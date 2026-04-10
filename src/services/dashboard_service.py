from __future__ import annotations

import json
import sqlite3
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from src.core.config import ConfigManager
from src.core.database import DatabaseManager
from src.core.logger import get_logger
from src.services.dashboard_action_record_service import DashboardActionRecordService
from src.services.monitor_session_service import MonitorSessionService
from src.services.terminal_runtime_service import TerminalRuntimeService
from src.modules.secondary_launch_intraday import blocker_tag_to_label

logger = get_logger("dashboard_service")


class DashboardDataService:
    """Aggregate live dashboard data from SQLite stores and cache files."""

    SOURCE_LABELS = {
        "recommendation": "盘前推荐",
        "pre_market_selection": "盘前计划",
        "intraday_signal": "盘中信号",
    }

    DIRECTION_LABELS = {
        "buy": "买点",
        "sell": "卖点",
        "hold": "持有",
    }

    STATUS_COLORS = {
        "healthy": "green",
        "degraded": "amber",
        "stale": "red",
        "unknown": "slate",
    }

    def __init__(
        self,
        project_root: Optional[str | Path] = None,
        quant_db_path: Optional[str | Path] = None,
        history_db_path: Optional[str | Path] = None,
        candidate_cache_path: Optional[str | Path] = None,
        virtual_trades_path: Optional[str | Path] = None,
        terminals_directory: Optional[str | Path] = None,
        config: Optional[ConfigManager] = None,
        now_provider: Optional[Callable[[], datetime]] = None,
    ):
        self.project_root = Path(project_root or Path(__file__).resolve().parents[2])
        self.config = config or ConfigManager()
        self.now_provider = now_provider or datetime.now

        self.quant_db_path = self._resolve_path(
            quant_db_path or self.config.get("database.path", "data/database/quant_system.db")
        )
        # 实盘级要求：禁止通过“改内部字段”方式切换数据库，避免串库污染。
        # 必须显式按 db_path 创建独立实例。
        self.record_db = DatabaseManager(self.config, db_path=str(self.quant_db_path))
        self.history_db_path = self._resolve_path(
            history_db_path
            or self.config.get("feedback.history_recommendation_db", "data/history_recommendation.db")
        )
        self.candidate_cache_path = self._resolve_path(
            candidate_cache_path or "data/cache/candidate_pool.json"
        )
        self.virtual_trades_path = self._resolve_path(
            virtual_trades_path or "data/cache/virtual_trades.json"
        )
        self.background_tasks_state_path = self._resolve_path("data/cache/web_background_tasks.json")
        self.results_dir = self.project_root / "results"
        self.monitor_session_service = MonitorSessionService(
            config=self.config,
            project_root=self.project_root,
        )
        self.action_record_service = DashboardActionRecordService(
            config=self.config,
            db=self.record_db,
        )
        self.terminal_runtime_service = TerminalRuntimeService(
            terminals_directory=terminals_directory,
        )
        # 行情短缓存：实时源抖动或 502 时用于兜底，避免前端频繁看到异常跳变。
        self._realtime_quote_cache: Dict[str, Dict[str, Any]] = {}
        self._realtime_quote_cache_at: Dict[str, float] = {}

    def build_snapshot(self) -> Dict[str, Any]:
        """Build a single payload for the dashboard front end."""
        now = self.now_provider()

        candidate_pool = self._build_candidate_pool_section()
        virtual_trades = self._build_virtual_trade_section()
        holdings = self._build_holdings_section()
        recommendations = self._build_recommendation_section()
        feedback = self._build_feedback_section()
        signals = self._build_signal_section()
        secondary_launch_tracking = self._build_secondary_launch_tracking_section()
        health = self._build_health_section(now)
        startup_market_sync = self._build_startup_market_sync_section()
        health["startup_market_sync"] = startup_market_sync
        terminal_runtime = self._build_terminal_runtime_section(now)
        monitor_session = self._build_monitor_session_section(health=health, now=now)
        action_center = self._build_action_center_section()

        return {
            "meta": {
                "generated_at": now.isoformat(),
                "generated_label": now.strftime("%Y-%m-%d %H:%M:%S"),
                "app_name": self.config.get("system.name", "量化交易辅助系统"),
                "version": self.config.get("system.version", "1.0.0"),
                "strategy_profile": self.config.get("stock_selection.strategy_profile", "legacy"),
                "enhanced_weight_profile": self.config.get(
                    "stock_selection.enhanced_weight_profile", "active"
                ),
                "minute_provider": self.config.get("data_source.realtime_minute_provider", "akshare"),
                "monitor_interval_minutes": self.config.get("monitor.interval_minutes", 5),
                "dashboard_mode": "web_v2",
                "auto_refresh_seconds": 30,
                "market_session": self._build_market_session(now),
                "feature_flags": {
                    "runtime_optimization": bool(
                        self.config.get("monitor.optimization_runtime_enabled", False)
                    ),
                    "feedback_guard": bool(self.config.get("monitor.feedback_guard_enabled", False)),
                    "market_gate": bool(self.config.get("monitor.market_gate_enabled", False)),
                    "position_linkage": bool(
                        self.config.get("monitor.position_linkage_enabled", False)
                    ),
                    "push_enabled": bool(self.config.get("push.enabled", False)),
                },
            },
            "overview": self._build_overview(
                candidate_pool=candidate_pool,
                virtual_trades=virtual_trades,
                holdings=holdings,
                recommendations=recommendations,
                feedback=feedback,
                signals=signals,
                health=health,
            ),
            "today_board": self._build_today_board(
                now=now,
                candidate_pool=candidate_pool,
                virtual_trades=virtual_trades,
                holdings=holdings,
                recommendations=recommendations,
                feedback=feedback,
                signals=signals,
                secondary_launch_tracking=secondary_launch_tracking,
                health=health,
                startup_market_sync=startup_market_sync,
                monitor_session=monitor_session,
                action_center=action_center,
            ),
            "journey": self._build_journey_sections(
                now=now,
                candidate_pool=candidate_pool,
                virtual_trades=virtual_trades,
                holdings=holdings,
                recommendations=recommendations,
                feedback=feedback,
                signals=signals,
                secondary_launch_tracking=secondary_launch_tracking,
                health=health,
                monitor_session=monitor_session,
            ),
            "candidate_pool": candidate_pool,
            "virtual_trades": virtual_trades,
            "holdings": holdings,
            "recommendations": recommendations,
            "feedback": feedback,
            "signals": signals,
            "secondary_launch_tracking": secondary_launch_tracking,
            "health": health,
            "startup_market_sync": startup_market_sync,
            "monitor_session": monitor_session,
            "terminal_runtime": terminal_runtime,
            "action_center": action_center,
        }

    def build_terminal_home_snapshot(self) -> Dict[str, Any]:
        """
        终端 main.py 首页专用：只聚合指挥台展示所需字段。
        避免完整 build_snapshot（大量独立 SQLite 连接 + Windows tasklist 子进程）导致启动后长时间无菜单。
        """
        now = self.now_provider()
        candidate_pool = self._build_candidate_pool_section()
        virtual_trades = self._build_virtual_trade_section()
        holdings = self._build_holdings_section()
        signals = self._build_signal_section()
        health = self._build_health_section(now)
        return {
            "meta": {
                "generated_at": now.isoformat(),
                "generated_label": now.strftime("%Y-%m-%d %H:%M:%S"),
                "app_name": self.config.get("system.name", "量化交易辅助系统"),
                "market_session": self._build_market_session(now),
            },
            "candidate_pool": candidate_pool,
            "virtual_trades": virtual_trades,
            "holdings": holdings,
            "signals": signals,
            "health": health,
        }

    def _build_overview(
        self,
        candidate_pool: Dict[str, Any],
        virtual_trades: Dict[str, Any],
        holdings: Dict[str, Any],
        recommendations: Dict[str, Any],
        feedback: Dict[str, Any],
        signals: Dict[str, Any],
        health: Dict[str, Any],
    ) -> Dict[str, Any]:
        best_feedback = feedback.get("best_summary") or {}
        metrics = [
            {
                "key": "candidate_pool",
                "label": "盘前候选池",
                "value": candidate_pool.get("count", 0),
                "unit": "只",
                "note": f"平均评分 {candidate_pool.get('avg_score', 0):.1f}",
                "tone": "teal",
            },
            {
                "key": "open_virtual_trades",
                "label": "虚拟持仓",
                "value": virtual_trades.get("open_count", 0),
                "unit": "笔",
                "note": f"累计信号 {virtual_trades.get('stats', {}).get('total_signals', 0)}",
                "tone": "navy",
            },
            {
                "key": "closed_virtual_trades",
                "label": "已平仓跟踪",
                "value": virtual_trades.get("closed_count", 0),
                "unit": "笔",
                "note": f"胜率 {virtual_trades.get('stats', {}).get('win_rate_pct', 0):.1f}%",
                "tone": "emerald",
            },
            {
                "key": "active_holdings",
                "label": "真实持仓",
                "value": holdings.get("count", 0),
                "unit": "只",
                "note": f"浮盈均值 {holdings.get('avg_unrealized_pct', 0):.2f}%",
                "tone": "amber",
            },
            {
                "key": "recent_signals",
                "label": "近两周信号",
                "value": signals.get("recent_count", 0),
                "unit": "条",
                "note": signals.get("latest_signal_label", "暂无信号"),
                "tone": "rose",
            },
            {
                "key": "feedback_best",
                "label": "复盘最佳窗口",
                "value": best_feedback.get("mean_net_return_pct", 0),
                "unit": "%",
                "note": best_feedback.get("label", "暂无闭环结论"),
                "tone": "gold",
                "is_percentage": True,
            },
            {
                "key": "runtime_health",
                "label": "运行健康",
                "value": health.get("status_label", "未知"),
                "unit": "",
                "note": health.get("subtitle", "暂无健康快照"),
                "tone": health.get("tone", "slate"),
                "is_text": True,
            },
            {
                "key": "recommendation_days",
                "label": "历史推荐日",
                "value": recommendations.get("daily_count", 0),
                "unit": "天",
                "note": recommendations.get("latest_date_label", "暂无盘前历史"),
                "tone": "plum",
            },
        ]

        return {
            "headline": {
                "health_status": health.get("status", "unknown"),
                "health_label": health.get("status_label", "未知"),
                "candidate_status": candidate_pool.get("freshness_label", "暂无候选池"),
                "last_signal_label": signals.get("latest_signal_label", "暂无最近信号"),
                "recommendation_status": recommendations.get("latest_date_label", "暂无推荐记录"),
            },
            "metrics": metrics,
        }

    def _build_today_board(
        self,
        now: datetime,
        candidate_pool: Dict[str, Any],
        virtual_trades: Dict[str, Any],
        holdings: Dict[str, Any],
        recommendations: Dict[str, Any],
        feedback: Dict[str, Any],
        signals: Dict[str, Any],
        secondary_launch_tracking: Dict[str, Any],
        health: Dict[str, Any],
        startup_market_sync: Dict[str, Any],
        monitor_session: Dict[str, Any],
        action_center: Dict[str, Any],
    ) -> Dict[str, Any]:
        market_session = self._build_market_session(now)
        status = "可交易"
        tone = "green"
        action = "等待盘中信号"
        reason = "候选池已生成，按盘中信号执行。"

        if health.get("status") == "stale":
            status = "仅复盘"
            tone = "slate"
            action = "先恢复系统链路"
            reason = "实时监控停更，当前更适合查看计划和复盘。"
        elif not candidate_pool.get("count"):
            status = "休息"
            tone = "amber"
            action = "先生成今日计划"
            reason = "当前没有可执行候选，不建议主观找票。"
        elif market_session.get("phase") in {"休市", "盘后"}:
            status = "准备中"
            tone = "slate"
            action = "查看明日计划"
            reason = "当前不在交易时段，重点是整理候选和复盘。"
        elif market_session.get("phase") == "盘前":
            status = "可交易"
            tone = "green"
            action = "圈定重点观察票"
            reason = "盘前只做缩圈，不直接下结论。"
        elif monitor_session.get("is_active"):
            status = "可交易"
            tone = "green"
            action = "正在盯盘"
            reason = monitor_session.get("display_text", "监控会话已启动，等待盘中信号。")
        elif market_session.get("phase") == "午间休市":
            status = "谨慎"
            tone = "amber"
            action = "复核上午信号"
            reason = "午间适合确认风险与已出现信号，不适合冲动加仓。"
        elif holdings.get("count", 0) and float(holdings.get("total_unrealized_pct", 0) or 0) < -2:
            status = "谨慎"
            tone = "amber"
            action = "优先处理风险"
            reason = "真实持仓浮盈承压，先管控回撤。"

        best_intraday = feedback.get("best_intraday_subtype") or {}
        tracking_summary = secondary_launch_tracking.get("summary") or {}
        top_blockers = tracking_summary.get("top_blockers") or []
        return {
            "status": status,
            "tone": tone,
            "action": action,
            "reason": reason,
            "cards": [
                {
                    "label": "今日状态",
                    "value": status,
                    "note": reason,
                    "tone": tone,
                },
                {
                    "label": "今日主策略",
                    "value": "二次启动",
                    "note": "默认围绕计划-触发-结果三段节奏使用",
                    "tone": "teal",
                },
                {
                    "label": "今日候选数",
                    "value": f"{int(candidate_pool.get('count', 0) or 0)}只",
                    "note": f"平均评分 {float(candidate_pool.get('avg_score', 0) or 0):.1f}",
                    "tone": "navy",
                },
                {
                    "label": "当前动作",
                    "value": action,
                    "note": monitor_session.get("display_text") or market_session.get("detail", "按当前阶段执行"),
                    "tone": "gold",
                },
            ],
            "quick_actions": [
                {
                    "key": "generate_plan",
                    "label": "生成今日计划",
                    "hint": "盘前候选、市场结论、观察重点一次看完",
                },
                {
                    "key": "enter_stage",
                    "label": "进入当前阶段",
                    "hint": f"当前阶段：{market_session.get('phase', '未知')}",
                },
            ],
            "highlights": [
                f"市场阶段：{market_session.get('phase', '未知')}",
                f"最近推荐日：{recommendations.get('latest_date') or '暂无'}",
                f"最近信号：{signals.get('latest_signal_label', '暂无最近信号')}",
                f"盯盘状态：{monitor_session.get('status_label', '未开始')}",
                f"最近动作：{action_center.get('latest_summary', '暂无执行记录')}",
                f"启动同步：{startup_market_sync.get('summary', '暂无记录')}",
                (
                    f"当前最优盘中子类型：{best_intraday.get('signal_type')} "
                    f"胜率{float(best_intraday.get('win_rate_pct', 0) or 0):.1f}%"
                    if best_intraday
                    else "当前暂无足够盘中闭环结论"
                ),
                (
                    f"二次启动主阻断：{top_blockers[0].get('reason')} ({int(top_blockers[0].get('count', 0) or 0)}次)"
                    if top_blockers
                    else "二次启动阻断原因暂无统计"
                ),
            ],
        }

    @staticmethod
    def _normalize_journey_symbol(raw: Optional[str]) -> Optional[str]:
        """将 ts_code 或纯数字代码规范为 6 位 A 股代码。"""
        if not raw:
            return None
        s = str(raw).strip().upper()
        if "." in s:
            head = s.split(".", 1)[0]
            digits = "".join(c for c in head if c.isdigit())
        else:
            digits = "".join(c for c in s if c.isdigit())
        if not digits:
            return None
        if len(digits) >= 6:
            return digits[-6:]
        return digits.zfill(6)

    def _row_to_quote_payload(self, row: Any) -> Dict[str, Any]:
        """将实时行情行转为看板 journey 项可序列化字段。"""
        import pandas as pd

        def _float(name: str) -> float:
            try:
                v = row.get(name) if hasattr(row, "get") else row[name]
                if v is None or (isinstance(v, float) and pd.isna(v)):
                    return 0.0
                return float(v)
            except (TypeError, ValueError, KeyError):
                return 0.0

        dt_str = ""
        try:
            if hasattr(row, "index") and "datetime" in row.index:
                dv = row["datetime"]
                if dv is not None and not pd.isna(dv):
                    dt_str = pd.Timestamp(dv).strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            dt_str = ""
        if not dt_str:
            d = str(row.get("date", "") if hasattr(row, "get") else "").strip()
            t = str(row.get("time", "") if hasattr(row, "get") else "").strip()
            dt_str = f"{d} {t}".strip() or "--"

        return {
            "quote_ok": True,
            "quote_price": _float("price"),
            "quote_pct_change": _float("pct_change"),
            "quote_high": _float("high"),
            "quote_low": _float("low"),
            "quote_open": _float("open"),
            "quote_volume": _float("volume"),
            "quote_pre_close": _float("pre_close"),
            "quote_time": dt_str,
            "quote_source": "tushare新浪",
        }

    def _fetch_journey_realtime_quotes_map(
        self, codes: List[str]
    ) -> tuple[Dict[str, Dict[str, Any]], str]:
        """
        批量拉取新浪实时行情。
        返回 (6 位代码 -> 行情字段, 状态: ok / empty / error)。
        """
        from src.modules.realtime_quote_fetcher import RealtimeQuoteFetcher

        uniq: List[str] = []
        seen: set[str] = set()
        for c in codes:
            if c and c not in seen:
                seen.add(c)
                uniq.append(c)
        if not uniq:
            return {}, "empty"
        out: Dict[str, Dict[str, Any]] = {}
        try:
            token = self.config.get("tushare.token") or self.config.get("data_source.tushare_token")
            fetcher = RealtimeQuoteFetcher(token=token) if token else RealtimeQuoteFetcher()
            df = fetcher.get_realtime_quotes_batch(uniq, batch_size=50)
            if df is None or getattr(df, "empty", True):
                return {}, "empty"
            for _, row in df.iterrows():
                sym = str(row.get("symbol", "") or "").strip()
                if not sym:
                    continue
                key = sym.zfill(6)
                out[key] = self._row_to_quote_payload(row)
            return out, ("ok" if out else "empty")
        except Exception:
            logger.exception("盘中盯盘实时行情拉取失败")
            return {}, "error"

    def _get_cached_realtime_quotes(
        self, codes: List[str], ttl_seconds: int = 120
    ) -> Dict[str, Dict[str, Any]]:
        if ttl_seconds <= 0:
            return {}
        now_ts = time.time()
        out: Dict[str, Dict[str, Any]] = {}
        for code in codes:
            key = str(code or "").strip()
            if not key:
                continue
            cached_at = self._realtime_quote_cache_at.get(key)
            payload = self._realtime_quote_cache.get(key)
            if cached_at is None or not payload:
                continue
            age = now_ts - cached_at
            if age > ttl_seconds:
                continue
            item = dict(payload)
            item["quote_cached"] = True
            item["quote_cache_age_seconds"] = round(age, 1)
            src = str(item.get("quote_source") or "realtime")
            if "cache" not in src.lower():
                item["quote_source"] = f"{src} (cache)"
            out[key] = item
        return out

    def _fetch_journey_realtime_quotes_map_resilient(
        self, codes: List[str]
    ) -> tuple[Dict[str, Dict[str, Any]], str]:
        """
        Resilient realtime quote fetch with retry and short-lived cache fallback.
        """
        uniq: List[str] = []
        seen: set[str] = set()
        for c in codes:
            if c and c not in seen:
                seen.add(c)
                uniq.append(c)
        if not uniq:
            return {}, "empty"

        try:
            quote_map, status = self._fetch_journey_realtime_quotes_map(uniq)
            if quote_map:
                now_ts = time.time()
                for key, payload in quote_map.items():
                    item = dict(payload or {})
                    item["quote_cached"] = False
                    quote_map[key] = item
                    self._realtime_quote_cache[key] = dict(item)
                    self._realtime_quote_cache_at[key] = now_ts
                return quote_map, status
        except Exception as exc:
            logger.warning("realtime fetch primary attempt failed: %s", exc)

        try:
            time.sleep(0.35)
            quote_map, status = self._fetch_journey_realtime_quotes_map(uniq)
            if quote_map:
                now_ts = time.time()
                for key, payload in quote_map.items():
                    item = dict(payload or {})
                    item["quote_cached"] = False
                    quote_map[key] = item
                    self._realtime_quote_cache[key] = dict(item)
                    self._realtime_quote_cache_at[key] = now_ts
                return quote_map, status
        except Exception as exc:
            logger.warning("realtime fetch retry failed: %s", exc)

        cached = self._get_cached_realtime_quotes(uniq, ttl_seconds=120)
        if cached:
            status = "cached" if len(cached) == len(uniq) else "partial_cached"
            return cached, status
        return {}, "error"

    def _merge_quote_into_journey_item(
        self, item: Dict[str, Any], quotes_map: Dict[str, Dict[str, Any]]
    ) -> None:
        key = None
        for field in ("symbol", "ts_code"):
            key = self._normalize_journey_symbol(item.get(field))
            if key:
                break
        if not key:
            item["quote_ok"] = False
            item["quote_hint"] = "代码无效"
            return
        payload = quotes_map.get(key)
        if not payload:
            item["quote_ok"] = False
            item["quote_hint"] = "暂无实时行情"
            return
        item.update(payload)

    def _build_journey_sections(
        self,
        now: datetime,
        candidate_pool: Dict[str, Any],
        virtual_trades: Dict[str, Any],
        holdings: Dict[str, Any],
        recommendations: Dict[str, Any],
        feedback: Dict[str, Any],
        signals: Dict[str, Any],
        secondary_launch_tracking: Dict[str, Any],
        health: Dict[str, Any],
        monitor_session: Dict[str, Any],
    ) -> Dict[str, Any]:
        market_session = self._build_market_session(now)
        pre_market_items = []
        for idx, item in enumerate(candidate_pool.get("top_candidates", [])[:3], 1):
            score = float(item.get("score", 0) or 0)
            pre_market_items.append(
                {
                    "symbol": item.get("symbol"),
                    "name": item.get("name"),
                    "level": "强关注" if idx == 1 else ("可观察" if score >= 80 else "低优先"),
                    "summary": (
                        "优先等待盘中回踩确认"
                        if idx == 1
                        else "保留观察，不抢开盘"
                    ),
                    "focus": "等盘中信号，不直接追涨",
                    "risk_tip": "高开过多不追，弱于VWAP放弃",
                    "score": score,
                }
            )

        if not pre_market_items:
            pre_market_items.append(
                {
                    "symbol": "",
                    "name": "今日无推荐",
                    "level": "休息",
                    "summary": "当前没有满足条件的候选，今天以观察为主。",
                    "focus": "不开新仓",
                    "risk_tip": "避免临时找票",
                    "score": 0.0,
                }
            )

        latest_signal_items = []
        for row in (signals.get("latest_items") or [])[:3]:
            latest_signal_items.append(
                {
                    "symbol": row.get("ts_code"),
                    "name": row.get("name"),
                    "signal_type": row.get("signal_type"),
                    "signal_time": row.get("signal_time"),
                    "trigger_reason": row.get("trigger_reason") or "等待确认",
                    "suggestion": row.get("suggestion") or "仅观察",
                }
            )

        watch_list: List[Dict[str, Any]] = []
        for idx, item in enumerate((candidate_pool.get("top_candidates") or [])[:3]):
            watch_list.append(
                {
                    "symbol": item.get("symbol") or item.get("ts_code"),
                    "name": item.get("name"),
                    "status": "主盯" if idx == 0 else "观察",
                    "note": (
                        "等待盘中确认，不要提前追。"
                        if idx == 0
                        else "不是第一优先，避免分散注意力。"
                    ),
                }
            )

        if not watch_list and latest_signal_items:
            # 候选池为空时，用最近信号临时补齐盯盘列表，避免“盯盘无内容”影响可信度。
            seen_symbols: set[str] = set()
            for row in latest_signal_items:
                code = self._normalize_journey_symbol(row.get("symbol"))
                if not code or code in seen_symbols:
                    continue
                seen_symbols.add(code)
                watch_list.append(
                    {
                        "symbol": row.get("symbol"),
                        "name": row.get("name"),
                        "status": "观察",
                        "note": "候选池为空，临时用最近信号生成盯盘列表（建议先生成盘前计划）。",
                    }
                )
                if len(watch_list) >= 3:
                    break

        quote_codes: List[str] = []
        for w in watch_list:
            k = self._normalize_journey_symbol(w.get("symbol"))
            if k:
                quote_codes.append(k)
        for s in latest_signal_items:
            for field in ("symbol", "ts_code"):
                k = self._normalize_journey_symbol(s.get(field))
                if k:
                    quote_codes.append(k)
                    break
        quotes_map, quote_batch_status = self._fetch_journey_realtime_quotes_map_resilient(quote_codes)
        for w in watch_list:
            self._merge_quote_into_journey_item(w, quotes_map)
        for s in latest_signal_items:
            self._merge_quote_into_journey_item(s, quotes_map)

        intraday_title = "当前无可执行买点"
        intraday_action = "继续等待"
        if latest_signal_items:
            intraday_title = f"最近出现 {len(latest_signal_items)} 条信号"
            intraday_action = "只处理已触发信号"
        elif monitor_session.get("is_active"):
            intraday_title = "盘中盯盘中"
            intraday_action = "监控会话已启动，继续等待信号"

        open_trades = virtual_trades.get("open_trades") or []
        tracking_summary = secondary_launch_tracking.get("summary") or {}
        review_rows = secondary_launch_tracking.get("review_rows") or []
        top_blockers = tracking_summary.get("top_blockers") or []

        # 候选池“有无信号 + 原因”对齐到用户口径
        signal_by_code: Dict[str, Dict[str, Any]] = {}
        for row in latest_signal_items:
            code = self._normalize_journey_symbol(row.get("symbol") or row.get("ts_code"))
            if code:
                signal_by_code[code] = row

        blocker_by_code: Dict[str, Dict[str, Any]] = {}
        for row in review_rows:
            code = self._normalize_journey_symbol(row.get("ts_code") or row.get("symbol"))
            if code and code not in blocker_by_code:
                blocker_by_code[code] = row

        # 盯盘列表补齐“有无信号 + 具体原因”
        for w in watch_list:
            code = self._normalize_journey_symbol(w.get("symbol") or w.get("ts_code"))
            if not code:
                w["signal_status_label"] = "未知"
                w["signal_reason"] = "代码无效，无法判断是否触发。"
                continue
            if code in signal_by_code:
                srow = signal_by_code[code]
                w["signal_status_label"] = "已触发"
                w["signal_reason"] = f"{srow.get('signal_type') or '信号'}：{srow.get('trigger_reason') or '已满足触发条件'}"
                continue
            brow = blocker_by_code.get(code) or {}
            w["signal_status_label"] = "未触发"
            if brow.get("blocker_label") or brow.get("not_pushed_reason"):
                w["signal_reason"] = brow.get("blocker_label") or brow.get("not_pushed_reason")
            else:
                # 如果没有逐只阻断记录，至少把“数据不足”具体化到系统层原因，避免影响操作判断
                degraded = monitor_session.get("degraded_reasons") or []
                if health.get("status") == "stale":
                    w["signal_reason"] = "监控健康快照停更：盘中分钟数据/闸门判断可能不可用，请先检查并重启监控。"
                elif not monitor_session.get("runtime_online", False):
                    w["signal_reason"] = "监控进程未在线：请在操作中心“一键开启监控”，否则不会产生日内买点判定。"
                elif degraded:
                    w["signal_reason"] = f"数据源降级：{degraded[0]}"
                elif quote_batch_status in {"empty", "error"}:
                    w["signal_reason"] = "实时行情/分钟数据获取异常：无法完成盘中确认判定，建议检查网络与数据源。"
                else:
                    w["signal_reason"] = "未生成逐只阻断记录：建议保持监控在线并生成盘后复盘，以拿到明确阻断标签。"

        post_market_summary = {
            "recommended_count": int(candidate_pool.get("count", 0) or 0),
            "triggered_count": int(tracking_summary.get("buy_signal_count", len(latest_signal_items)) or 0),
            "best_signal": (
                feedback.get("best_intraday_subtype", {}) or {}
            ).get("signal_type")
            or "暂无明确最佳信号",
            "main_blocker": "暂无复盘结论",
            "done_right": [],
            "missed_today": [],
            "next_day_actions": [],
            "blocked_rows": review_rows[:8],
        }

        # 候选池逐只（最多 6 条），给用户看“有没有信号 + 原因”
        candidate_signal_rows: List[Dict[str, Any]] = []
        hit_count = 0
        miss_count = 0
        reasons_counter: Counter[str] = Counter()
        for item in (candidate_pool.get("top_candidates") or [])[:10]:
            code = self._normalize_journey_symbol(item.get("symbol") or item.get("ts_code"))
            if not code:
                continue
            name = item.get("name")
            symbol = item.get("symbol") or code
            if code in signal_by_code:
                hit_count += 1
                srow = signal_by_code[code]
                reason = f"{srow.get('signal_type') or '信号'}：{srow.get('trigger_reason') or '已满足触发条件'}"
                candidate_signal_rows.append(
                    {"symbol": symbol, "name": name, "status": "已触发", "reason": reason}
                )
            else:
                miss_count += 1
                brow = blocker_by_code.get(code) or {}
                if brow.get("blocker_label") or brow.get("not_pushed_reason"):
                    reason = brow.get("blocker_label") or brow.get("not_pushed_reason")
                else:
                    degraded = monitor_session.get("degraded_reasons") or []
                    if health.get("status") == "stale":
                        reason = "监控健康快照停更：盘中分钟数据/闸门判断可能不可用"
                    elif not monitor_session.get("runtime_online", False):
                        reason = "监控进程未在线：未执行盘中判定"
                    elif degraded:
                        reason = f"数据源降级：{degraded[0]}"
                    elif quote_batch_status in {"empty", "error"}:
                        reason = "实时行情/分钟数据获取异常：无法完成盘中确认判定"
                    else:
                        reason = "未生成逐只阻断记录：当天未出现可执行形态或数据不足"
                reasons_counter[str(reason or "未触发原因暂无记录")] += 1
                candidate_signal_rows.append(
                    {"symbol": symbol, "name": name, "status": "未触发", "reason": reason}
                )

        main_reason = reasons_counter.most_common(1)[0][0] if reasons_counter else ""
        post_market_summary["candidate_pool_count"] = int(candidate_pool.get("count", 0) or 0)
        post_market_summary["candidate_hit_count"] = int(hit_count)
        post_market_summary["candidate_miss_count"] = int(miss_count)
        post_market_summary["candidate_main_reason"] = main_reason or post_market_summary.get("main_blocker")
        post_market_summary["candidate_signal_rows"] = candidate_signal_rows[:6]
        insights = feedback.get("intraday_insights") or {}
        conclusions = list(insights.get("conclusions") or [])
        actions = list(insights.get("action_items") or [])
        if conclusions:
            post_market_summary["main_blocker"] = conclusions[0]
            post_market_summary["done_right"] = conclusions[:2]
        else:
            post_market_summary["done_right"] = [
                "盘前候选池与盘中信号已经打通，可直接按节奏使用。"
            ]
        if actions:
            post_market_summary["missed_today"] = actions[:2]
            post_market_summary["next_day_actions"] = actions[:3]
        else:
            post_market_summary["missed_today"] = [
                "当前还缺少足够的盘后行动建议，建议继续积累样本。"
            ]
            post_market_summary["next_day_actions"] = [
                "明天继续围绕上午盘的二次启动回踩确认执行。"
            ]
        if holdings.get("count", 0):
            post_market_summary["next_day_actions"].append(
                f"真实持仓 {int(holdings.get('count', 0) or 0)} 只，先看风险再决定是否开新仓。"
            )
        if top_blockers:
            post_market_summary["main_blocker"] = str(top_blockers[0].get("reason") or post_market_summary["main_blocker"])
            post_market_summary["missed_today"] = [
                f"{item.get('reason', '未知原因')}：{int(item.get('count', 0) or 0)}次"
                for item in top_blockers[:3]
            ]
        blocked_rows = [
            row for row in review_rows
            if not row.get("has_buy_signal")
            and str(row.get("blocker_tag", "") or "") in {"near_high_supply", "afternoon_threshold", "market_gate_weak"}
        ]
        if blocked_rows:
            post_market_summary["next_day_actions"].append(
                "重点复查被前高抛压、午后阈值、市场共振闸门拦下的股票，避免把边缘突破当有效信号。"
            )

        return {
            "current_stage": market_session.get("phase", "未知"),
            "pre_market": {
                "title": "今天能不能做，做哪几只",
                "action_label": "一键生成今日计划",
                "summary": (
                    "今天先缩小观察范围，盘前不直接下单。"
                    if candidate_pool.get("count")
                    else "今天没有合格候选，系统建议休息。"
                ),
                "items": pre_market_items,
            },
            "intraday": {
                "title": intraday_title,
                "action_label": "一键开始盘中盯盘",
                "summary": intraday_action,
                "monitor_session": monitor_session,
                "watch_list": watch_list,
                "quote_batch_status": quote_batch_status,
                "signals": latest_signal_items,
                "risk_hint": (
                    "实时链路停更，当前只看计划不做执行。"
                    if health.get("status") == "stale"
                    else (
                        monitor_session.get("display_text")
                        or "只处理已触发信号，别把盘前候选当成下单指令。"
                    )
                ),
                "blocked_rows": review_rows[:6],
            },
            "post_market": {
                "title": "今天哪里做对了，明天该怎么做",
                "action_label": "一键生成今日复盘",
                "summary": post_market_summary,
                "open_trade_count": len(open_trades),
            },
        }

    def _build_secondary_launch_tracking_section(self) -> Dict[str, Any]:
        reports = sorted(self.results_dir.glob("secondary_launch_recent_tracking_*.json"), reverse=True)
        if not reports:
            return {"summary": {}, "review_rows": [], "report_json": None}
        latest_path = reports[0]
        try:
            payload = json.loads(latest_path.read_text(encoding="utf-8"))
        except Exception:
            logger.exception("读取二次启动跟踪报表失败: %s", latest_path)
            return {"summary": {}, "review_rows": [], "report_json": str(latest_path)}

        summary = dict(payload.get("intraday_review_summary") or {})
        top_blockers = summary.get("top_not_pushed_reasons") or []
        review_rows = []
        for item in payload.get("details", [])[:20]:
            review_rows.append(
                {
                    "signal_date": item.get("signal_date"),
                    "ts_code": item.get("ts_code"),
                    "name": item.get("name"),
                    "rank": item.get("rank"),
                    "has_buy_signal": bool(item.get("has_buy_signal")),
                    "signal_type": item.get("signal_type"),
                    "trigger_time": item.get("trigger_time"),
                    "push_reason": item.get("push_reason"),
                    "not_pushed_reason": item.get("not_pushed_reason"),
                    "blocker_tag": item.get("blocker_tag"),
                    "blocker_label": blocker_tag_to_label(item.get("blocker_tag")),
                    "blocker_detail": item.get("blocker_detail"),
                    "confidence": float(item.get("confidence", 0.0) or 0.0),
                }
            )
        return {
            "report_json": str(latest_path.relative_to(self.project_root)),
            "generated_at": payload.get("generated_at"),
            "summary": {
                "reviewed_signal_count": int(summary.get("reviewed_signal_count", 0) or 0),
                "buy_signal_count": int(summary.get("buy_signal_count", 0) or 0),
                "buy_signal_ratio_pct": round(self._ratio_to_percent(summary.get("buy_signal_ratio")), 2),
                "not_pushed_count": int(summary.get("not_pushed_count", 0) or 0),
                "top_blockers": [
                    {
                        **item,
                        "label": blocker_tag_to_label(item.get("tag")) if item.get("tag") else item.get("reason"),
                    }
                    for item in top_blockers[:5]
                ],
            },
            "review_rows": review_rows,
        }

    def _build_monitor_session_section(
        self,
        health: Dict[str, Any],
        now: datetime,
    ) -> Dict[str, Any]:
        session = self.monitor_session_service.get_session()
        terminal_runtime = self._build_terminal_runtime_section(now)
        is_active = bool(session.get("is_active", False))
        last_refresh_at = session.get("last_refresh_at")
        display_text = "尚未开始盘中盯盘。"
        status_label = str(session.get("status_label", "未开始") or "未开始")
        candidate_count = int(self._fetch_candidate_pool_count() or 0)
        degraded_reasons = self._fetch_monitor_degraded_reasons()
        runtime_online = health.get("status") == "healthy" or terminal_runtime.get("terminal_online", False)
        runtime_usable = runtime_online and candidate_count > 0 and not degraded_reasons

        if is_active:
            display_text = "监控会话已启动，等待盘中信号。"
            if health.get("status") == "stale":
                status_label = "会话已开，但实时链路停更"
                display_text = "已进入盯盘状态，但健康快照停更，请先检查主监控服务。"
            elif candidate_count <= 0:
                status_label = "会话已开，但候选池为空"
                display_text = "已进入盯盘状态，但当前候选池为空，请先生成盘前计划。"
            elif degraded_reasons:
                status_label = "会话已开，但数据源已降级"
                display_text = f"已进入盯盘状态，但当前存在降级告警：{degraded_reasons[0]}。"
            elif last_refresh_at:
                age_seconds = self._age_seconds(last_refresh_at, now)
                if age_seconds is not None:
                    display_text = f"最近一次盯盘刷新在 {last_refresh_at}，距今 {int(age_seconds)} 秒。"

        return {
            **session,
            "is_active": is_active,
            "status_label": status_label,
            "runtime_online": runtime_online,
            "runtime_usable": runtime_usable,
            "runtime_status_label": (
                "实时监控在线且可用"
                if runtime_usable
                else "实时监控在线但不可用"
                if runtime_online
                else "实时监控未在线"
            ),
            "display_text": display_text,
            "last_refresh_at": last_refresh_at,
            "candidate_count": candidate_count,
            "degraded_reasons": degraded_reasons,
            "terminal_runtime_status": terminal_runtime.get("status_label"),
            "terminal_runtime_text": terminal_runtime.get("display_text"),
        }

    def _build_terminal_runtime_section(self, now: datetime) -> Dict[str, Any]:
        return self.terminal_runtime_service.inspect(now=now)

    def _build_action_center_section(self) -> Dict[str, Any]:
        recent = self.action_record_service.get_recent(limit=20)
        latest = recent[0] if recent else None
        latest_summary = "暂无执行记录"
        if latest:
            latest_summary = (
                f"{self._action_label(latest.get('action_key'))} / "
                f"{self._action_status_label(latest.get('status'))} / "
                f"{latest.get('created_time')}"
            )
        latest_success = next((row for row in recent if row.get("status") == "success"), None)
        latest_failed = next((row for row in recent if row.get("status") == "failed"), None)
        timeline = [
            {
                "action_label": self._action_label(row.get("action_key")),
                "status_label": self._action_status_label(row.get("status")),
                "status_tone": "green" if row.get("status") == "success" else "red",
                "message": row.get("message"),
                "created_time": row.get("created_time"),
            }
            for row in recent
        ]
        outbox = {
            "available": False,
            "pending": 0,
            "failed": 0,
            "success": 0,
        }
        try:
            row = self.record_db.query_one(
                """
                SELECT
                    SUM(CASE WHEN status IN ('pending') THEN 1 ELSE 0 END) AS pending_count,
                    SUM(CASE WHEN status IN ('failed') THEN 1 ELSE 0 END) AS failed_count,
                    SUM(CASE WHEN status IN ('success') THEN 1 ELSE 0 END) AS success_count
                FROM push_outbox
                """
            )
            if row is not None:
                outbox = {
                    "available": True,
                    "pending": int(row.get("pending_count") or 0),
                    "failed": int(row.get("failed_count") or 0),
                    "success": int(row.get("success_count") or 0),
                }
        except Exception:
            outbox = {
                "available": False,
                "pending": 0,
                "failed": 0,
                "success": 0,
            }
        return {
            "latest_summary": latest_summary,
            "latest": latest,
            "recent": recent,
            "latest_success": latest_success,
            "latest_failed": latest_failed,
            "timeline": timeline,
            "push_outbox": outbox,
        }

    def _build_startup_market_sync_section(self) -> Dict[str, Any]:
        default_summary = "未记录启动自动校验"
        default_state = {
            "available": False,
            "status": "unknown",
            "status_label": "未执行",
            "message": "启动后尚未记录市场数据自动校验任务",
            "updated_at": None,
            "started_at": None,
            "ended_at": None,
            "target_trade_date": None,
            "latest_trade_date_before": None,
            "latest_trade_date_after": None,
            "missing_trade_dates": [],
            "missing_trade_dates_count": 0,
            "summary": default_summary,
        }

        state = self._load_json(self.background_tasks_state_path)
        tasks = state.get("tasks") if isinstance(state, dict) else []
        if not isinstance(tasks, list):
            return default_state

        row = next(
            (
                item
                for item in tasks
                if isinstance(item, dict) and str(item.get("action_key") or "") == "startup_market_data_sync"
            ),
            None,
        )
        if not row:
            return default_state

        payload = row.get("payload")
        payload = payload if isinstance(payload, dict) else {}
        missing_trade_dates = payload.get("missing_trade_dates")
        if not isinstance(missing_trade_dates, list):
            missing_trade_dates = []

        status = str(row.get("status") or "unknown")
        status_label_map = {
            "queued": "排队中",
            "running": "执行中",
            "success": "成功",
            "failed": "失败",
        }
        status_label = status_label_map.get(status, "未知")
        target_trade_date = payload.get("target_trade_date")
        updated_at = row.get("updated_at")
        message = row.get("message") or payload.get("message") or ""

        if status == "success":
            summary = f"成功，目标交易日 {target_trade_date or '--'}，补齐 {len(missing_trade_dates)} 个交易日"
        elif status == "failed":
            summary = f"失败：{message or '请检查日志'}"
        elif status == "running":
            summary = "执行中，正在校验并补齐市场数据"
        elif status == "queued":
            summary = "排队中，等待启动任务执行"
        else:
            summary = default_summary
        if updated_at:
            summary = f"{summary}（{updated_at}）"

        return {
            "available": True,
            "status": status,
            "status_label": status_label,
            "message": message,
            "updated_at": updated_at,
            "started_at": row.get("started_at"),
            "ended_at": row.get("ended_at"),
            "target_trade_date": target_trade_date,
            "latest_trade_date_before": payload.get("latest_trade_date_before"),
            "latest_trade_date_after": payload.get("latest_trade_date_after"),
            "missing_trade_dates": missing_trade_dates,
            "missing_trade_dates_count": len(missing_trade_dates),
            "summary": summary,
        }

    @staticmethod
    def _action_label(action_key: Any) -> str:
        mapping = {
            "generate_plan": "生成今日计划",
            "enter_stage": "进入当前阶段",
            "start_intraday_watch": "开始盘中盯盘",
            "start_monitor_runtime": "启动实时监控",
            "stop_monitor_runtime": "停止实时监控",
            "refresh_intraday_status": "刷新盘中状态",
            "generate_post_market_review": "生成今日复盘",
            "update_stock_data": "更新股票数据",
            "run_stock_selection": "执行今日选股",
            "push_selection_wecom": "推送选股到企业微信",
            "push_review_wecom": "推送复盘到企业微信",
            "retry_push_outbox": "重试推送队列",
            "update_holding": "更新持仓",
            "remove_holding": "删除持仓",
            "clear_candidate_pool": "清空候选池",
            "clear_history_records": "清理历史记录",
            "clear_virtual_trades": "清理虚拟交易",
        }
        key = str(action_key or "")
        return mapping.get(key, key or "未知动作")

    @staticmethod
    def _action_status_label(status: Any) -> str:
        return "成功" if str(status or "") == "success" else "失败"

    def _fetch_candidate_pool_count(self) -> int:
        payload = self._load_json(self.candidate_cache_path) or {}
        if isinstance(payload, list):
            return len(payload)
        if not isinstance(payload, dict):
            return 0

        # 兼容多种候选池缓存结构：
        # - {"candidates":[...]}
        # - {"top_candidates":[...]}
        # - {"count": N}
        raw_candidates = payload.get("candidates")
        if isinstance(raw_candidates, list):
            return len(raw_candidates)
        raw_top = payload.get("top_candidates")
        if isinstance(raw_top, list):
            return len(raw_top)
        try:
            return int(payload.get("count") or 0)
        except (TypeError, ValueError):
            return 0

    def _fetch_monitor_degraded_reasons(self) -> List[str]:
        rows = self._fetch_all(
            self.quant_db_path,
            """
            SELECT title, message
            FROM runtime_incident
            WHERE component IN ('monitor.loop', 'service.monitor_check')
            ORDER BY incident_time DESC
            LIMIT 8
            """,
        )
        degraded = []
        for row in rows:
            merged = f"{row.get('title', '')} {row.get('message', '')}"
            if "降级" in merged or "获取失败" in merged or "No realtime market data available" in merged:
                degraded.append(merged[:60])
        return degraded[:3]

    def _build_candidate_pool_section(self) -> Dict[str, Any]:
        payload = self._load_json(self.candidate_cache_path) or {}
        raw_candidates = payload.get("candidates") if isinstance(payload, dict) else payload
        candidates = raw_candidates if isinstance(raw_candidates, list) else []
        candidates = sorted(
            candidates,
            key=lambda item: float(item.get("score", 0) or 0),
            reverse=True,
        )
        quote_map = self._load_latest_daily_quote_map(
            [item.get("ts_code") or item.get("symbol") for item in candidates]
        )
        enriched_candidates = []
        for item in candidates:
            candidate = dict(item or {})
            ts_code = self._normalize_ts_code(candidate.get("ts_code") or candidate.get("symbol"))
            quote = quote_map.get(ts_code) or {}
            # 统一候选卡片展示字段：优先实时/缓存值，缺失时回退最新日线。
            if candidate.get("current_price") is None and quote.get("close") is not None:
                candidate["current_price"] = quote.get("close")
            if candidate.get("last_price") is None and quote.get("close") is not None:
                candidate["last_price"] = quote.get("close")
            if candidate.get("quote_pct_change") is None and quote.get("pct_chg") is not None:
                candidate["quote_pct_change"] = quote.get("pct_chg")
            if candidate.get("pct_chg") is None and quote.get("pct_chg") is not None:
                candidate["pct_chg"] = quote.get("pct_chg")
            if candidate.get("quote_trade_date") is None and quote.get("trade_date") is not None:
                candidate["quote_trade_date"] = quote.get("trade_date")
            enriched_candidates.append(candidate)

        industries = Counter((item.get("industry") or "未分类") for item in enriched_candidates)
        levels = Counter((item.get("level") or "未评级") for item in enriched_candidates)
        avg_score = (
            sum(float(item.get("score", 0) or 0) for item in enriched_candidates) / len(enriched_candidates)
            if enriched_candidates
            else 0.0
        )

        created_time = payload.get("created_time") if isinstance(payload, dict) else None
        freshness_label = "未生成"
        if created_time:
            freshness_label = f"缓存生成于 {created_time}"

        return {
            "date": payload.get("date") if isinstance(payload, dict) else None,
            "created_time": created_time,
            "freshness_label": freshness_label,
            "count": len(enriched_candidates),
            "avg_score": round(avg_score, 2),
            "level_distribution": [
                {"name": name, "value": value}
                for name, value in levels.most_common()
            ],
            "industry_distribution": [
                {"name": name, "value": value}
                for name, value in industries.most_common(8)
            ],
            "top_candidates": enriched_candidates[:10],
        }

    def _build_virtual_trade_section(self) -> Dict[str, Any]:
        payload = self._load_json(self.virtual_trades_path) or {}
        open_trades = list(payload.get("open_trades") or [])
        closed_trades = list(payload.get("closed_trades") or [])

        open_trades = sorted(
            open_trades,
            key=lambda item: item.get("buy_time") or "",
            reverse=True,
        )
        closed_trades = sorted(
            closed_trades,
            key=lambda item: item.get("sell_time") or item.get("buy_time") or "",
            reverse=True,
        )

        stats = dict(payload.get("statistics") or {})
        if closed_trades and not stats.get("total_closed"):
            pnl_values = [
                self._ratio_to_percent(item.get("pnl_pct"))
                for item in closed_trades
                if item.get("pnl_pct") is not None
            ]
            win_count = sum(1 for value in pnl_values if value > 0)
            stats["total_closed"] = len(closed_trades)
            stats["total_signals"] = len(closed_trades) + len(open_trades)
            stats["open_trades"] = len(open_trades)
            stats["win_rate"] = (win_count / len(pnl_values)) if pnl_values else 0
            stats["avg_pnl_pct"] = sum(pnl_values) / len(pnl_values) if pnl_values else 0

        normalized_stats = {
            "total_signals": int(stats.get("total_signals", len(open_trades) + len(closed_trades)) or 0),
            "total_closed": int(stats.get("total_closed", len(closed_trades)) or 0),
            "open_trades": int(stats.get("open_trades", len(open_trades)) or 0),
            "win_rate_pct": self._ratio_to_percent(stats.get("win_rate")),
            "avg_pnl_pct": self._ratio_to_percent(stats.get("avg_pnl_pct")),
            "profit_loss_ratio": round(float(stats.get("profit_loss_ratio", 0) or 0), 2),
            "max_drawdown_pct": self._ratio_to_percent(stats.get("max_drawdown")),
        }

        route_counter: Counter[str] = Counter()
        subtype_counter: Counter[str] = Counter()
        equity_points: List[Dict[str, Any]] = []
        daily_points: Dict[str, Dict[str, Any]] = {}
        cumulative = 0.0

        closed_for_curve = sorted(
            closed_trades,
            key=lambda item: item.get("sell_time") or item.get("buy_time") or "",
        )
        for item in closed_for_curve:
            route = (
                item.get("buy_route")
                or (item.get("details") or {}).get("buy_route")
                or item.get("buy_signal")
                or "未分类"
            )
            route_counter[route] += 1
            subtype = (
                item.get("signal_subtype")
                or (item.get("details") or {}).get("signal_subtype")
                or route
                or item.get("buy_signal")
                or "未分类"
            )
            subtype_counter[subtype] += 1

            pnl_pct = self._ratio_to_percent(item.get("pnl_pct"))
            close_time = item.get("sell_time") or item.get("buy_time") or ""
            cumulative += pnl_pct
            equity_points.append(
                {
                    "time": close_time,
                    "value": round(cumulative, 2),
                    "pnl_pct": round(pnl_pct, 2),
                    "symbol": item.get("symbol") or item.get("ts_code") or "",
                }
            )

            if close_time:
                day = close_time[:10]
                day_bucket = daily_points.setdefault(day, {"date": day, "pnl_pct": 0.0, "count": 0})
                day_bucket["pnl_pct"] += pnl_pct
                day_bucket["count"] += 1

        for item in open_trades:
            route = (
                item.get("buy_route")
                or (item.get("details") or {}).get("buy_route")
                or item.get("buy_signal")
                or "未分类"
            )
            route_counter[route] += 1
            subtype = (
                item.get("signal_subtype")
                or (item.get("details") or {}).get("signal_subtype")
                or route
                or item.get("buy_signal")
                or "未分类"
            )
            subtype_counter[subtype] += 1

        trade_symbols = [item.get("ts_code") or item.get("symbol") for item in open_trades]
        latest_close_map = self._load_latest_close_map(trade_symbols)
        realtime_quotes_map, _ = self._fetch_journey_realtime_quotes_map_resilient(
            [self._normalize_journey_symbol(s) for s in trade_symbols if s]
        )
        normalized_open = []
        for item in open_trades[:12]:
            details = item.get("details") or {}
            last_pnl_pct = details.get("last_pnl_pct")
            peak_pnl_pct = details.get("peak_pnl_pct")
            lowest_pnl_pct = details.get("lowest_pnl_pct")
            buy_price = item.get("buy_price")
            ts_code = self._normalize_ts_code(item.get("ts_code") or item.get("symbol"))
            latest_close = latest_close_map.get(ts_code) or {}
            realtime_quote = realtime_quotes_map.get(ts_code) or {}

            realtime_price = realtime_quote.get("quote_price")
            try:
                realtime_price = float(realtime_price) if realtime_price is not None else None
            except (TypeError, ValueError):
                realtime_price = None

            # 持仓最新价优先实时行情，避免页面长期显示上一交易日价格。
            if realtime_price is not None and realtime_price > 0:
                last_price = realtime_price
                price_source = "cached_realtime" if bool(realtime_quote.get("quote_cached")) else "realtime"
                last_trade_date = realtime_quote.get("quote_time") or latest_close.get("trade_date")
            else:
                last_price = details.get("last_price")
                if last_price is None:
                    last_price = latest_close.get("close")
                price_source = "daily_close"
                last_trade_date = latest_close.get("trade_date")
            if last_pnl_pct is None and buy_price not in (None, 0) and last_price is not None:
                try:
                    last_pnl_pct = (float(last_price) - float(buy_price)) / float(buy_price)
                except (TypeError, ValueError, ZeroDivisionError):
                    last_pnl_pct = None
            normalized_open.append(
                {
                    "symbol": item.get("symbol", ""),
                    "name": item.get("name", ""),
                    "buy_time": item.get("buy_time"),
                    "last_trade_date": last_trade_date,
                    "buy_price": buy_price,
                    "last_price": last_price,
                    "current_price": last_price,
                    "last_pnl_pct": (
                        round(self._ratio_to_percent(last_pnl_pct), 2)
                        if last_pnl_pct is not None
                        else None
                    ),
                    "peak_pnl_pct": (
                        round(self._ratio_to_percent(peak_pnl_pct), 2)
                        if peak_pnl_pct is not None
                        else None
                    ),
                    "lowest_pnl_pct": (
                        round(self._ratio_to_percent(lowest_pnl_pct), 2)
                        if lowest_pnl_pct is not None
                        else None
                    ),
                    "buy_score": item.get("buy_score"),
                    "buy_signal": item.get("buy_signal"),
                    "pool_type": details.get("pool_type"),
                    "buy_route": details.get("buy_route") or item.get("buy_route"),
                    "signal_subtype": details.get("signal_subtype") or item.get("signal_subtype"),
                    "price_source": price_source,
                    "quote_pct_change": realtime_quote.get("quote_pct_change"),
                    "quote_time": realtime_quote.get("quote_time"),
                    "quote_source": realtime_quote.get("quote_source"),
                }
            )

        normalized_closed = []
        for item in closed_trades[:12]:
            details = item.get("details") or {}
            normalized_closed.append(
                {
                    "symbol": item.get("symbol", ""),
                    "name": item.get("name", ""),
                    "buy_time": item.get("buy_time"),
                    "sell_time": item.get("sell_time"),
                    "buy_price": item.get("buy_price"),
                    "sell_price": item.get("sell_price"),
                    "pnl_pct": round(self._ratio_to_percent(item.get("pnl_pct")), 2),
                    "peak_pnl_pct": round(
                        self._ratio_to_percent(
                            item.get("peak_pnl_pct") or details.get("peak_pnl_pct")
                        ),
                        2,
                    ),
                    "sell_reason": item.get("sell_reason"),
                    "buy_signal": item.get("buy_signal"),
                    "signal_subtype": details.get("signal_subtype") or item.get("signal_subtype"),
                }
            )

        return {
            "save_time": payload.get("save_time"),
            "open_count": len(open_trades),
            "closed_count": len(closed_trades),
            "stats": normalized_stats,
            "route_distribution": [
                {"name": name, "value": value}
                for name, value in route_counter.most_common(8)
            ],
            "signal_subtype_distribution": [
                {"name": name, "value": value}
                for name, value in subtype_counter.most_common(8)
            ],
            "equity_curve": equity_points,
            "daily_pnl": list(sorted(daily_points.values(), key=lambda item: item["date"])),
            "open_trades": normalized_open,
            "recent_closed": normalized_closed,
        }

    def _build_holdings_section(self) -> Dict[str, Any]:
        rows = self._fetch_all(
            self.quant_db_path,
            """
            SELECT
                h.ts_code,
                h.name,
                h.hold_price,
                h.hold_num,
                h.hold_date,
                h.update_time,
                (
                    SELECT sd.close
                    FROM stock_daily sd
                    WHERE sd.ts_code = h.ts_code
                    ORDER BY sd.trade_date DESC
                    LIMIT 1
                ) AS latest_close,
                (
                    SELECT sd.trade_date
                    FROM stock_daily sd
                    WHERE sd.ts_code = h.ts_code
                    ORDER BY sd.trade_date DESC
                    LIMIT 1
                ) AS latest_trade_date
            FROM hold_stock h
            WHERE h.status = 1
            ORDER BY h.update_time DESC, h.ts_code
            """,
        )

        total_market_value = 0.0
        total_cost = 0.0
        unrealized_values: List[float] = []
        normalized = []

        for row in rows:
            hold_price = float(row.get("hold_price") or 0)
            hold_num = int(row.get("hold_num") or 0)
            latest_close = row.get("latest_close")
            latest_close = float(latest_close) if latest_close is not None else None
            cost_value = hold_price * hold_num
            market_value = (latest_close or hold_price) * hold_num
            unrealized_pct = ((market_value / cost_value) - 1.0) * 100 if cost_value else 0.0

            total_cost += cost_value
            total_market_value += market_value
            unrealized_values.append(unrealized_pct)

            normalized.append(
                {
                    "ts_code": row.get("ts_code"),
                    "name": row.get("name"),
                    "hold_price": hold_price,
                    "hold_num": hold_num,
                    "latest_close": latest_close,
                    "latest_trade_date": row.get("latest_trade_date"),
                    "market_value": round(market_value, 2),
                    "cost_value": round(cost_value, 2),
                    "unrealized_pct": round(unrealized_pct, 2),
                    "hold_date": row.get("hold_date"),
                }
            )

        total_unrealized_pct = ((total_market_value / total_cost) - 1.0) * 100 if total_cost else 0.0
        avg_unrealized_pct = sum(unrealized_values) / len(unrealized_values) if unrealized_values else 0.0

        return {
            "count": len(normalized),
            "total_market_value": round(total_market_value, 2),
            "total_cost": round(total_cost, 2),
            "total_unrealized_pct": round(total_unrealized_pct, 2),
            "avg_unrealized_pct": round(avg_unrealized_pct, 2),
            "items": normalized,
        }

    def _build_recommendation_section(self) -> Dict[str, Any]:
        daily_rows = self._fetch_all(
            self.history_db_path,
            """
            SELECT recommendation_date, COUNT(*) AS count, AVG(recommendation_score) AS avg_score
            FROM recommendations
            GROUP BY recommendation_date
            ORDER BY recommendation_date DESC
            LIMIT 20
            """,
        )
        daily_rows = list(reversed(daily_rows))

        latest_date_row = self._fetch_one(
            self.history_db_path,
            "SELECT MAX(recommendation_date) AS latest_date FROM recommendations",
        )
        latest_date = (latest_date_row or {}).get("latest_date")

        latest_items = self._fetch_all(
            self.history_db_path,
            """
            SELECT symbol, name, recommendation_date, recommendation_score, recommendation_reason, strategy_type
            FROM recommendations
            WHERE recommendation_date = ?
            ORDER BY recommendation_score DESC, symbol
            LIMIT 12
            """,
            (latest_date,),
        ) if latest_date else []

        theme_rows = self._fetch_all(
            self.history_db_path,
            """
            SELECT COALESCE(strategy_type, '未分类') AS theme, COUNT(*) AS count
            FROM recommendations
            WHERE recommendation_date = (
                SELECT MAX(recommendation_date) FROM recommendations
            )
            GROUP BY COALESCE(strategy_type, '未分类')
            ORDER BY count DESC, theme
            LIMIT 8
            """,
        )

        return {
            "daily_count": len(daily_rows),
            "latest_date": latest_date,
            "latest_date_label": f"最近推荐日 {latest_date}" if latest_date else "暂无推荐记录",
            "trend": [
                {
                    "date": row.get("recommendation_date"),
                    "count": int(row.get("count") or 0),
                    "avg_score": round(float(row.get("avg_score") or 0), 2),
                }
                for row in daily_rows
            ],
            "latest_items": latest_items,
            "theme_distribution": [
                {"name": row.get("theme"), "value": int(row.get("count") or 0)}
                for row in theme_rows
            ],
        }

    def _build_feedback_section(self) -> Dict[str, Any]:
        latest_run = self._fetch_one(
            self.quant_db_path,
            """
            SELECT run_id, start_date, end_date, recommendation_count, signal_count,
                   detail_count, summary_count, meta_json, created_time
            FROM signal_feedback_run
            ORDER BY created_time DESC
            LIMIT 1
            """,
        )
        if not latest_run:
            return {
                "latest_run": None,
                "summary_rows": [],
                "chart": {"horizons": [], "series": []},
                "best_summary": None,
            }

        meta = self._safe_json_loads(latest_run.get("meta_json"))
        signal_meta = meta.get("signal_meta") or {}
        intraday_type_stats = signal_meta.get("signal_type_stats") or []
        intraday_window_stats = signal_meta.get("window_stats") or []
        intraday_insights = signal_meta.get("insights") or {}
        summaries = self._fetch_all(
            self.quant_db_path,
            """
            SELECT source_type, direction, horizon, sample_count, win_rate,
                   mean_gross_return, mean_net_return, median_net_return,
                   p25_net_return, p75_net_return, mean_mfe, mean_mae
            FROM signal_feedback_summary
            WHERE run_id = ?
            ORDER BY source_type, direction, horizon
            """,
            (latest_run["run_id"],),
        )

        horizons = sorted({int(row.get("horizon") or 0) for row in summaries})
        grouped: Dict[str, Dict[int, float]] = defaultdict(dict)
        best_summary = None
        best_score = None
        normalized_rows = []

        for row in summaries:
            label = self._compose_feedback_label(
                source_type=row.get("source_type"),
                direction=row.get("direction"),
            )
            mean_net_return_pct = round(self._ratio_to_percent(row.get("mean_net_return")), 2)
            grouped[label][int(row.get("horizon") or 0)] = mean_net_return_pct

            normalized = {
                "label": label,
                "source_type": row.get("source_type"),
                "direction": row.get("direction"),
                "horizon": int(row.get("horizon") or 0),
                "sample_count": int(row.get("sample_count") or 0),
                "win_rate_pct": round(self._ratio_to_percent(row.get("win_rate")), 2),
                "mean_net_return_pct": mean_net_return_pct,
                "mean_mfe_pct": round(self._ratio_to_percent(row.get("mean_mfe")), 2),
                "mean_mae_pct": round(self._ratio_to_percent(row.get("mean_mae")), 2),
            }
            normalized_rows.append(normalized)

            score = (normalized["mean_net_return_pct"], normalized["sample_count"])
            if best_score is None or score > best_score:
                best_score = score
                best_summary = normalized

        series = []
        for label, mapping in grouped.items():
            series.append(
                {
                    "name": label,
                    "values": [mapping.get(horizon, 0.0) for horizon in horizons],
                }
            )

        best_intraday_subtype = None
        if intraday_type_stats:
            ranked = sorted(
                intraday_type_stats,
                key=lambda item: (
                    float(item.get("mean_net_return", -999.0)),
                    int(item.get("sample_count", 0)),
                ),
                reverse=True,
            )
            top_item = ranked[0]
            best_intraday_subtype = {
                "signal_type": top_item.get("signal_type"),
                "direction": top_item.get("direction"),
                "horizon": int(top_item.get("horizon", 0) or 0),
                "sample_count": int(top_item.get("sample_count", 0) or 0),
                "win_rate_pct": round(self._ratio_to_percent(top_item.get("win_rate")), 2),
                "mean_net_return_pct": round(
                    self._ratio_to_percent(top_item.get("mean_net_return")), 2
                ),
            }

        return {
            "latest_run": {
                "run_id": latest_run.get("run_id"),
                "start_date": latest_run.get("start_date"),
                "end_date": latest_run.get("end_date"),
                "recommendation_count": int(latest_run.get("recommendation_count") or 0),
                "signal_count": int(latest_run.get("signal_count") or 0),
                "detail_count": int(latest_run.get("detail_count") or 0),
                "summary_count": int(latest_run.get("summary_count") or 0),
                "created_time": latest_run.get("created_time"),
                "meta": meta,
            },
            "summary_rows": normalized_rows,
            "chart": {
                "horizons": horizons,
                "series": series,
            },
            "intraday_type_rows": intraday_type_stats,
            "intraday_window_rows": intraday_window_stats,
            "intraday_insights": intraday_insights,
            "best_intraday_subtype": best_intraday_subtype,
            "best_summary": best_summary,
        }

    def _build_signal_section(self) -> Dict[str, Any]:
        latest_rows = self._fetch_all(
            self.quant_db_path,
            """
            SELECT ts_code, name, signal_type, signal_time, trigger_reason, suggestion
            FROM signal_history
            ORDER BY signal_time DESC
            LIMIT 12
            """,
        )
        type_rows = self._fetch_all(
            self.quant_db_path,
            """
            SELECT signal_type, COUNT(*) AS count
            FROM signal_history
            GROUP BY signal_type
            ORDER BY count DESC, signal_type
            LIMIT 8
            """,
        )
        daily_rows = self._fetch_all(
            self.quant_db_path,
            """
            SELECT substr(signal_time, 1, 10) AS day, COUNT(*) AS count
            FROM signal_history
            GROUP BY substr(signal_time, 1, 10)
            ORDER BY day DESC
            LIMIT 14
            """,
        )
        daily_rows = list(reversed(daily_rows))
        latest_signal = latest_rows[0] if latest_rows else None

        return {
            "recent_count": sum(int(row.get("count") or 0) for row in daily_rows),
            "latest_signal_label": (
                f"最近信号 {latest_signal.get('signal_type')} @ {latest_signal.get('signal_time')}"
                if latest_signal
                else "暂无最近信号"
            ),
            "latest_items": latest_rows,
            "type_distribution": [
                {"name": row.get("signal_type"), "value": int(row.get("count") or 0)}
                for row in type_rows
            ],
            "daily_trend": [
                {"date": row.get("day"), "count": int(row.get("count") or 0)}
                for row in daily_rows
            ],
        }

    def _build_health_section(self, now: datetime) -> Dict[str, Any]:
        latest_row = self._fetch_one(
            self.quant_db_path,
            """
            SELECT snapshot_time, source, uptime_seconds, success_total, incident_total,
                   severity_json, component_status_json, latency_summary_json, snapshot_json
            FROM health_snapshot
            WHERE source = 'service'
            ORDER BY snapshot_time DESC
            LIMIT 1
            """,
        )
        snapshot_rows = self._fetch_all(
            self.quant_db_path,
            """
            SELECT snapshot_time, success_total, incident_total
            FROM health_snapshot
            WHERE source = 'service'
            ORDER BY snapshot_time DESC
            LIMIT 40
            """,
        )
        snapshot_rows = list(reversed(snapshot_rows))
        incidents = self._fetch_all(
            self.quant_db_path,
            """
            SELECT incident_time, title, message, severity, category, component
            FROM runtime_incident
            ORDER BY incident_time DESC
            LIMIT 12
            """,
        )

        if not latest_row:
            return {
                "status": "unknown",
                "status_label": "暂无快照",
                "subtitle": "尚未写入 runtime health 数据",
                "tone": "slate",
                "latest_snapshot": None,
                "timeline": [],
                "recent_incidents": incidents,
                "components": [],
            }

        snapshot = self._safe_json_loads(latest_row.get("snapshot_json"))
        system_metrics = snapshot.get("system_metrics") or {}
        components = snapshot.get("component_status") or self._safe_json_loads(
            latest_row.get("component_status_json")
        )
        snapshot_time_str = latest_row.get("snapshot_time")
        age_seconds = self._age_seconds(snapshot_time_str, now)
        heartbeat_timeout = float(self.config.get("monitor.heartbeat_timeout_seconds", 600) or 600)

        status = "healthy"
        if age_seconds is None or age_seconds > heartbeat_timeout:
            status = "stale"
        elif any((item or {}).get("health") not in {"healthy", "ok"} for item in components.values()):
            status = "degraded"

        timeline = [
            {
                "time": row.get("snapshot_time"),
                "success_total": int(row.get("success_total") or 0),
                "incident_total": int(row.get("incident_total") or 0),
            }
            for row in snapshot_rows
        ]

        component_items = []
        for component, detail in sorted((components or {}).items()):
            component_items.append(
                {
                    "component": component,
                    "health": detail.get("health", "unknown"),
                    "last_seen": detail.get("last_seen"),
                    "lag_seconds": detail.get("lag_seconds"),
                    "details": detail.get("details") or {},
                }
            )

        return {
            "status": status,
            "status_label": {
                "healthy": "健康",
                "degraded": "有告警",
                "stale": "已停更",
                "unknown": "未知",
            }.get(status, "未知"),
            "age_seconds": int(age_seconds) if age_seconds is not None else None,
            "success_count": int(latest_row.get("success_total") or 0),
            "incident_count": int(latest_row.get("incident_total") or 0),
            "subtitle": (
                f"最后快照 {snapshot_time_str}，距今 {int(age_seconds)} 秒"
                if age_seconds is not None
                else "快照时间不可用"
            ),
            "tone": self.STATUS_COLORS.get(status, "slate"),
            "latest_snapshot": {
                "snapshot_time": snapshot_time_str,
                "success_total": int(latest_row.get("success_total") or 0),
                "incident_total": int(latest_row.get("incident_total") or 0),
                "uptime_seconds": float(latest_row.get("uptime_seconds") or 0),
            },
            "system_metrics": system_metrics,
            "timeline": timeline,
            "recent_incidents": incidents,
            "components": component_items,
        }

    def _build_market_session(self, now: datetime) -> Dict[str, Any]:
        clock = now.strftime("%H:%M")
        weekday = now.weekday()

        if weekday >= 5:
            phase = "休市"
            detail = "周末，市场未开盘"
        elif clock < "09:15":
            phase = "盘前"
            detail = "可查看候选池与执行计划"
        elif clock < "11:30":
            phase = "上午盘"
            detail = "适合观察开盘结构与早盘信号"
        elif clock < "13:00":
            phase = "午间休市"
            detail = "市场午间休市，适合复核信号"
        elif clock <= "15:00":
            phase = "下午盘"
            detail = "关注持仓管理与尾盘风险"
        else:
            phase = "盘后"
            detail = "适合复盘反馈、日报与参数回看"

        return {
            "phase": phase,
            "detail": detail,
            "clock": clock,
            "weekday": weekday,
        }

    def _compose_feedback_label(self, source_type: Optional[str], direction: Optional[str]) -> str:
        source_label = self.SOURCE_LABELS.get(source_type or "", source_type or "未知来源")
        direction_label = self.DIRECTION_LABELS.get(direction or "", direction or "未知方向")
        return f"{source_label}·{direction_label}"

    def _resolve_path(self, raw_path: str | Path) -> Path:
        path = Path(raw_path)
        if path.is_absolute():
            return path
        return self.project_root / path

    def _load_json(self, path: Path) -> Dict[str, Any]:
        if not path.exists():
            return {}
        try:
            with path.open("r", encoding="utf-8") as handle:
                return json.load(handle)
        except Exception as exc:
            logger.warning("Failed to load dashboard JSON %s: %s", path, exc)
            return {}

    def _fetch_one(
        self,
        db_path: Path,
        sql: str,
        params: tuple[Any, ...] = (),
    ) -> Optional[Dict[str, Any]]:
        rows = self._fetch_all(db_path=db_path, sql=sql, params=params, limit_one=True)
        return rows[0] if rows else None

    def _get_db_connection(self, db_path: Path) -> Optional[sqlite3.Connection]:
        """打开一个只读 WAL 模式连接，失败时返回 None。"""
        if not db_path.exists():
            return None
        try:
            conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            # 优化：提高缓存页数，减少磁盘 IO
            conn.execute("PRAGMA cache_size = -4096")
            conn.execute("PRAGMA temp_store = MEMORY")
            return conn
        except sqlite3.OperationalError:
            # 数据库文件不存在或不可读时回退到读写模式
            try:
                conn = sqlite3.connect(str(db_path), check_same_thread=False)
                conn.row_factory = sqlite3.Row
                return conn
            except sqlite3.Error as exc:
                logger.warning("Dashboard cannot open db %s: %s", db_path, exc)
                return None

    def _fetch_all(
        self,
        db_path: Path,
        sql: str,
        params: tuple[Any, ...] = (),
        limit_one: bool = False,
    ) -> List[Dict[str, Any]]:
        if not db_path.exists():
            return []

        conn: Optional[sqlite3.Connection] = None
        try:
            conn = self._get_db_connection(db_path)
            if conn is None:
                return []
            cursor = conn.execute(sql, params)
            rows = cursor.fetchall()
            if limit_one and rows:
                rows = rows[:1]
            return [dict(row) for row in rows]
        except sqlite3.Error as exc:
            logger.warning("Dashboard query failed on %s: %s", db_path, exc)
            return []
        finally:
            if conn is not None:
                conn.close()

    def _normalize_ts_code(self, value: Any) -> str:
        text = str(value or "").strip().upper()
        if not text:
            return ""
        if "." in text:
            return text
        if len(text) == 6 and text.isdigit():
            if text.startswith(("5", "6", "9")):
                return f"{text}.SH"
            if text.startswith(("0", "1", "2", "3")):
                return f"{text}.SZ"
            if text.startswith(("4", "8")):
                return f"{text}.BJ"
        return text

    def _load_latest_close_map(self, symbols: List[Any]) -> Dict[str, Dict[str, Any]]:
        ts_codes: List[str] = []
        for symbol in symbols:
            ts_code = self._normalize_ts_code(symbol)
            if ts_code:
                ts_codes.append(ts_code)
        ts_codes = list(dict.fromkeys(ts_codes))
        if not ts_codes:
            return {}

        placeholders = ",".join("?" for _ in ts_codes)
        rows = self._fetch_all(
            self.quant_db_path,
            f"""
            SELECT sd.ts_code, sd.close, sd.trade_date
            FROM stock_daily sd
            JOIN (
                SELECT ts_code, MAX(trade_date) AS latest_trade_date
                FROM stock_daily
                WHERE ts_code IN ({placeholders})
                GROUP BY ts_code
            ) latest
              ON sd.ts_code = latest.ts_code
             AND sd.trade_date = latest.latest_trade_date
            """,
            tuple(ts_codes),
        )
        return {
            str(row.get("ts_code") or "").upper(): {
                "close": row.get("close"),
                "trade_date": row.get("trade_date"),
            }
            for row in rows
            if row.get("ts_code")
        }

    def _load_latest_daily_quote_map(self, symbols: List[Any]) -> Dict[str, Dict[str, Any]]:
        ts_codes: List[str] = []
        for symbol in symbols:
            ts_code = self._normalize_ts_code(symbol)
            if ts_code:
                ts_codes.append(ts_code)
        ts_codes = list(dict.fromkeys(ts_codes))
        if not ts_codes:
            return {}

        placeholders = ",".join("?" for _ in ts_codes)
        rows = self._fetch_all(
            self.quant_db_path,
            f"""
            SELECT sd.ts_code, sd.close, sd.pct_chg, sd.trade_date
            FROM stock_daily sd
            JOIN (
                SELECT ts_code, MAX(trade_date) AS latest_trade_date
                FROM stock_daily
                WHERE ts_code IN ({placeholders})
                GROUP BY ts_code
            ) latest
              ON sd.ts_code = latest.ts_code
             AND sd.trade_date = latest.latest_trade_date
            """,
            tuple(ts_codes),
        )
        return {
            str(row.get("ts_code") or "").upper(): {
                "close": row.get("close"),
                "pct_chg": row.get("pct_chg"),
                "trade_date": row.get("trade_date"),
            }
            for row in rows
            if row.get("ts_code")
        }

    def _ratio_to_percent(self, value: Any) -> float:
        """将比例值（如 0.15）转换为百分比（15.0）。
        
        判断规则：
        - 若绝对值 <= 2.0，认为是比例形式（0.15 -> 15.0）
        - 否则认为已经是百分比形式（15.0 -> 15.0）
        
        注意：此启发式对极端值（如 +200% 涨幅）不适用，
        调用方应确保数据来源一致。
        """
        if value is None:
            return 0.0
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return 0.0
        return numeric * 100 if abs(numeric) <= 2.0 else numeric

    def _safe_json_loads(self, payload: Any) -> Dict[str, Any]:
        if isinstance(payload, dict):
            return payload
        if not payload:
            return {}
        try:
            return json.loads(payload)
        except Exception:
            return {}

    def _age_seconds(self, snapshot_time: Optional[str], now: datetime) -> Optional[float]:
        if not snapshot_time:
            return None
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S"):
            try:
                parsed = datetime.strptime(snapshot_time, fmt)
                return max((now - parsed).total_seconds(), 0.0)
            except ValueError:
                continue
        return None
