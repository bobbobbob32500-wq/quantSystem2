# -*- coding: utf-8 -*-
"""
一键日报模块
自动化执行核心流程，生成综合量化日报
"""

import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from src.core.logger import get_logger
from src.core.config import ConfigManager
from src.core.database import DatabaseManager
from src.modules.data_updater import DataUpdater
from src.modules.position_controller import PositionController
from src.modules.stock_selector import StockSelector
from src.modules.hold_analyzer import HoldAnalyzer
from src.modules.message_pusher import MessagePusher
from src.modules.signal_feedback_evaluator import SignalFeedbackEvaluator
from src.modules.secondary_launch_menu import SecondaryLaunchMenu
from src.modules.backtest.history_recommendation_db import HistoryRecommendationDB
from src.modules.secondary_launch_intraday import detect_secondary_launch_signal
from src.modules.secondary_launch_intraday import explain_secondary_launch_blocked, blocker_tag_to_label

logger = get_logger("daily_report")


class DailyReportGenerator:
    """日报生成器"""
    
    def __init__(self, config: ConfigManager = None, db: DatabaseManager = None):
        """
        初始化日报生成器
        
        Args:
            config: 配置管理器
            db: 数据库管理器
        """
        if config is None:
            config = ConfigManager()
        if db is None:
            db = DatabaseManager(config)
        
        self.config = config
        self.db = db
        
        # 初始化各模块
        self.data_updater = DataUpdater(config, db)
        self.position_controller = PositionController(config, db)
        self.stock_selector = StockSelector(config, db)
        self.hold_analyzer = HoldAnalyzer(config, db)
        self.message_pusher = MessagePusher(config)
        self.signal_feedback = SignalFeedbackEvaluator(config, db)
        self.secondary_launch_selector = SecondaryLaunchMenu(config, db)
        self.history_db = HistoryRecommendationDB(
            str(self.config.get("feedback.history_recommendation_db", "data/history_recommendation.db"))
        )
        
        logger.info("日报生成器初始化完成")

    def _secondary_launch_tier_threshold_overrides(self) -> Dict[str, float]:
        """二次启动分层阈值：从配置读取，供盘中分层与日报复盘一致。"""
        return {
            "direct_score_min": float(self.config.get("stock_selection.secondary_launch.direct_score_min", 76.0) or 76.0),
            "direct_lgb_min": float(self.config.get("stock_selection.secondary_launch.direct_lgb_min", 0.58) or 0.58),
            "semi_score_min": float(self.config.get("stock_selection.secondary_launch.semi_score_min", 70.0) or 70.0),
            "semi_lgb_min": float(self.config.get("stock_selection.secondary_launch.semi_lgb_min", 0.55) or 0.55),
            "direct_conf_min": float(self.config.get("stock_selection.secondary_launch.direct_conf_min", 0.45) or 0.45),
            "semi_conf_min": float(self.config.get("stock_selection.secondary_launch.semi_conf_min", 0.58) or 0.58),
        }

    @staticmethod
    def _market_status_label(score: float) -> str:
        """根据评分映射市场状态标签。"""
        if score >= 80:
            return "强势"
        if score >= 60:
            return "偏强"
        if score >= 40:
            return "震荡"
        return "偏弱"

    @staticmethod
    def _score_color(score: float) -> str:
        """企业微信Markdown支持的颜色映射。"""
        if score >= 75:
            return "warning"
        if score >= 50:
            return "info"
        return "comment"

    def _extract_tradeability_thresholds(
        self,
        stocks: List[Dict],
        selection_end_date: str,
    ) -> Dict:
        """优先从选股结果提取门槛，缺失时回退到选择器快照。"""
        for stock in stocks or []:
            thresholds = stock.get("tradeability_thresholds")
            if thresholds:
                return thresholds
        return self.stock_selector.get_tradeability_thresholds(end_date=selection_end_date)
    
    def generate_report(self, skip_data_update: bool = False) -> Dict:
        """
        生成综合日报
        
        Args:
            skip_data_update: 是否跳过数据更新
        
        Returns:
            日报数据
        """
        logger.info("=" * 60)
        logger.info("开始生成量化综合日报...")
        logger.info("=" * 60)
        
        report_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        report_date = datetime.now().strftime("%Y-%m-%d")
        
        result = {
            "report_date": report_date,
            "report_time": report_time,
            "status": "success",
            "data_update": None,
            "market_analysis": None,
            "stock_selection": None,
            "stock_selection_meta": {},
            "secondary_launch_selection": [],
            "secondary_launch_meta": {},
            "secondary_launch_intraday_review": [],
            "hold_analysis": None,
            "feedback_summary": {},
        }
        
        try:
            # 1. 数据更新
            if not skip_data_update:
                logger.info("步骤1: 执行数据更新...")
                data_result = self.data_updater.run_full_update()
                result["data_update"] = data_result
            else:
                logger.info("步骤1: 跳过数据更新")
            
            # 2. 市场分析
            logger.info("步骤2: 执行市场分析...")
            try:
                market_result = self.position_controller.analyze_market()
                result["market_analysis"] = market_result
            except Exception as e:
                logger.error(f"市场分析失败: {e}")
                result["market_analysis"] = {"error": str(e)}
            
            # 3. 每日选股
            logger.info("步骤3: 执行每日选股...")
            try:
                stock_result = self.stock_selector.run_selection()
                result["stock_selection"] = stock_result

                selection_end_date = self.db.get_latest_trade_date("stock_daily")
                if not selection_end_date:
                    selection_end_date = datetime.now().strftime("%Y%m%d")
                thresholds = self._extract_tradeability_thresholds(
                    stock_result,
                    selection_end_date=selection_end_date,
                )
                selection_meta = {
                    "selection_end_date": selection_end_date,
                    "tradeability_thresholds": thresholds,
                }
                if self.stock_selector.use_dynamic_industry_strength:
                    selection_meta["industry_snapshot"] = self.stock_selector.get_dynamic_industry_strength(
                        end_date=selection_end_date,
                        top_n=3,
                    )
                result["stock_selection_meta"] = selection_meta
            except Exception as e:
                logger.error(f"每日选股失败: {e}")
                result["stock_selection"] = []
                result["stock_selection_meta"] = {"error": str(e)}

            logger.info("步骤3b: 执行二次启动策略选股...")
            try:
                secondary_end_date = self.db.get_latest_trade_date("stock_daily")
                if not secondary_end_date:
                    secondary_end_date = datetime.now().strftime("%Y%m%d")
                secondary_result = self.secondary_launch_selector.get_daily_selection(secondary_end_date)
                self.secondary_launch_selector.persist_daily_selection(
                    trade_date=secondary_end_date,
                    selections=secondary_result,
                )
                result["secondary_launch_selection"] = secondary_result
                result["secondary_launch_meta"] = self.secondary_launch_selector.get_selection_meta(secondary_end_date)
                result["secondary_launch_intraday_review"] = self._build_secondary_launch_intraday_review(
                    trade_date=secondary_end_date,
                    selections=secondary_result,
                    market_score=float((result.get("market_analysis") or {}).get("total_score", 50.0)),
                )
            except Exception as e:
                logger.error(f"二次启动策略选股失败: {e}")
                result["secondary_launch_selection"] = []
                result["secondary_launch_meta"] = {"error": str(e)}
                result["secondary_launch_intraday_review"] = []
            
            # 4. 持仓分析
            logger.info("步骤4: 执行持仓分析...")
            try:
                market_score = result["market_analysis"].get("total_score", 50.0) if result.get("market_analysis") else 50.0
                hold_result = self.hold_analyzer.run_analysis(market_score)
                result["hold_analysis"] = hold_result
            except Exception as e:
                logger.error(f"持仓分析失败: {e}")
                result["hold_analysis"] = {"error": str(e)}

            # 5. 信号闭环摘要（用于日报/推送）
            feedback_enabled = bool(self.config.get("feedback.snapshot_enabled", True))
            if feedback_enabled:
                logger.info("步骤5: 生成信号闭环摘要...")
                try:
                    selection_end_date = (
                        result.get("stock_selection_meta", {}).get("selection_end_date")
                        if isinstance(result.get("stock_selection_meta"), dict)
                        else None
                    )
                    end_date = selection_end_date or self.db.get_latest_trade_date("stock_daily")
                    lookback_days = int(self.config.get("feedback.snapshot_lookback_days", 90))
                    top_n = int(self.config.get("feedback.snapshot_top_n_per_day", self.config.get("feedback.top_n_per_day", 10)))
                    rec_h = self.config.get("feedback.snapshot_recommendation_horizons", self.config.get("feedback.recommendation_horizons", [2, 3, 4, 5]))
                    sig_h = self.config.get("feedback.snapshot_signal_horizons", self.config.get("feedback.signal_horizons", [1, 2, 3]))
                    min_samples_for_best = int(self.config.get("feedback.snapshot_min_samples_for_best", 10))

                    start_date = None
                    if end_date:
                        dt = datetime.strptime(str(end_date), "%Y%m%d")
                        start_date = (dt - timedelta(days=lookback_days)).strftime("%Y%m%d")

                    feedback_summary = self.signal_feedback.build_feedback_snapshot(
                        start_date=start_date,
                        end_date=end_date,
                        top_n_per_day=top_n,
                        recommendation_horizons=rec_h,
                        signal_horizons=sig_h,
                        min_samples_for_best=min_samples_for_best,
                    )
                    result["feedback_summary"] = feedback_summary
                except Exception as e:
                    logger.error(f"信号闭环摘要生成失败: {e}")
                    result["feedback_summary"] = {"error": str(e)}
            
            logger.info("=" * 60)
            logger.info("量化综合日报生成完成")
            logger.info("=" * 60)
            
        except Exception as e:
            result["status"] = "failed"
            result["error"] = str(e)
            logger.error(f"日报生成失败: {e}")
        
        return result

    def _build_secondary_launch_intraday_review(
        self,
        trade_date: str,
        selections: List[Dict],
        market_score: float = 50.0,
    ) -> List[Dict]:
        """复盘二次启动当日盘中是否出现买点，以及触发/未触发原因。"""
        review_rows: List[Dict] = []
        if not trade_date or not selections:
            return review_rows

        day_text = f"{str(trade_date)[:4]}-{str(trade_date)[4:6]}-{str(trade_date)[6:8]}"
        for item in selections[:10]:
            symbol = str(item.get("ts_code", "") or "").strip().upper()
            if not symbol:
                continue
            minute_df = self.history_db.get_intraday_data(symbol)
            if not minute_df.empty:
                minute_df = minute_df.copy()
                minute_df["trade_date_str"] = minute_df["trade_time"].dt.strftime("%Y-%m-%d")
                minute_df = minute_df[minute_df["trade_date_str"] == day_text].copy()
                minute_df = minute_df.sort_values("trade_time").reset_index(drop=True)

            row = {
                "ts_code": symbol,
                "name": str(item.get("name", "") or ""),
                "has_buy_signal": False,
                "signal_type": "",
                "trigger_time": "",
                "push_reason": "",
                "not_pushed_reason": "",
                "blocker_tag": "",
                "blocker_detail": "",
                "confidence": 0.0,
            }
            if minute_df.empty:
                row["not_pushed_reason"] = "缺少当日分钟数据"
                review_rows.append(row)
                continue

            candidate = {
                "symbol": symbol,
                "name": row["name"],
                "score": float(item.get("signal_score", item.get("total_score", 80.0)) or 80.0),
                "signal_score": float(item.get("signal_score", item.get("total_score", 80.0)) or 80.0),
                "rank": int(item.get("rank", 1) or 1),
                "pool_type": "core" if int(item.get("rank", 1) or 1) == 1 else "reserve",
                "industry": str(item.get("industry", "") or ""),
                "strategy_profile": "secondary_launch",
            }
            if item.get("lgb_prob") is not None:
                try:
                    candidate["lgb_prob"] = float(item.get("lgb_prob"))
                except (TypeError, ValueError):
                    pass
            candidate.update(self._secondary_launch_tier_threshold_overrides())
            for _k in ("pct_chg", "vol_ratio_5", "upper_shadow_pct"):
                if item.get(_k) is not None:
                    candidate[_k] = item[_k]
            if not any(candidate.get(_k) is not None for _k in ("pct_chg", "vol_ratio_5", "upper_shadow_pct")):
                ej = item.get("extra_json")
                if ej:
                    try:
                        extra = json.loads(ej) if isinstance(ej, str) else ej
                        v3 = (extra or {}).get("v3_daily_gate") or {}
                        for _k in ("pct_chg", "vol_ratio_5", "upper_shadow_pct"):
                            if v3.get(_k) is not None:
                                candidate[_k] = v3[_k]
                    except (json.JSONDecodeError, TypeError, ValueError):
                        pass
            neutral_industry = {"score": 50.0, "level": "neutral", "industry": candidate["industry"] or "未知"}
            market_confirm = {"market_score": float(market_score or 50.0)}

            triggered = None
            for idx in range(len(minute_df)):
                frame = minute_df.iloc[: idx + 1].copy()
                now = frame.iloc[-1]["trade_time"].to_pydatetime()
                current_price = float(frame.iloc[-1]["close"])
                signal = detect_secondary_launch_signal(
                    candidate=candidate,
                    quote={"price": current_price},
                    now=now,
                    minute_df=frame,
                    industry_confirm=neutral_industry,
                    market_confirm=market_confirm,
                )
                if signal.signal:
                    triggered = signal
                    row["has_buy_signal"] = True
                    row["signal_type"] = str(signal.signal_type or "")
                    row["trigger_time"] = now.strftime("%H:%M:%S")
                    row["confidence"] = round(float(signal.confidence or 0.0), 4)
                    details = signal.details or {}
                    row["push_reason"] = str(details.get("entry_trigger", "") or signal.reason or "")
                    break

            if not row["has_buy_signal"]:
                blocked = explain_secondary_launch_blocked(
                    candidate=candidate,
                    minute_df=minute_df,
                    industry_confirm=neutral_industry,
                    market_confirm=market_confirm,
                )
                row["confidence"] = round(float(blocked.get("confidence", 0.0) or 0.0), 4)
                row["not_pushed_reason"] = str(blocked.get("reason", "") or "未触发有效买点")
                row["blocker_tag"] = str(blocked.get("blocker_tag", "") or "")
                row["blocker_label"] = blocker_tag_to_label(row["blocker_tag"])
                row["blocker_detail"] = str(blocked.get("blocker_detail", "") or "")
                row["trigger_time"] = str(blocked.get("trigger_time", "") or "")
                row["signal_type"] = str(blocked.get("signal_type", "") or "")
            review_rows.append(row)
        return review_rows
    
    def format_report(self, result: Dict) -> str:
        """
        格式化日报为文本
        
        Args:
            result: 日报数据
        
        Returns:
            格式化的日报文本
        """
        lines = []
        
        # 标题
        lines.extend([
            "=" * 70,
            "                    A股量化交易辅助系统 - 综合日报",
            "=" * 70,
            f"报告日期: {result['report_date']}",
            f"生成时间: {result['report_time']}",
            "=" * 70,
            ""
        ])
        
        # 数据更新结果
        if result.get("data_update"):
            data = result["data_update"]
            lines.extend([
                "-" * 70,
                "【数据更新】",
                f"  状态: {'成功' if data.get('status') == 'success' else '失败'}",
                f"  股票基础信息: {data.get('stock_basic_count', 0)}条",
                f"  日线数据: {data.get('daily_data_count', 0)}条",
                f"  指数数据: {data.get('index_data_count', 0)}条",
                ""
            ])
        
        # 市场分析结果
        if result.get("market_analysis") and "error" not in result["market_analysis"]:
            market = result["market_analysis"]
            lines.extend([
                "-" * 70,
                "【市场分析】",
                f"  综合评分: {market.get('total_score', 0)}分",
                f"  趋势得分: {market.get('trend_score', 0)}分 (权重{market.get('trend_weight', 0.4)})",
                f"  宽度得分: {market.get('width_score', 0)}分 (权重{market.get('width_weight', 0.35)})",
                f"  量能得分: {market.get('volume_score', 0)}分 (权重{market.get('volume_weight', 0.25)})",
                f"  市场转弱: {'是' if market.get('market_weak') else '否'}",
                f"  操作建议: {market.get('suggestion', '')}",
                ""
            ])
        
        # 选股结果
        if result.get("stock_selection"):
            stocks = result["stock_selection"]
            lines.extend([
                "-" * 70,
                f"【每日选股】 共{len(stocks)}只",
                ""
            ])
            for i, stock in enumerate(stocks[:10], 1):  # 只显示前10只
                lines.append(f"  {i}. {stock['ts_code']} {stock['name']}")
                lines.append(f"     得分: {stock['total_score']}分 ({stock['level']})")
                lines.append(f"     行业: {stock.get('industry', '未知')}")
                lines.append("")

            selection_meta = result.get("stock_selection_meta", {})
            thresholds = selection_meta.get("tradeability_thresholds", {}) if isinstance(selection_meta, dict) else {}
            if thresholds:
                lines.extend([
                    "【盘前动态门槛】",
                    f"  数据截止: {selection_meta.get('selection_end_date', '-')}",
                    f"  门槛来源: {thresholds.get('source', 'unknown')} (样本{thresholds.get('sample_size', 0)})",
                    f"  20日均成交额 >= {float(thresholds.get('min_avg_amount_20d', 0)):.0f}",
                    f"  20日涨停次数 <= {int(thresholds.get('max_recent_limit_up_count_20d', 0))}",
                    f"  20日涨幅 <= {float(thresholds.get('max_recent_return_20d', 0)):.1f}%",
                    f"  10日均振幅 <= {float(thresholds.get('max_avg_amplitude_10d', 0)):.1f}%",
                    f"  当日涨幅 <= {float(thresholds.get('max_latest_pct_chg', 0)):.1f}%",
                    ""
                ])

        if result.get("secondary_launch_selection"):
            stocks = result["secondary_launch_selection"]
            meta = result.get("secondary_launch_meta", {}) if isinstance(result.get("secondary_launch_meta"), dict) else {}
            params = meta.get("strategy_params", {}) if isinstance(meta.get("strategy_params"), dict) else {}
            lines.extend([
                "-" * 70,
                f"【二次启动策略】 共{len(stocks)}只",
                f"  策略标签: {meta.get('strategy_label', '二次启动策略')}",
                f"  持有周期: {params.get('hold_days', '-')}",
                f"  回撤区间: {float(params.get('drawdown_min', 0)):.2%} ~ {float(params.get('drawdown_max', 0)):.2%}",
                f"  缩量系数: {float(params.get('vol_shrink_ratio', 0)):.2f}",
                ""
            ])
            for i, stock in enumerate(stocks[:10], 1):
                lines.append(f"  {i}. {stock['ts_code']} {stock['name']}")
                lines.append(
                    f"     RS20: {float(stock.get('rs20', 0)):.3f} | "
                    f"回撤: {float(stock.get('drawdown_from_peak', 0)):.2%} | "
                    f"距涨停: {int(stock.get('days_since_last_limit_up', 0))}天"
                )
                lines.append("")

        intraday_review = result.get("secondary_launch_intraday_review") or []
        if intraday_review:
            lines.extend([
                "-" * 70,
                "【二次启动盘中复盘】",
                ""
            ])
            for item in intraday_review:
                lines.append(f"  {item.get('ts_code', '')} {item.get('name', '')}")
                if item.get("has_buy_signal"):
                    lines.append(
                        f"    是否有买点: 是 | 类型: {item.get('signal_type', '-')}"
                    )
                    lines.append(
                        f"    触发时间: {item.get('trigger_time', '-')} | 置信度: {float(item.get('confidence', 0)):.2f}"
                    )
                    lines.append(f"    推送原因: {item.get('push_reason', '-')}")
                else:
                    lines.append(
                        f"    是否有买点: 否 | 末次置信度: {float(item.get('confidence', 0)):.2f}"
                    )
                    lines.append(f"    未推送原因: {item.get('not_pushed_reason', '-')}")
                    if item.get("blocker_label") or item.get("blocker_tag"):
                        lines.append(f"    拦截标签: {item.get('blocker_label', item.get('blocker_tag', '-'))}")
                    if item.get("blocker_detail"):
                        lines.append(f"    拦截说明: {item.get('blocker_detail', '-')}")
                lines.append("")
        
        # 持仓分析结果
        if result.get("hold_analysis") and "error" not in result["hold_analysis"]:
            hold = result["hold_analysis"]
            lines.extend([
                "-" * 70,
                "【持仓分析】",
                f"  持仓数量: {hold.get('hold_count', 0)}只",
                f"  总市值: {hold.get('total_market_value', 0)}元",
                f"  总盈亏: {hold.get('total_profit', 0)}元",
                ""
            ])
            
            for h in hold.get("holds", [])[:5]:  # 只显示前5只
                lines.append(f"  {h['ts_code']} {h['name']}")
                lines.append(f"    盈亏: {h['profit']}% ({h['profit_amount']}元)")
                lines.append(f"    风险: {h['risk_level']}")
                lines.append(f"    建议: {h['suggestion']}")
                lines.append("")

        feedback = result.get("feedback_summary", {}) if isinstance(result.get("feedback_summary"), dict) else {}
        if feedback and "error" not in feedback:
            lines.extend([
                "-" * 70,
                "【信号闭环摘要】",
                f"  回看窗口: {feedback.get('start_date', '-')} ~ {feedback.get('end_date', '-')}",
                f"  样本规模: 盘前{feedback.get('recommendation_detail_count', 0)}条 | 盘中{feedback.get('signal_detail_count', 0)}条",
                ""
            ])
            pre_best = feedback.get("pre_market_best")
            if pre_best:
                lines.append(
                    f"  盘前最佳: T+{int(pre_best.get('horizon', 0))} "
                    f"胜率{float(pre_best.get('win_rate', 0)):.1%} "
                    f"均值{float(pre_best.get('mean_net_return', 0)):.2%}"
                )
            sell_best = feedback.get("intraday_sell_best")
            if sell_best:
                lines.append(
                    f"  卖点最佳: T+{int(sell_best.get('horizon', 0))} "
                    f"胜率{float(sell_best.get('win_rate', 0)):.1%} "
                    f"均值{float(sell_best.get('mean_net_return', 0)):.2%}"
                )
            buy_best = feedback.get("intraday_buy_best")
            if buy_best:
                lines.append(
                    f"  买点最佳: T+{int(buy_best.get('horizon', 0))} "
                    f"胜率{float(buy_best.get('win_rate', 0)):.1%} "
                    f"均值{float(buy_best.get('mean_net_return', 0)):.2%}"
                )
            lines.append("")
        
        lines.extend([
            "=" * 70,
            "                    报告结束",
            "=" * 70
        ])
        
        return "\n".join(lines)
    
    def format_markdown_report(self, result: Dict) -> str:
        """
        格式化日报为Markdown（用于企业微信推送）
        
        Args:
            result: 日报数据
        
        Returns:
            Markdown格式文本
        """
        lines = []
        stocks = result.get("stock_selection") or []
        hold = result.get("hold_analysis", {}) or {}
        hold_count = int(hold.get("hold_count", 0)) if isinstance(hold, dict) else 0
        selection_meta = result.get("stock_selection_meta", {}) or {}
        thresholds = (
            selection_meta.get("tradeability_thresholds", {})
            if isinstance(selection_meta, dict)
            else {}
        )

        lines.extend([
            "## 📊 A股量化交易辅助日报",
            "",
            f"**日期**: {result['report_date']}",
            f"**时间**: {result['report_time']}",
            f"**概览**: 选股 `{len(stocks)}` 只 | 持仓 `{hold_count}` 只",
            "",
            "> 盘前选股 + 盘中监控辅助，仅供交易决策参考",
            "",
            "---",
            ""
        ])

        market = result.get("market_analysis", {})
        if market and "error" not in market:
            score = float(market.get("total_score", 0))
            status = self._market_status_label(score)
            color = self._score_color(score)
            lines.extend([
                "### 🧭 市场状态",
                f"**综合评分**: <font color=\"{color}\">{score:.1f}分</font> ({status})",
                f"- 趋势: {market.get('trend_score', 0)}分 | 宽度: {market.get('width_score', 0)}分 | 量能: {market.get('volume_score', 0)}分",
                f"- 建议: {market.get('suggestion', '无')}",
                "",
                "---",
                ""
            ])

        if thresholds:
            source = str(thresholds.get("source", "unknown"))
            source_desc = "动态分位数" if source.startswith("dynamic") else "静态回退"
            lines.extend([
                "### ⚙️ 盘前动态门槛",
                f"- 截止交易日: `{selection_meta.get('selection_end_date', '-')}`",
                f"- 门槛来源: `{source_desc}` (样本 `{int(thresholds.get('sample_size', 0))}`)",
                f"- 20日均成交额 ≥ `{float(thresholds.get('min_avg_amount_20d', 0)):.0f}`",
                f"- 20日涨停次数 ≤ `{int(thresholds.get('max_recent_limit_up_count_20d', 0))}`",
                f"- 20日涨幅 ≤ `{float(thresholds.get('max_recent_return_20d', 0)):.1f}%`",
                f"- 10日均振幅 ≤ `{float(thresholds.get('max_avg_amplitude_10d', 0)):.1f}%`",
                f"- 当日涨幅 ≤ `{float(thresholds.get('max_latest_pct_chg', 0)):.1f}%`",
                "",
            ])
            industry_snapshot = selection_meta.get("industry_snapshot", []) if isinstance(selection_meta, dict) else []
            if industry_snapshot:
                top_desc = "、".join(
                    f"{item.get('industry', '未知')}({float(item.get('heat_score', 0)):.1f})"
                    for item in industry_snapshot[:3]
                )
                lines.append(f"- 行业热度TOP3: {top_desc}")
                lines.append("")
            lines.extend(["---", ""])

        if stocks:
            lines.extend([
                "### 🎯 盘前选股TOP10",
                ""
            ])
            for i, stock in enumerate(stocks[:10], 1):
                total_score = float(stock.get("total_score", 0))
                score_color = self._score_color(total_score)
                lines.append(
                    f"{i}. **{stock.get('ts_code', '')} {stock.get('name', '')}** "
                    f"<font color=\"{score_color}\">{total_score:.1f}分</font> "
                    f"({stock.get('level', '观望')})"
                )
                lines.append(
                    f"- 行业: {stock.get('industry', '未知')} | "
                    f"短周期: {float(stock.get('short_cycle_score', 0)):.1f} | "
                    f"可交易: {float(stock.get('tradeability_score', 0)):.1f}"
                )
            lines.extend(["", "---", ""])
        else:
            lines.extend([
                "### 🎯 盘前选股TOP10",
                "- 当日未筛选出满足门槛的标的",
                "",
                "---",
                ""
            ])

        secondary_stocks = result.get("secondary_launch_selection") or []
        secondary_meta = result.get("secondary_launch_meta", {}) or {}
        secondary_params = (
            secondary_meta.get("strategy_params", {})
            if isinstance(secondary_meta, dict)
            else {}
        )
        lines.extend([
            "### 🚀 二次启动策略",
            f"- 策略标签: {secondary_meta.get('strategy_label', '二次启动策略（walk-forward 优化版）')}",
            f"- 候选数量: `{len(secondary_stocks)}`",
        ])
        if secondary_params:
            lines.append(
                f"- 参数: 持有`{secondary_params.get('hold_days', '-')}`天 | "
                f"回撤`{float(secondary_params.get('drawdown_min', 0)):.2%}~{float(secondary_params.get('drawdown_max', 0)):.2%}` | "
                f"缩量`{float(secondary_params.get('vol_shrink_ratio', 0)):.2f}`"
            )
        if secondary_stocks:
            for i, stock in enumerate(secondary_stocks[:5], 1):
                lines.append(
                    f"{i}. **{stock.get('ts_code', '')} {stock.get('name', '')}** | "
                    f"RS20 `{float(stock.get('rs20', 0)):.3f}` | "
                    f"回撤 `{float(stock.get('drawdown_from_peak', 0)):.2%}`"
                )
        else:
            lines.append("- 当日无满足二次启动条件的标的")
        lines.extend(["", "---", ""])

        intraday_review = result.get("secondary_launch_intraday_review") or []
        if intraday_review:
            lines.extend([
                "### 🕒 二次启动盘中复盘",
                "",
            ])
            for item in intraday_review[:10]:
                if item.get("has_buy_signal"):
                    lines.append(
                        f"- **{item.get('ts_code', '')} {item.get('name', '')}** | "
                        f"买点 `是` | 类型 `{item.get('signal_type', '-')}` | "
                        f"时间 `{item.get('trigger_time', '-')}` | "
                        f"原因 `{item.get('push_reason', '-')}`"
                    )
                else:
                    lines.append(
                        f"- **{item.get('ts_code', '')} {item.get('name', '')}** | "
                        f"买点 `否` | "
                        f"末次置信度 `{float(item.get('confidence', 0)):.2f}` | "
                        f"未推送 `{item.get('not_pushed_reason', '-')}`"
                    )
                    if item.get("blocker_tag") or item.get("blocker_detail"):
                        lines.append(
                            f"  - 拦截标签 `{item.get('blocker_label', item.get('blocker_tag', '-')) or '-'}` | "
                            f"说明 `{item.get('blocker_detail', '-') or '-'}`"
                        )
            lines.extend(["", "---", ""])

        if hold and "error" not in hold:
            lines.extend([
                "### 📦 持仓状态",
                f"- 持仓数量: {hold_count}只",
                f"- 总盈亏: {hold.get('total_profit', 0)}元",
                ""
            ])
            for h in hold.get("holds", [])[:3]:
                lines.append(
                    f"- {h.get('name', '')}: {h.get('profit', 0)}% "
                    f"({h.get('risk_level', '未知')}) | {h.get('suggestion', '')}"
                )

        feedback = result.get("feedback_summary", {}) if isinstance(result.get("feedback_summary"), dict) else {}
        if feedback and "error" not in feedback:
            lines.extend(["", "---", "", "### 🔁 信号闭环摘要"])
            lines.append(
                f"- 回看窗口: `{feedback.get('start_date', '-')}` ~ `{feedback.get('end_date', '-')}`"
            )
            lines.append(
                f"- 样本规模: 盘前 `{int(feedback.get('recommendation_detail_count', 0))}` 条 | "
                f"盘中 `{int(feedback.get('signal_detail_count', 0))}` 条"
            )
            pre_best = feedback.get("pre_market_best")
            if pre_best:
                lines.append(
                    f"- 盘前最佳窗口: `T+{int(pre_best.get('horizon', 0))}` | "
                    f"胜率 `{float(pre_best.get('win_rate', 0)):.2%}` | "
                    f"均值净收益 `{float(pre_best.get('mean_net_return', 0)):.2%}`"
                )
            sell_best = feedback.get("intraday_sell_best")
            if sell_best:
                lines.append(
                    f"- 卖点最佳窗口: `T+{int(sell_best.get('horizon', 0))}` | "
                    f"胜率 `{float(sell_best.get('win_rate', 0)):.2%}` | "
                    f"方向收益均值 `{float(sell_best.get('mean_net_return', 0)):.2%}`"
                )
            buy_best = feedback.get("intraday_buy_best")
            if buy_best:
                lines.append(
                    f"- 买点最佳窗口: `T+{int(buy_best.get('horizon', 0))}` | "
                    f"胜率 `{float(buy_best.get('win_rate', 0)):.2%}` | "
                    f"方向收益均值 `{float(buy_best.get('mean_net_return', 0)):.2%}`"
                )

        lines.extend(["", "---", "*由量化交易辅助系统自动生成*"])
        return "\n".join(lines)
    
    def run_and_push(self, skip_data_update: bool = False) -> Dict:
        """
        生成日报并推送
        
        Args:
            skip_data_update: 是否跳过数据更新
        
        Returns:
            日报数据
        """
        # 生成日报
        result = self.generate_report(skip_data_update)
        
        # 推送到企业微信
        if result["status"] == "success":
            markdown_content = self.format_markdown_report(result)
            self.message_pusher.push_markdown(markdown_content)
            logger.info("日报已推送到企业微信")
        
        return result
    
    def save_report(self, result: Dict) -> bool:
        """
        保存日报到数据库
        
        Args:
            result: 日报数据
        
        Returns:
            是否成功
        """
        try:
            report_text = self.format_report(result)
            
            sql = """
                INSERT INTO system_log (log_time, log_level, module_name, log_content)
                VALUES (?, ?, ?, ?)
            """
            
            self.db.execute(sql, (
                result['report_time'],
                "INFO",
                "daily_report",
                f"日报生成完成 - 市场评分:{result.get('market_analysis', {}).get('total_score', 0)}分"
            ))
            
            logger.info("日报已保存到数据库")
            return True
        except Exception as e:
            logger.error(f"保存日报失败: {e}")
            return False
