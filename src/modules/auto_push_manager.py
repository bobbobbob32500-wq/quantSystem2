# -*- coding: utf-8 -*-
"""
自动推送管理模块
整合各核心模块的自动推送到企业微信功能
"""

import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.core.logger import get_logger
from src.core.config import ConfigManager
from src.core.database import DatabaseManager
from src.modules.message_pusher import MessagePusher
from src.modules.position_controller import PositionController
from src.modules.stock_selector import StockSelector
from src.modules.hold_analyzer import HoldAnalyzer
from src.modules.risk_controller import RiskController
from src.modules.daily_report import DailyReportGenerator
from src.modules.secondary_launch_menu import SecondaryLaunchMenu
from src.modules.trade_plan import TradePlanGenerator
from src.modules.post_market import PostMarketWorker
from src.modules.position_event_store import PositionEventStore
from src.modules.signal_feedback_evaluator import SignalFeedbackEvaluator

logger = get_logger("auto_push")


class AutoPushManager:
    """自动推送管理器"""
    
    def __init__(self, config: ConfigManager = None, db: DatabaseManager = None):
        """
        初始化自动推送管理器
        
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
        self.pusher = MessagePusher(config, db)
        
        # 初始化各模块
        self.position_controller = PositionController(config, db)
        self.stock_selector = StockSelector(config, db)
        self.hold_analyzer = HoldAnalyzer(config, db)
        self.risk_controller = RiskController(config, db)
        self.daily_report = DailyReportGenerator(config, db)
        self.secondary_launch_selector = SecondaryLaunchMenu(config, db)
        self.trade_plan = TradePlanGenerator(config, db)
        self.post_market = PostMarketWorker(config, db)
        self.signal_feedback = SignalFeedbackEvaluator(config, db)
        self.position_event_store = PositionEventStore(db)
        # 通用推送 outbox（消息失败不丢）
        from src.modules.push_outbox_store import PushOutboxStore
        self.push_outbox = PushOutboxStore(db)
        self.push_cache_path = Path(__file__).resolve().parents[2] / "data" / "cache" / "push_payload_cache.json"
        self.push_cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.push_cache_ttl_seconds = int(self.config.get("push.web_cache_ttl_seconds", 900) or 900)

        # 持仓事件推送控制
        self.position_event_cooldown_minutes = int(
            config.get("push.position_event_cooldown_minutes", 30)
        )
        self.position_retry_max_attempts = int(
            config.get("push.position_retry_max_attempts", 3)
        )
        self.position_retry_delay_seconds = int(
            config.get("push.position_retry_delay_seconds", 60)
        )
        self.position_retry_batch_size = int(
            config.get("push.position_retry_batch_size", 20)
        )
        self.outbox_retry_batch_size = int(
            config.get("push.outbox_retry_batch_size", 30)
        )
        self.outbox_retry_delay_seconds = int(
            config.get("push.outbox_retry_delay_seconds", 60)
        )
        
        # 记录上次推送的市场状态（用于判断是否异常）
        self.last_market_score = None  # 存储目标仓位
        self.last_market_regime = None  # 存储市场状态
        
        logger.info("自动推送管理器初始化完成")
    
    def push_market_analysis(self, force: bool = False) -> bool:
        """
        推送市场分析结果（使用仓位控制引擎）

        Args:
            force: 是否强制推送（忽略异常检测）

        Returns:
            是否成功
        """
        try:
            logger.info("执行市场分析并推送...")

            result = self.position_controller.analyze_market()

            # 判断是否需要推送
            should_push = force
            position_change = 0

            if self.last_market_score is not None:
                position_change = result["target_position"] - self.last_market_score
                # 仓位变化超过10%或市场状态变化时推送
                if abs(position_change) >= 0.1 or result["market_regime"] != self.last_market_regime:
                    should_push = True
            else:
                should_push = True

            self.last_market_score = result["target_position"]
            self.last_market_regime = result["market_regime"]

            if not should_push:
                logger.info("市场分析无显著变化，不推送")
                return False

            # 构建推送内容
            regime_emoji = self._get_regime_emoji(result["market_regime"])

            content = f"""## {regime_emoji} 仓位控制分析报告

