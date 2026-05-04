# -*- coding: utf-8 -*-
"""
AI管家服务 - 集成到量化系统运行流程
定时任务、事件触发、主动监控
"""

import json
import os
import yaml
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from src.core.logger import get_logger
from src.core.config import ConfigManager
from src.modules.ai_integration.llm_client import LLMClient
from src.modules.ai_integration.ai_butler import AIButler

logger = get_logger("ai_butler_service")

# 项目根目录
_PROJECT_ROOT = Path(__file__).resolve().parents[2]


class AIButlerService:
    """
    AI管家服务 - 系统级集成

    功能:
    1. 定时任务: 盘前简报、盘中监控、盘后复盘
    2. 事件触发: 信号触发时实时分析
    3. 主动监控: 持仓监控、风险预警
    4. 消息推送: 将管家建议推送到企业微信/钉钉
    """

    _instance = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(
        self,
        config: Optional[ConfigManager] = None,
        push_callback: Optional[callable] = None,
    ):
        if hasattr(self, "_initialized"):
            return

        self._config = config or ConfigManager()
        self._push_callback = push_callback  # 消息推送回调

        # 初始化LLM和管家
        ai_config = self._load_ai_config()
        self.llm = LLMClient(config=self._build_llm_config(ai_config))
        self.butler = AIButler(self.llm)
        ai_root = ai_config.get("ai", {}) if isinstance(ai_config, dict) else {}
        butler_cfg = ai_root.get("butler", {}) if isinstance(ai_root, dict) else {}
        self._strong_reminder_levels = {
            str(level).upper()
            for level in (butler_cfg.get("strong_reminder_levels", ["HIGH", "CRITICAL"]) or [])
            if str(level).strip()
        }
        if not self._strong_reminder_levels:
            self._strong_reminder_levels = {"HIGH", "CRITICAL"}

        # 调度器
        self._scheduler = BackgroundScheduler(daemon=True)
        self._running = False

        # 状态
        self._last_briefing: Optional[Dict] = None
        self._last_review: Optional[Dict] = None
        self._active_alerts: List[Dict] = []

        # 数据服务(懒加载)
        self._dashboard_service = None

        self._initialized = True
        logger.info(f"AI管家服务初始化完成, LLM可用={self.llm.is_available}")

    # ==================== 数据服务懒加载 ====================

    def _normalize_alert_level(self, level: Optional[str]) -> str:
        raw = str(level or "").strip().upper()
        return raw if raw else "INFO"

    def _format_alert_title(self, alert_type: str, level: str) -> str:
        level_prefix = {
            "CRITICAL": "【紧急】",
            "HIGH": "【高危】",
            "MEDIUM": "【提示】",
            "LOW": "【关注】",
            "INFO": "【信息】",
        }
        return f"{level_prefix.get(level, '【信息】')}{alert_type}"

    def _publish_alert(
        self,
        *,
        alert_type: str,
        message: str,
        level: Optional[str] = None,
        source: str = "butler",
        extra: Optional[Dict[str, Any]] = None,
    ) -> None:
        normalized = self._normalize_alert_level(level)
        alert_record = {
            "type": alert_type,
            "message": message,
            "level": normalized,
            "source": source,
            "created_at": datetime.now().isoformat(),
        }
        if extra:
            alert_record.update(extra)

        self._active_alerts.append(alert_record)
        if len(self._active_alerts) > 200:
            self._active_alerts = self._active_alerts[-200:]

        if self._push_callback and normalized in self._strong_reminder_levels:
            self._push_callback(self._format_alert_title(alert_type, normalized), message)

    def _get_dashboard_service(self):
        """懒加载DashboardDataService, 避免循环依赖"""
        if self._dashboard_service is None:
            try:
                from src.services.dashboard_service import DashboardDataService
                self._dashboard_service = DashboardDataService(project_root=_PROJECT_ROOT)
                logger.debug("DashboardDataService已加载")
            except Exception as e:
                logger.warning(f"DashboardDataService加载失败: {e}")
        return self._dashboard_service

    def _get_system_snapshot(self) -> Dict[str, Any]:
        """获取系统快照(聚合所有模块数据)"""
        service = self._get_dashboard_service()
        if service is None:
            return {}
        try:
            return service.build_snapshot()
        except Exception as e:
            logger.warning(f"系统快照获取失败: {e}")
            return {}

    def _load_ai_config(self) -> Dict:
        """加载AI配置"""
        config_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            "config",
            "ai_config.yaml",
        )
        if os.path.exists(config_path):
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    return yaml.safe_load(f) or {}
            except Exception as e:
                logger.warning(f"AI配置加载失败: {e}")
        return {}

    def _build_llm_config(self, config_data: Dict[str, Any]) -> Dict[str, Any]:
        """Build butler LLM config from ai_config.yaml."""
        ai_root = config_data.get("ai", {}) if isinstance(config_data, dict) else {}
        provider = str(ai_root.get("provider", "deepseek")).strip() or "deepseek"
        models_config = ai_root.get("models", {}) or {}
        generation_config = ai_root.get("generation", {}) or {}

        if provider == "deepseek":
            provider_config = ai_root.get("deepseek", {}) or {}
            default_base_url = "https://api.deepseek.com/v1"
            default_model = "deepseek-chat"
            code_model = "deepseek-coder"
        elif provider == "local_deepseek":
            provider_config = ai_root.get("local_deepseek", {}) or {}
            default_base_url = "http://localhost:8000/v1"
            default_model = "deepseek-r1"
            code_model = "deepseek-r1"
        else:
            provider_config = ai_root.get("ollama", {}) or {}
            default_base_url = "http://localhost:11434"
            default_model = "qwen2.5:7b"
            code_model = "mistral:7b"

        api_key_env = str(provider_config.get("api_key_env", "")).strip()
        api_key = os.environ.get(api_key_env, "") if api_key_env else ""
        if not api_key:
            api_key = str(provider_config.get("api_key", "") or "")

        llm_config: Dict[str, Any] = {
            "provider": provider,
            "base_url": provider_config.get("base_url", default_base_url),
            "api_key": api_key,
            "default_model": models_config.get("default", default_model),
            "code_model": models_config.get("code", code_model),
            "timeout": provider_config.get("timeout", 120),
            "max_retries": provider_config.get("max_retries", 2),
            "retry_delay": provider_config.get("retry_delay", 3),
            "temperature": generation_config.get("temperature", 0.4),
            "max_tokens": generation_config.get("max_tokens", 2048),
        }

        protection_cfg = ai_root.get("protection", {}) or {}
        llm_config["max_concurrency"] = int(protection_cfg.get("max_concurrency", 2))
        llm_config["circuit_breaker"] = protection_cfg.get("circuit_breaker", {}) or {}
        return llm_config

    @property
    def is_available(self) -> bool:
        """管家是否可用"""
        return self.llm.is_available

    @property
    def is_running(self) -> bool:
        """服务是否运行中"""
        return self._running

    # ==================== 启动/停止 ====================

    def start(self):
        """启动管家服务"""
        if self._running:
            logger.warning("AI管家服务已在运行")
            return

        if not self.llm.is_available:
            logger.warning("LLM不可用，管家服务将以降级模式运行")

        # 添加定时任务
        self._setup_scheduled_tasks()

        # 启动调度器
        self._scheduler.start()
        self._running = True
        logger.info("AI管家服务已启动")

    def stop(self):
        """停止管家服务"""
        if not self._running:
            return
        self._scheduler.shutdown(wait=False)
        self._running = False
        logger.info("AI管家服务已停止")

    def _setup_scheduled_tasks(self):
        """设置定时任务"""
        # 盘前简报: 每个交易日 8:15
        self._scheduler.add_job(
            self._morning_briefing_task,
            CronTrigger(hour=8, minute=15, day_of_week="mon-fri"),
            id="butler_morning_briefing",
            replace_existing=True,
        )

        # 盘中监控: 交易时段每30分钟
        self._scheduler.add_job(
            self._intraday_monitor_task,
            CronTrigger(hour="9-11,13-14", minute="*/30", day_of_week="mon-fri"),
            id="butler_intraday_monitor",
            replace_existing=True,
        )

        # 盘后复盘: 每个交易日 15:30
        self._scheduler.add_job(
            self._post_market_review_task,
            CronTrigger(hour=15, minute=30, day_of_week="mon-fri"),
            id="butler_post_market_review",
            replace_existing=True,
        )

        # 风险检查: 每15分钟
        self._scheduler.add_job(
            self._risk_check_task,
            CronTrigger(minute="*/15"),
            id="butler_risk_check",
            replace_existing=True,
        )

        logger.info("定时任务已设置: 盘前简报(8:15), 盘中监控(每30分钟), 盘后复盘(15:30), 风险检查(每15分钟)")

    # ==================== 定时任务 ====================

    def _morning_briefing_task(self):
        """盘前简报任务"""
        logger.info("执行盘前简报任务...")
        try:
            yesterday_review = self._get_yesterday_review()
            today_selection = self._get_today_selection()
            overnight_news = self._get_overnight_news()
            data_status = self._get_data_status()

            briefing = self.butler.morning_briefing(
                yesterday_review=yesterday_review,
                today_selection=today_selection,
                overnight_news=overnight_news,
                data_status=data_status,
            )

            self._last_briefing = briefing

            if self._push_callback:
                self._push_callback("盘前简报", briefing["briefing"])

            logger.info("盘前简报生成完成")

        except Exception as e:
            logger.error(f"盘前简报任务失败: {e}")

    def _intraday_monitor_task(self):
        """盘中监控任务"""
        logger.debug("执行盘中监控任务...")
        try:
            holdings = self._get_current_holdings()
            signals = self._get_recent_signals()
            market_status = self._get_market_status()

            monitor_result = self.butler.intraday_monitor(
                holdings=holdings,
                signals=signals,
                market_status=market_status,
            )

            alerts = monitor_result.get("alerts", [])
            for alert in alerts:
                self._publish_alert(
                    alert_type=str(alert.get("type", "盘中监控告警")),
                    message=str(alert.get("message", "")),
                    level=str(alert.get("level", "INFO")),
                    source="intraday_monitor",
                    extra={"raw": alert},
                )

            logger.debug(f"盘中监控完成, 预警数: {len(alerts)}")

        except Exception as e:
            logger.error(f"盘中监控任务失败: {e}")

    def _post_market_review_task(self):
        """盘后复盘任务"""
        logger.info("执行盘后复盘任务...")
        try:
            today_trades = self._get_today_trades()
            today_signals = self._get_today_signals()
            holdings = self._get_current_holdings()
            market_summary = self._get_market_summary()

            review = self.butler.post_market_review(
                today_trades=today_trades,
                today_signals=today_signals,
                holdings=holdings,
                market_summary=market_summary,
            )

            self._last_review = review

            if self._push_callback:
                self._push_callback("盘后复盘", review["review_report"])

            logger.info("盘后复盘完成")

        except Exception as e:
            logger.error(f"盘后复盘任务失败: {e}")

    def _risk_check_task(self):
        """风险检查任务"""
        logger.debug("执行风险检查任务...")
        try:
            holdings = self._get_current_holdings()
            market_data = self._get_market_status()

            risk_result = self.butler.risk_check(holdings=holdings, market_data=market_data)

            if risk_result["risk_level"] in ["HIGH", "CRITICAL"]:
                for alert in risk_result["alerts"]:
                    self._publish_alert(
                        alert_type="风险预警",
                        message=str(alert.get("message", "")),
                        level=str(alert.get("level", risk_result.get("risk_level", "HIGH"))),
                        source="risk_check",
                        extra={"raw": alert},
                    )

            logger.debug(f"风险检查完成, 风险等级: {risk_result['risk_level']}")

        except Exception as e:
            logger.error(f"风险检查任务失败: {e}")

    # ==================== 事件触发 ====================

    def on_signal_triggered(self, signal: Dict, stock_info: Dict, position: Optional[Dict] = None) -> Dict:
        """信号触发事件 - 实时分析"""
        logger.info(f"信号触发: {stock_info.get('name', '')} {signal.get('type', '')}")

        result = self.butler.analyze_signal_realtime(
            signal=signal,
            stock_info=stock_info,
            position=position,
        )

        if result.get("confidence", 0) >= 0.7 and result.get("action") in ["BUY", "SELL"]:
            action_text = "买入" if result["action"] == "BUY" else "卖出"
            confidence = float(result.get("confidence", 0) or 0)
            level = "HIGH" if confidence >= 0.85 else "MEDIUM"
            self._publish_alert(
                alert_type=f"{action_text}建议",
                message=(
                    f"{stock_info.get('name', '')} {action_text}\n"
                    f"原因: {result.get('reason', '')}\n"
                    f"执行: {result.get('execution_advice', '')}"
                ),
                level=level,
                source="signal_analysis",
                extra={"signal": signal, "stock_info": stock_info, "confidence": confidence},
            )

        return result

    def on_position_changed(self, position: Dict):
        """持仓变化事件"""
        logger.info(f"持仓变化: {position.get('name', '')}")

    def on_market_event(self, event: Dict):
        """市场事件（如大盘异动）"""
        logger.info(f"市场事件: {event.get('type', '')}")

    # ==================== 手动调用 ====================

    def generate_briefing_now(self, **kwargs) -> Dict:
        """立即生成盘前简报"""
        return self.butler.morning_briefing(**kwargs)

    def do_intraday_monitor_now(self, **kwargs) -> Dict:
        """立即执行盘中监控"""
        return self.butler.intraday_monitor(**kwargs)

    def generate_review_now(self, **kwargs) -> Dict:
        """立即生成盘后复盘"""
        return self.butler.post_market_review(**kwargs)

    def do_risk_check_now(self, **kwargs) -> Dict:
        """立即执行风险检查"""
        return self.butler.risk_check(**kwargs)

    # ==================== 数据获取（对接系统模块） ====================

    def _get_yesterday_review(self) -> Optional[Dict]:
        """获取昨日复盘数据 - 从闭环反馈模块获取"""
        try:
            snapshot = self._get_system_snapshot()
            feedback = snapshot.get("feedback", {})
            if not feedback:
                return None

            best_summary = feedback.get("best_summary", {})
            best_intraday = feedback.get("best_intraday_subtype", {})

            return {
                "pre_market": {
                    "win_rate": best_summary.get("win_rate_pct"),
                    "mean_net_return": best_summary.get("mean_net_return_pct"),
                    "sample_count": best_summary.get("sample_count"),
                },
                "intraday": {
                    "best_subtype": best_intraday.get("subtype"),
                    "win_rate": best_intraday.get("win_rate_pct"),
                    "mean_net_return": best_intraday.get("mean_net_return_pct"),
                },
                "insights": feedback.get("intraday_insights", {}).get("conclusions", []),
                "action_items": feedback.get("intraday_insights", {}).get("action_items", []),
            }
        except Exception as e:
            logger.warning(f"获取昨日复盘数据失败: {e}")
            return None

    def _get_today_selection(self) -> Optional[List[Dict]]:
        """获取今日选股结果 - 从候选池获取"""
        try:
            snapshot = self._get_system_snapshot()
            pool = snapshot.get("candidate_pool", {})
            candidates = pool.get("top_candidates", [])
            if not candidates:
                # 尝试直接读取候选池缓存文件
                cache_path = _PROJECT_ROOT / "data" / "cache" / "candidate_pool.json"
                if cache_path.exists():
                    data = json.loads(cache_path.read_text(encoding="utf-8"))
                    candidates = data.get("candidates", [])[:10]

            # 转换为管家需要的格式
            result = []
            for c in candidates[:10]:
                result.append({
                    "code": c.get("ts_code", c.get("symbol", "")),
                    "name": c.get("name", ""),
                    "score": c.get("score", c.get("total_score", 0)),
                    "industry": c.get("industry", ""),
                    "level": c.get("level", ""),
                    "strategy_profile": c.get("strategy_profile", ""),
                    "trigger_reason": c.get("trigger_reason", ""),
                })
            return result if result else None
        except Exception as e:
            logger.warning(f"获取今日选股结果失败: {e}")
            return None

    def _get_overnight_news(self) -> Optional[List[Dict]]:
        """获取隔夜新闻 - 暂无外部新闻源,返回None"""
        # 系统当前没有新闻采集模块,后续可对接东方财富/同花顺新闻API
        return None

    def _get_data_status(self) -> Optional[Dict]:
        """获取数据状态 - 从系统健康和启动同步状态获取"""
        try:
            snapshot = self._get_system_snapshot()
            health = snapshot.get("health", {})
            sync = snapshot.get("startup_market_sync", {})

            return {
                "health_status": health.get("status", "unknown"),
                "health_label": health.get("status_label", ""),
                "incident_count": health.get("incident_count", 0),
                "sync_status": sync.get("status", ""),
                "sync_label": sync.get("status_label", ""),
                "latest_trade_date": sync.get("latest_trade_date_after", ""),
                "missing_dates_count": sync.get("missing_trade_dates_count", 0),
            }
        except Exception as e:
            logger.warning(f"获取数据状态失败: {e}")
            return None

    def _get_current_holdings(self) -> Optional[List[Dict]]:
        """获取当前持仓 - 虚拟持仓 + 真实持仓"""
        holdings = []

        try:
            # 1. 虚拟持仓(从系统快照获取)
            snapshot = self._get_system_snapshot()
            vt = snapshot.get("virtual_trades", {})
            open_trades = vt.get("open_trades", [])
            for t in open_trades:
                holdings.append({
                    "code": t.get("symbol", t.get("ts_code", "")),
                    "name": t.get("name", ""),
                    "position": 0,  # 虚拟持仓无仓位比例,标记为虚拟
                    "buy_price": t.get("buy_price", 0),
                    "pnl_pct": t.get("last_pnl_pct", t.get("profit_pct", 0)),
                    "buy_time": t.get("buy_time", ""),
                    "buy_signal": t.get("buy_signal", ""),
                    "buy_score": t.get("buy_score", 0),
                    "type": "virtual",
                })

            # 2. 真实持仓(从系统快照获取)
            real_holdings = snapshot.get("holdings", {})
            for h in real_holdings.get("items", []):
                holdings.append({
                    "code": h.get("ts_code", ""),
                    "name": h.get("name", ""),
                    "position": h.get("hold_num", 0),
                    "buy_price": h.get("hold_price", 0),
                    "pnl_pct": h.get("unrealized_pct", 0),
                    "market_value": h.get("market_value", 0),
                    "type": "real",
                })
        except Exception as e:
            logger.warning(f"获取持仓数据失败: {e}")

        # 3. 如果快照获取失败,尝试直接读取虚拟交易缓存
        if not holdings:
            try:
                cache_path = _PROJECT_ROOT / "data" / "cache" / "virtual_trades.json"
                if cache_path.exists():
                    data = json.loads(cache_path.read_text(encoding="utf-8"))
                    for t in data.get("open_trades", []):
                        holdings.append({
                            "code": t.get("symbol", ""),
                            "name": t.get("name", ""),
                            "buy_price": t.get("buy_price", 0),
                            "pnl_pct": t.get("last_pnl_pct", 0),
                            "type": "virtual",
                        })
            except Exception as e:
                logger.warning(f"读取虚拟交易缓存失败: {e}")

        return holdings if holdings else None

    def _get_recent_signals(self) -> Optional[List[Dict]]:
        """获取最近信号 - 从信号DAO获取"""
        try:
            # 优先从DAO获取
            from src.dao.signal_dao import SignalDAO
            dao = SignalDAO()
            signals = dao.get_recent_signals(limit=10)
            if signals:
                return [
                    {
                        "code": s.get("ts_code", ""),
                        "name": s.get("name", ""),
                        "type": s.get("signal_type", ""),
                        "category": s.get("signal_category", ""),
                        "time": s.get("trigger_time", ""),
                        "reason": s.get("reason", ""),
                        "suggestion": s.get("suggestion", ""),
                        "priority": s.get("priority_level", ""),
                        "status": s.get("status", ""),
                    }
                    for s in signals
                ]
        except Exception as e:
            logger.debug(f"SignalDAO获取失败, 尝试快照: {e}")

        # 降级: 从系统快照获取
        try:
            snapshot = self._get_system_snapshot()
            signals_data = snapshot.get("signals", {})
            items = signals_data.get("latest_items", [])
            if items:
                return [
                    {
                        "code": s.get("ts_code", ""),
                        "name": s.get("name", ""),
                        "type": s.get("signal_type", ""),
                        "time": s.get("trigger_time", ""),
                    }
                    for s in items
                ]
        except Exception as e:
            logger.warning(f"获取信号数据失败: {e}")

        return None

    def _get_market_status(self) -> Optional[Dict]:
        """获取市场状态 - 从市场体制引擎和评分获取"""
        result = {}

        try:
            # 1. 市场体制(从DAO获取)
            from src.dao.market_regime_dao import MarketRegimeDAO
            regime_dao = MarketRegimeDAO()
            latest_regime = regime_dao.get_latest_regime()
            if latest_regime:
                result["regime"] = latest_regime.get("regime", "")
                result["trend_state"] = latest_regime.get("trend_state", "")
                result["money_state"] = latest_regime.get("money_state", "")
                result["target_position"] = latest_regime.get("max_position", 0)
                result["regime_time"] = latest_regime.get("trigger_time", "")
        except Exception as e:
            logger.debug(f"MarketRegimeDAO获取失败: {e}")

        try:
            # 2. 市场评分(从系统快照获取)
            snapshot = self._get_system_snapshot()
            today_board = snapshot.get("today_board", {})
            if today_board:
                result["board_status"] = today_board.get("status", "")
                result["board_action"] = today_board.get("action", "")
                result["board_reason"] = today_board.get("reason", "")

            # 3. 市场时段
            market_session = snapshot.get("meta", {}).get("market_session", {})
            if market_session:
                result["phase"] = market_session.get("phase", "")
        except Exception as e:
            logger.debug(f"市场评分获取失败: {e}")

        return result if result else None

    def _get_today_trades(self) -> Optional[List[Dict]]:
        """获取今日交易 - 从虚拟交易最近平仓获取"""
        try:
            snapshot = self._get_system_snapshot()
            vt = snapshot.get("virtual_trades", {})
            recent_closed = vt.get("recent_closed", [])
            today = datetime.now().strftime("%Y-%m-%d")

            # 筛选今日平仓
            today_trades = []
            for t in recent_closed:
                sell_time = str(t.get("sell_time", ""))
                if today in sell_time:
                    today_trades.append({
                        "code": t.get("symbol", ""),
                        "name": t.get("name", ""),
                        "action": "卖出",
                        "buy_price": t.get("buy_price", 0),
                        "sell_price": t.get("sell_price", 0),
                        "pnl_pct": t.get("pnl_pct", 0),
                        "sell_reason": t.get("sell_reason", ""),
                        "hold_duration": t.get("hold_duration", 0),
                    })
            return today_trades if today_trades else None
        except Exception as e:
            logger.warning(f"获取今日交易失败: {e}")
            return None

    def _get_today_signals(self) -> Optional[List[Dict]]:
        """获取今日信号 - 从信号DAO获取今日信号"""
        try:
            from src.dao.signal_dao import SignalDAO
            dao = SignalDAO()
            today = datetime.now().strftime("%Y%m%d")
            signals = dao.get_signals_by_filters({"start_date": today, "limit": 20})
            if signals:
                return [
                    {
                        "code": s.get("ts_code", ""),
                        "name": s.get("name", ""),
                        "type": s.get("signal_type", ""),
                        "time": s.get("trigger_time", ""),
                        "status": s.get("status", ""),
                    }
                    for s in signals
                ]
        except Exception as e:
            logger.warning(f"获取今日信号失败: {e}")
        return None

    def _get_market_summary(self) -> Optional[Dict]:
        """获取市场总结 - 综合市场体制和评分"""
        return self._get_market_status()

    # ==================== 状态查询 ====================

    def get_status(self) -> Dict:
        """获取管家状态"""
        return {
            "running": self._running,
            "llm_available": self.llm.is_available,
            "llm_provider": self.llm.provider,
            "strong_reminder_levels": sorted(self._strong_reminder_levels),
            "last_briefing_time": self._last_briefing.get("created_at") if self._last_briefing else None,
            "last_review_time": self._last_review.get("created_at") if self._last_review else None,
            "active_alerts_count": len(self._active_alerts),
            "active_alerts": self._active_alerts[-10:],
        }

    def get_last_briefing(self) -> Optional[Dict]:
        """获取最近的盘前简报"""
        return self._last_briefing

    def get_last_review(self) -> Optional[Dict]:
        """获取最近的盘后复盘"""
        return self._last_review