**时间**: {datetime.now().strftime('%Y-%m-%d %H:%M')}

### 市场状态: {result['market_regime']}
### 目标仓位: {result['target_position']*100:.0f}%
### 仓位等级: {result['position_level']}

**策略建议**: {result['strategy_suggestion']}

### 模块状态

| 模块 | 状态 | 强度 |
|------|------|------|
| 趋势 | {result['trend_state']} | {result['trend_strength']:.2f} |
| 资金 | {result['money_state']} | {result['money_strength']:.2f} |
| 情绪 | {result['sentiment_state']} | {result['sentiment_strength']:.2f} |
| 风险 | {result['risk_state']} | {result['risk_strength']:.2f} |

### 关键机制

- 风险一票否决: {'已触发' if result['risk_state'] == 'HIGH' else '未触发'}
- 情绪调整: {'已触发' if result['sentiment_state'] in ['OVERHEATED', 'COLD'] else '未触发'}"""

            if position_change != 0:
                change_emoji = "📈" if position_change > 0 else "📉"
                content += f"\n\n**仓位变化**: {change_emoji} {position_change*100:+.0f}%"

            return self.pusher.push_markdown(content)

        except Exception as e:
            logger.error(f"市场分析推送失败: {e}")
            return False
    
    def push_risk_signals(self) -> bool:
        """
        推送风控信号（仅在有信号时推送）
        
        Returns:
            是否成功
        """
        try:
            logger.info("执行风控检测...")
            
            # 获取持仓列表
            hold_list = self.hold_analyzer.get_hold_list()
            
            if not hold_list:
                logger.info("无持仓，跳过风控检测")
                return self.retry_position_events()
            
            # 获取市场评分
            market_result = self.position_controller.analyze_market()
            # 将目标仓位转换为市场评分（0-100）
            market_score = market_result.get("target_position", 0.5) * 100
            
            # 执行风控检测
            result = self.risk_controller.run_risk_check(hold_list, market_score)
            
            signals = result.get("signals", [])
            hold_map = {
                str(item.get("ts_code", "")).upper(): item for item in hold_list
            }

            new_event_count = 0
            for signal in signals:
                event = self._build_position_event(
                    signal=signal,
                    hold_map=hold_map,
                    market_result=market_result,
                )
                if self.position_event_store.enqueue_event(
                    event,
                    max_retry=self.position_retry_max_attempts,
                ):
                    new_event_count += 1

            if new_event_count > 0:
                logger.info("持仓事件已入队: %d", new_event_count)
            else:
                logger.info("无新增持仓事件，尝试重试队列")

            return self.retry_position_events()
            
        except Exception as e:
            logger.error(f"风控信号推送失败: {e}")
            return False

    def retry_position_events(self) -> bool:
        """
        推送持仓事件队列（含失败重试）。
        """
        try:
            pending_events = self.position_event_store.list_retryable_events(
                limit=self.position_retry_batch_size
            )
            if not pending_events:
                logger.info("持仓事件重试队列为空")
                return False

            success_count = 0
            for event in pending_events:
                event_id = str(event.get("event_id", ""))
                if not event_id:
                    continue

                push_ok = self.pusher.push_position_events([event], now=datetime.now())
                if push_ok:
                    self.position_event_store.mark_success(event_id)
                    success_count += 1
                else:
                    self.position_event_store.mark_failed(
                        event_id=event_id,
                        error="position push failed",
                        retry_delay_seconds=self.position_retry_delay_seconds,
                    )

            logger.info(
                "持仓事件推送完成: success=%d, total=%d",
                success_count,
                len(pending_events),
            )
            return success_count == len(pending_events)
        except Exception as e:
            logger.error(f"持仓事件重试失败: {e}")
            return False

    def retry_push_outbox(self) -> bool:
        """
        重试通用推送 outbox（盘前/盘中/盘后 markdown 推送失败不丢）。
        """
        try:
            pending = self.push_outbox.list_retryable(limit=self.outbox_retry_batch_size)
            if not pending:
                logger.info("push_outbox 重试队列为空")
                return False

            success = 0
            for row in pending:
                row_id = int(row.get("id", 0) or 0)
                channel = str(row.get("channel", "wechat") or "wechat")
                msg_type = str(row.get("msg_type", "markdown") or "markdown")
                payload = row.get("payload") or {}
                if row_id <= 0:
                    continue

                if msg_type != "markdown":
                    self.push_outbox.mark_failed(row_id, error=f"unsupported_msg_type:{msg_type}", retry_delay_seconds=self.outbox_retry_delay_seconds)
                    continue

                content = str(payload.get("content", "") or "")
                if not content.strip():
                    self.push_outbox.mark_failed(row_id, error="empty_markdown_content", retry_delay_seconds=self.outbox_retry_delay_seconds)
                    continue

                ok = self.pusher.push_markdown(content, channel=channel, enqueue_on_fail=False)
                if ok:
                    self.push_outbox.mark_success(row_id)
                    success += 1
                else:
                    self.push_outbox.mark_failed(row_id, error="outbox_retry_failed", retry_delay_seconds=self.outbox_retry_delay_seconds)

            logger.info("push_outbox 重试完成: success=%d total=%d", success, len(pending))
            return success == len(pending)
        except Exception as exc:
            logger.error("push_outbox 重试异常: %s", exc)
            return False
    
    def push_daily_report(self) -> bool:
        """
        推送盘前选股计划（兼容旧接口名）。
        
        Returns:
            是否成功
        """
        return self.push_pre_market_selection()

    def push_pre_market_selection(self, strategy: str = "both") -> bool:
        """
        推送盘前选股计划（计划型模板）。
        """
        try:
            logger.info("生成并推送盘前选股计划...")
            strategy_key = str(strategy or "both").strip().lower()
            cache_key = f"pre_market::{strategy_key}"
            cached_payload = self._load_push_cache(cache_key)
            if cached_payload:
                return self._push_cached_pre_market_payload(strategy_key, cached_payload)

            result = self.daily_report.generate_report(skip_data_update=True)
            push_legacy = strategy_key in {"legacy", "both"}
            push_secondary = strategy_key in {"secondary_launch", "secondary", "both"}

            success = True
            cache_payload: Dict[str, Any] = {"trade_date": None}
            if push_legacy:
                strategy_profile = str(getattr(self.stock_selector, "strategy_profile", "legacy")).lower()
                strategy_label = (
                    "增强策略（enhanced / 6因子）"
                    if strategy_profile == "enhanced"
                    else "原策略优化版（legacy_opt / 5因子）"
                    if strategy_profile == "legacy_opt"
                    else "基准原策略（legacy / 5因子）"
                )
                result["strategy_label"] = strategy_label
                success = self.pusher.push_pre_market_selection(result)
                cache_payload["legacy_payload"] = result

            selection_end_date = (
                result.get("secondary_launch_meta", {}).get("selection_end_date")
                if isinstance(result.get("secondary_launch_meta"), dict)
                else None
            )
            if not selection_end_date:
                selection_end_date = self.db.get_latest_trade_date("stock_daily")
            cache_payload["trade_date"] = selection_end_date

            secondary_payload = self.secondary_launch_selector.build_push_payload(
                trade_date=selection_end_date,
                market_analysis=result.get("market_analysis", {}),
            )
            secondary_success = True
            if push_secondary and secondary_payload.get("stock_selection"):
                self.secondary_launch_selector.persist_daily_selection(
                    trade_date=selection_end_date,
                    selections=secondary_payload.get("stock_selection", []),
                )
                secondary_payload["strategy_label"] = "二次启动策略"
                secondary_success = self.pusher.push_pre_market_selection(secondary_payload)
                cache_payload["secondary_payload"] = secondary_payload

            self._save_push_cache(cache_key, cache_payload)

            return bool(success and secondary_success)

        except Exception as e:
            logger.error(f"盘前选股计划推送失败: {e}")
            return False
    
    def push_trade_plan(self) -> bool:
        """
        推送交易计划
        
        Returns:
            是否成功
        """
        try:
            logger.info("生成并推送交易计划...")
            
            plan = self.trade_plan.generate_plan()
            
            # 转换为Markdown格式
            content = self._convert_plan_to_markdown(plan)
            
            return self.pusher.push_markdown(content)
            
        except Exception as e:
            logger.error(f"交易计划推送失败: {e}")
            return False
    
    def push_post_market_summary(self, strategy: str = "secondary_launch") -> bool:
        """
        推送盘后复盘结论
        
        Returns:
            是否成功
        """
        try:
            logger.info("生成并推送盘后复盘结论...")
            strategy_key = str(strategy or "secondary_launch").strip().lower()
            cache_key = f"post_market::{strategy_key}"
            cached_payload = self._load_push_cache(cache_key)
            if cached_payload:
                return self._push_cached_post_market_payload(strategy_key, cached_payload)

            report = self.daily_report.generate_report(skip_data_update=True)
            if strategy_key == "legacy":
                self._save_push_cache(
                    cache_key,
                    {
                        "trade_date": report.get("report_date"),
                        "legacy_payload": report,
                    },
                )
                return self.pusher.push_daily_report(report)
            legacy_ok = True
            if strategy_key == "both":
                legacy_ok = self.pusher.push_daily_report(report)
            secondary_selection = report.get("secondary_launch_selection", []) or []
            intraday_review = report.get("secondary_launch_intraday_review", []) or []
            triggered_count = sum(1 for item in intraday_review if item.get("has_buy_signal"))
            blockers = [
                str(item.get("not_pushed_reason", "") or "").strip()
                for item in intraday_review
                if not item.get("has_buy_signal")
            ]
            main_blocker = blockers[0] if blockers else "暂无明显阻塞项"
            hold = report.get("hold_analysis", {}) if isinstance(report.get("hold_analysis"), dict) else {}

            content = f"""## 盘后复盘

**日期**: {datetime.now().strftime('%Y-%m-%d')}

### 今日结论
- 今日推荐: `{len(secondary_selection)}` 只
- 今日触发: `{triggered_count}` 只
- 当前持仓: `{int(hold.get('hold_count', 0) or 0)}` 只
- 主要未触发原因: {main_blocker}

### 今天做对了什么
- 系统已自动完成盘前候选、盘中复盘、盘后汇总。
- 买点复盘已直接落到日报与跟踪报表，可用于次日准备。

### 明日建议
- 盘前先看“今日计划”，不要直接把候选当下单指令。
- 盘中仍以实时买卖点信号为准，优先处理真正触发的票。

---
*仅供交易决策参考*"""

            secondary_ok = self.pusher.push_markdown(content)
            self._save_push_cache(
                cache_key,
                {
                    "trade_date": report.get("report_date"),
                    "legacy_payload": report if strategy_key == "both" else None,
                    "secondary_markdown": content,
                },
            )
            return bool(legacy_ok and secondary_ok)
            
        except Exception as e:
            logger.error(f"盘后作业推送失败: {e}")
            return False

    def invalidate_push_cache(self) -> None:
        """清理 Web 推送缓存，避免数据更新后继续发送旧内容。"""
        try:
            if self.push_cache_path.exists():
                self.push_cache_path.unlink()
        except Exception as exc:
            logger.warning("清理推送缓存失败: %s", exc)

    def _push_cached_pre_market_payload(self, strategy: str, payload: Dict[str, Any]) -> bool:
        strategy_key = str(strategy or "").strip().lower()
        success = True
        if strategy_key in {"legacy", "both"} and payload.get("legacy_payload"):
            success = self.pusher.push_pre_market_selection(payload.get("legacy_payload") or {})
        secondary_success = True
        if strategy_key in {"secondary_launch", "secondary", "both"} and payload.get("secondary_payload"):
            secondary_success = self.pusher.push_pre_market_selection(payload.get("secondary_payload") or {})
        return bool(success and secondary_success)

    def _push_cached_post_market_payload(self, strategy: str, payload: Dict[str, Any]) -> bool:
        strategy_key = str(strategy or "").strip().lower()
        if strategy_key == "legacy":
            return self.pusher.push_daily_report(payload.get("legacy_payload") or {})
        legacy_ok = True
        if strategy_key == "both" and payload.get("legacy_payload"):
            legacy_ok = self.pusher.push_daily_report(payload.get("legacy_payload") or {})
        secondary_ok = self.pusher.push_markdown(str(payload.get("secondary_markdown", "") or ""))
        return bool(legacy_ok and secondary_ok)

    def _load_push_cache(self, cache_key: str) -> Optional[Dict[str, Any]]:
        state = self._read_push_cache_state()
        row = state.get(str(cache_key))
        if not isinstance(row, dict):
            return None
        created_at = str(row.get("created_at", "") or "")
        if not created_at:
            return None
        try:
            age_seconds = (datetime.now() - datetime.strptime(created_at, "%Y-%m-%d %H:%M:%S")).total_seconds()
        except Exception:
            return None
        if age_seconds > self.push_cache_ttl_seconds:
            return None
        return row.get("payload") if isinstance(row.get("payload"), dict) else None

    def _save_push_cache(self, cache_key: str, payload: Dict[str, Any]) -> None:
        state = self._read_push_cache_state()
        state[str(cache_key)] = {
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "payload": payload,
        }
        self.push_cache_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

    def _read_push_cache_state(self) -> Dict[str, Any]:
        if not self.push_cache_path.exists():
            return {}
        try:
            return json.loads(self.push_cache_path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("读取推送缓存失败: %s", exc)
            return {}
    
    @staticmethod
    def _best_feedback_stat(
        stats: List[Dict[str, Any]],
        source_type: str,
        direction: Optional[str] = None,
        min_samples_for_best: int = 10,
    ) -> Optional[Dict[str, Any]]:
        candidates: List[Dict[str, Any]] = []
        for stat in stats or []:
            if str(stat.get("source_type", "")) != str(source_type):
                continue
            if direction is not None and str(stat.get("direction", "")) != str(direction):
                continue
            candidates.append(stat)

        if not candidates:
            return None

        eligible = [
            s
            for s in candidates
            if int(s.get("sample_count", 0) or 0) >= int(min_samples_for_best)
        ]
        pool = eligible if eligible else candidates
        pool = sorted(
            pool,
            key=lambda x: (
                float(x.get("mean_net_return", -999) or -999),
                int(x.get("sample_count", 0) or 0),
            ),
            reverse=True,
        )
        if not pool:
            return None

        best = pool[0]
        return {
            "horizon": int(best.get("horizon", 0) or 0),
            "sample_count": int(best.get("sample_count", 0) or 0),
            "win_rate": float(best.get("win_rate", 0.0) or 0.0),
            "mean_net_return": float(best.get("mean_net_return", 0.0) or 0.0),
            "mean_mfe": float(best.get("mean_mfe", 0.0) or 0.0),
            "mean_mae": float(best.get("mean_mae", 0.0) or 0.0),
        }

    def _build_feedback_digest_payload(
        self,
        run_result: Dict[str, Any],
        min_samples_for_best: int = 10,
    ) -> Dict[str, Any]:
        stats = run_result.get("stats", [])
        if not isinstance(stats, list):
            stats = []
        files = run_result.get("files", {})
        if not isinstance(files, dict):
            files = {}

        return {
            "run_id": str(run_result.get("run_id", "")),
            "generated_time": str(
                run_result.get("generated_time", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            ),
            "start_date": str(run_result.get("start_date", "")),
            "end_date": str(run_result.get("end_date", "")),
            "detail_count": int(run_result.get("detail_count", 0) or 0),
            "recommendation_detail_count": int(
                run_result.get("recommendation_detail_count", 0) or 0
            ),
            "signal_detail_count": int(run_result.get("signal_detail_count", 0) or 0),
            "pre_market_best": self._best_feedback_stat(
                stats=stats,
                source_type=SignalFeedbackEvaluator.SOURCE_PRE_MARKET,
                direction=None,
                min_samples_for_best=min_samples_for_best,
            ),
            "intraday_buy_best": self._best_feedback_stat(
                stats=stats,
                source_type=SignalFeedbackEvaluator.SOURCE_INTRADAY,
                direction="buy",
                min_samples_for_best=min_samples_for_best,
            ),
            "intraday_sell_best": self._best_feedback_stat(
                stats=stats,
                source_type=SignalFeedbackEvaluator.SOURCE_INTRADAY,
                direction="sell",
                min_samples_for_best=min_samples_for_best,
            ),
            "files": files,
        }

    def push_signal_feedback_digest(self) -> bool:
        """
        鎺ㄩ€佺洏鍚庝俊鍙烽棴鐜弽棣堟憳瑕侊紙鐙珛妯℃澘锛夈€?        
        """
        if not bool(self.config.get("feedback.digest_push_enabled", True)):
            logger.info("淇″彿闂幆鎽樿鎺ㄩ€佸凡绂佺敤")
            return False

        try:
            logger.info("鎵ц鐩樺悗淇″彿闂幆璇勪及骞舵帹閫佹憳瑕?..")

            end_date = self.db.get_latest_trade_date("stock_daily")
            if not end_date:
                end_date = datetime.now().strftime("%Y%m%d")
            end_date = str(end_date)

            lookback_days = int(self.config.get("feedback.default_lookback_days", 90))
            top_n = int(self.config.get("feedback.top_n_per_day", 10))
            rec_h = self.config.get("feedback.recommendation_horizons", [2, 3, 4, 5])
            sig_h = self.config.get("feedback.signal_horizons", [1, 2, 3])
            min_samples_for_best = int(
                self.config.get(
                    "feedback.digest_min_samples_for_best",
                    self.config.get("feedback.snapshot_min_samples_for_best", 10),
                )
            )

            start_date: Optional[str] = None
            try:
                end_dt = datetime.strptime(end_date, "%Y%m%d")
                start_date = (end_dt - timedelta(days=lookback_days)).strftime("%Y%m%d")
            except Exception:
                start_date = None

            run_result = self.signal_feedback.run_feedback(
                start_date=start_date,
                end_date=end_date,
                top_n_per_day=top_n,
                recommendation_horizons=rec_h,
                signal_horizons=sig_h,
                persist=True,
            )
            if str(run_result.get("status", "")).lower() != "success":
                logger.error("淇″彿闂幆璇勪及鏈垚鍔? status=%s", run_result.get("status"))
                return False

            digest_payload = self._build_feedback_digest_payload(
                run_result=run_result,
                min_samples_for_best=min_samples_for_best,
            )
            return self.pusher.push_feedback_digest(digest_payload)

        except Exception as e:
            logger.error(f"淇″彿闂幆鎽樿鎺ㄩ€佸け璐? {e}")
            return False

    def push_realtime_alert(self, alert_data: Dict) -> bool:
        """
        推送实时监控预警
        
        Args:
            alert_data: 预警数据
        
        Returns:
            是否成功
        """
        try:
            content = f"""## 实时监控预警

**时间**: {datetime.now().strftime('%H:%M:%S')}

**股票**: {alert_data.get('ts_code', '')} {alert_data.get('name', '')}

### 预警信息

{alert_data.get('message', '')}

> 请及时关注"""
            
            return self.pusher.push_markdown(content)
            
        except Exception as e:
            logger.error(f"实时预警推送失败: {e}")
            return False

    @staticmethod
    def _normalize_ts_code(ts_code: str) -> str:
        return str(ts_code or "").strip().upper()

    def _make_position_event_id(
        self,
        signal: Dict[str, Any],
        hold: Dict[str, Any],
        now: datetime,
    ) -> str:
        cooldown_minutes = max(1, int(self.position_event_cooldown_minutes))
        bucket = int(now.timestamp() // (cooldown_minutes * 60))
        source = "|".join(
            [
                self._normalize_ts_code(signal.get("ts_code", "")),
                str(signal.get("signal_type", "")),
                str(signal.get("reason", "")),
                str(hold.get("hold_price", "")),
                str(hold.get("hold_num", "")),
                str(bucket),
            ]
        )
        return hashlib.sha1(source.encode("utf-8")).hexdigest()[:24]

    @staticmethod
    def _infer_position_action(signal: Dict[str, Any]) -> str:
        signal_type = str(signal.get("signal_type", "")).lower()
        suggestion = str(signal.get("suggestion", ""))
        reason = str(signal.get("reason", ""))
        merged = f"{signal_type} {suggestion} {reason}"

        if any(word in merged for word in ["清仓", "全部卖出", "立即卖出"]):
            return "SELL_ALL"
        if any(word in merged for word in ["止损", "止盈", "卖出"]):
            return "REDUCE"
        return "REVIEW"

    def _build_position_event(
        self,
        signal: Dict[str, Any],
        hold_map: Dict[str, Dict[str, Any]],
        market_result: Dict[str, Any],
    ) -> Dict[str, Any]:
        now = datetime.now()
        ts_code = self._normalize_ts_code(signal.get("ts_code", ""))
        hold = hold_map.get(ts_code, {})
        hold_num = int(hold.get("hold_num", 0) or 0)
        hold_price = float(hold.get("hold_price", 0) or 0.0)
        event_id = self._make_position_event_id(signal=signal, hold=hold, now=now)
        hold_date = str(hold.get("hold_date", "") or "")
        hold_days = 0
        if hold_date:
            try:
                hold_days = max(0, (now.date() - datetime.strptime(hold_date, "%Y-%m-%d").date()).days)
            except Exception:
                hold_days = 0

        return {
            "event_id": event_id,
            "event_type": "position_risk_signal",
            "trigger_time": str(signal.get("trigger_time", now.strftime("%Y-%m-%d %H:%M:%S"))),
            "ts_code": ts_code,
            "name": str(signal.get("name", hold.get("name", ""))),
            "signal_type": str(signal.get("signal_type", "")),
            "severity": str(signal.get("severity", "medium")),
            "reason": str(signal.get("reason", "")),
            "suggestion": str(signal.get("suggestion", "")),
            "action": self._infer_position_action(signal),
            "current_price": float(signal.get("current_price", 0) or 0.0),
            "profit": float(signal.get("profit", 0) or 0.0),
            "hold_price": hold_price,
            "hold_num": hold_num,
            "hold_days": hold_days,
            "market_regime": str(market_result.get("market_regime", "UNKNOWN")),
            "market_risk_state": str(market_result.get("risk_state", "MEDIUM")),
            "is_real_position": hold_num > 0,
            "reconcile_status": "CONFIRMED" if hold_num > 0 else "NOT_IN_HOLD",
        }
    
    def _get_score_emoji(self, score: float) -> str:
        """根据评分获取表情符号"""
        if score >= 70:
            return "🟢"
        elif score >= 50:
            return "🟡"
        else:
            return "🔴"

    def _get_regime_emoji(self, regime: str) -> str:
        """根据市场状态获取表情符号"""
        if regime == 'BULL':
            return "🟢"
        elif regime == 'NEUTRAL':
            return "🟡"
        else:  # BEAR
            return "🔴"
    
    def _convert_report_to_markdown(self, report: str) -> str:
        """将日报转换为Markdown格式"""
        lines = report.split('\n')
        markdown_lines = []
        
        for line in lines:
            # 转换分隔线
            if line.startswith('='):
                continue
            # 转换标题
            if '日报' in line and len(line) < 20:
                markdown_lines.append(f"## {line.strip()}")
            else:
                markdown_lines.append(line)
        
        return '\n'.join(markdown_lines)
    
    def _convert_plan_to_markdown(self, plan: str) -> str:
        """将交易计划转换为Markdown格式"""
        lines = plan.split('\n')
        markdown_lines = []
        
        for line in lines:
            if line.startswith('='):
                continue
            if '交易计划' in line and len(line) < 20:
                markdown_lines.append(f"## {line.strip()}")
            else:
                markdown_lines.append(line)
        
        return '\n'.join(markdown_lines)
