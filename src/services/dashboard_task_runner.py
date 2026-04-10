from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from src.core.config import ConfigManager
from src.core.database import DatabaseManager
from src.core.logger import get_logger
from src.modules.auto_push_manager import AutoPushManager
from src.modules.breakout_selector_menu import merge_breakout_watchlist_to_candidate_cache
from src.modules.breakout_strategy import BreakoutParams, BreakoutStrategy
from src.modules.daily_report import DailyReportGenerator
from src.modules.secondary_launch_menu import SecondaryLaunchMenu
from src.modules.data_updater import DataUpdater
from src.modules.strong_start_selector_menu import merge_strong_start_candidates_to_candidate_cache
from src.modules.strong_start_strategy import StrongStartParams, StrongStartStrategy
from src.services.dashboard_action_record_service import DashboardActionRecordService
from src.services.dashboard_process_manager import DashboardProcessManager

logger = get_logger("dashboard_task_runner")


class DashboardTaskRunner:
    """统一管理 Web 面板的后台任务。"""

    def __init__(
        self,
        config: Optional[ConfigManager] = None,
        db: Optional[DatabaseManager] = None,
        project_root: Optional[str | Path] = None,
        process_manager: Optional[DashboardProcessManager] = None,
    ):
        self.config = config or ConfigManager()
        self.db = db or DatabaseManager(self.config)
        self.project_root = Path(project_root or Path(__file__).resolve().parents[2])
        self.state_path = self.project_root / "data" / "cache" / "web_background_tasks.json"
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self.action_record_service = DashboardActionRecordService(self.config, self.db)
        self.process_manager = process_manager or DashboardProcessManager(project_root=self.project_root)
        self.data_updater = DataUpdater(self.config, self.db)
        self.daily_report = DailyReportGenerator(self.config, self.db)
        self.auto_push = AutoPushManager(self.config, self.db)
        self.secondary_launch = SecondaryLaunchMenu(self.config, self.db)

    def list_tasks(self, limit: int = 20) -> list[Dict[str, Any]]:
        rows = list(self._load_state().get("tasks", []))
        process_state = self.process_manager.get_process(DashboardProcessManager.PROCESS_KEY_MONITOR)
        if process_state:
            rows.insert(
                0,
                {
                    "task_id": "process_monitor_runtime",
                    "task_type": "process",
                    "action_key": "start_monitor_runtime",
                    "action_label": "实时监控服务",
                    "status": process_state.get("status", "unknown"),
                    "message": process_state.get("log_path", ""),
                    "started_at": process_state.get("started_at"),
                    "updated_at": process_state.get("updated_at"),
                    "payload": process_state,
                },
            )
        return rows[: int(limit)]

    def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        state = self._load_state()
        for row in state.get("tasks", []):
            if str(row.get("task_id") or "") == str(task_id or ""):
                return dict(row)
        return None

    def submit_background_task(
        self,
        action_key: str,
        action_label: str,
        target: Callable[[], Dict[str, Any]],
    ) -> Dict[str, Any]:
        task_id = uuid.uuid4().hex[:12]
        row = {
            "task_id": task_id,
            "task_type": "thread",
            "action_key": action_key,
            "action_label": action_label,
            "status": "queued",
            "message": "任务已提交，等待执行。",
            "started_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "ended_at": None,
            "payload": {},
        }
        self._upsert_task(row)

        thread = threading.Thread(
            target=self._run_task_thread,
            args=(task_id, action_key, target),
            daemon=True,
            name=f"dashboard-task-{task_id}",
        )
        thread.start()
        return row

    def start_monitor_runtime(self) -> Dict[str, Any]:
        return self.process_manager.start_monitor_runtime()

    def stop_monitor_runtime(self) -> Dict[str, Any]:
        return self.process_manager.stop_monitor_runtime()

    def run_update_stock_data(self) -> Dict[str, Any]:
        return self.submit_background_task(
            action_key="update_stock_data",
            action_label="更新股票数据",
            target=self._run_update_stock_data_task,
        )

    def run_startup_market_data_sync(self) -> Dict[str, Any]:
        return self.submit_background_task(
            action_key="startup_market_data_sync",
            action_label="启动校验市场数据",
            target=self._run_startup_market_data_sync_task,
        )

    def run_stock_selection(self, strategy: str = "secondary_launch") -> Dict[str, Any]:
        def _task() -> Dict[str, Any]:
            self.auto_push.invalidate_push_cache()
            report = self.daily_report.generate_report(skip_data_update=True)
            trade_date = (
                report.get("secondary_launch_meta", {}).get("selection_end_date")
                if isinstance(report.get("secondary_launch_meta"), dict)
                else None
            ) or self.db.get_latest_trade_date("stock_daily")
            strategy_key = str(strategy or "secondary_launch").strip().lower()
            secondary = list(report.get("secondary_launch_selection") or [])
            legacy = list(report.get("stock_selection") or [])
            selected_count = 0
            sync_count = 0

            if strategy_key in {"secondary_launch", "secondary"}:
                selected_count = len(secondary)
                if trade_date and secondary:
                    sync_count = self.secondary_launch.sync_to_candidate_pool(
                        trade_date=trade_date,
                        selections=secondary,
                    )
            elif strategy_key == "legacy":
                selected_count = len(legacy)
                if trade_date and legacy:
                    sync_count = self._sync_legacy_to_candidate_pool(
                        trade_date=trade_date,
                        selections=legacy,
                    )
            elif strategy_key == "both":
                selected_count = len(secondary) + len(legacy)
                if trade_date:
                    sync_count = self._sync_combined_to_candidate_pool(
                        trade_date=trade_date,
                        secondary=secondary,
                        legacy=legacy,
                    )
            elif strategy_key == "breakout":
                selected_count, sync_count, trade_date = self._run_breakout_selection(trade_date)
            elif strategy_key == "strong_start":
                selected_count, sync_count, trade_date = self._run_strong_start_selection(trade_date)
            else:
                raise ValueError(f"Unsupported stock selection strategy: {strategy_key}")
            return {
                "selected_count": selected_count,
                "sync_count": sync_count,
                "trade_date": trade_date,
                "strategy": strategy_key,
            }

        return self.submit_background_task(
            action_key="run_stock_selection",
            action_label="执行今日选股",
            target=_task,
        )

    def _sync_legacy_to_candidate_pool(self, trade_date: str, selections: list[dict]) -> int:
        if not trade_date or not selections:
            return 0
        candidates = []
        for row in selections:
            symbol_raw = str(row.get("ts_code") or row.get("symbol") or row.get("code") or "").strip()
            if not symbol_raw:
                continue
            symbol = symbol_raw.split(".")[0]
            score = row.get("total_score", row.get("signal_score", row.get("score", 0.0)))
            try:
                score_value = float(score or 0.0)
            except Exception:
                score_value = 0.0
            candidates.append(
                {
                    "symbol": symbol,
                    "name": str(row.get("name") or ""),
                    "score": score_value,
                    "level": str(row.get("recommendation_level") or "原策略候选"),
                    "industry": str(row.get("industry") or "未知"),
                    "pool_type": "core",
                    "strategy_profile": "legacy",
                    "strategy_name": str(row.get("strategy_name") or "legacy"),
                    "source": "daily_report_legacy",
                    "trade_date": str(trade_date),
                }
            )
        return self._write_candidate_pool_cache(trade_date=trade_date, candidates=candidates)

    def _sync_combined_to_candidate_pool(self, trade_date: str, secondary: list[dict], legacy: list[dict]) -> int:
        merged: Dict[str, Dict[str, Any]] = {}
        for row in secondary or []:
            ts_code = str(row.get("ts_code", "") or "").strip()
            if not ts_code:
                continue
            symbol = ts_code.split(".")[0]
            merged[symbol] = {
                "symbol": symbol,
                "name": str(row.get("name", "") or ""),
                "score": float(row.get("signal_score", row.get("total_score", 0.0)) or 0.0),
                "level": str(row.get("level", "二次启动候选") or "二次启动候选"),
                "industry": str(row.get("industry", "未知") or "未知"),
                "pool_type": "core",
                "strategy_profile": "secondary_launch",
                "strategy_name": str(row.get("strategy_name", "secondary_launch_walkforward")),
                "source": "secondary_launch_menu",
                "trade_date": str(trade_date),
            }
        for row in legacy or []:
            symbol_raw = str(row.get("ts_code") or row.get("symbol") or row.get("code") or "").strip()
            if not symbol_raw:
                continue
            symbol = symbol_raw.split(".")[0]
            score = row.get("total_score", row.get("signal_score", row.get("score", 0.0)))
            try:
                score_value = float(score or 0.0)
            except Exception:
                score_value = 0.0
            current = merged.get(symbol)
            if current and float(current.get("score", 0.0) or 0.0) >= score_value:
                continue
            merged[symbol] = {
                "symbol": symbol,
                "name": str(row.get("name") or ""),
                "score": score_value,
                "level": str(row.get("recommendation_level") or "原策略候选"),
                "industry": str(row.get("industry") or "未知"),
                "pool_type": "core",
                "strategy_profile": "legacy",
                "strategy_name": str(row.get("strategy_name") or "legacy"),
                "source": "daily_report_legacy",
                "trade_date": str(trade_date),
            }
        return self._write_candidate_pool_cache(trade_date=trade_date, candidates=list(merged.values()))

    def _write_candidate_pool_cache(self, trade_date: str, candidates: list[dict]) -> int:
        payload = {
            "date": str(trade_date),
            "candidates": candidates,
            "created_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        cache_path = self.project_root / "data" / "cache" / "candidate_pool.json"
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return len(candidates)

    def _run_breakout_selection(self, trade_date: str | None) -> tuple[int, int, str | None]:
        params = BreakoutParams()
        params.min_amt_ma20 = 8e4
        params.rs_quantile_max = 0.97
        params.min_signal_score = 60.0
        params.top_k = 15
        strategy = BreakoutStrategy(db=self.db, params=params)
        watch_items = strategy.run(end_date=trade_date) if trade_date else strategy.run()
        watch_date = (
            watch_items[0].watch_date
            if watch_items
            else (str(trade_date) if trade_date else datetime.now().strftime("%Y%m%d"))
        )
        sync_count = merge_breakout_watchlist_to_candidate_cache(
            watch_items=watch_items,
            watch_date=watch_date,
            project_root=self.project_root,
        )
        return len(watch_items), int(sync_count), watch_date

    def _run_strong_start_selection(self, trade_date: str | None) -> tuple[int, int, str | None]:
        resolved_trade_date = str(trade_date or self.db.get_latest_trade_date("stock_daily") or "").strip()
        if resolved_trade_date:
            self.data_updater.sync_chip_perf_with_latest_data(reference_trade_date=resolved_trade_date)

        params = StrongStartParams.tradeable_v2()
        strategy = StrongStartStrategy(db=self.db, params=params)
        candidates = strategy.run(end_date=resolved_trade_date) if resolved_trade_date else strategy.run()
        watch_date = (
            candidates[0].watch_date
            if candidates
            else (resolved_trade_date or datetime.now().strftime("%Y%m%d"))
        )
        sync_count = merge_strong_start_candidates_to_candidate_cache(
            candidates=candidates,
            trade_date=watch_date,
            project_root=self.project_root,
        )
        return len(candidates), int(sync_count), watch_date

    def run_push_selection_wecom(self, strategy: str = "secondary_launch") -> Dict[str, Any]:
        return self.submit_background_task(
            action_key="push_selection_wecom",
            action_label="推送选股到企业微信",
            target=lambda: {
                "push_ok": bool(self.auto_push.push_pre_market_selection(strategy=strategy)),
                "strategy": strategy,
            },
        )

    def run_push_review_wecom(self, strategy: str = "secondary_launch") -> Dict[str, Any]:
        return self.submit_background_task(
            action_key="push_review_wecom",
            action_label="推送复盘到企业微信",
            target=lambda: {
                "push_ok": bool(self.auto_push.push_post_market_summary(strategy=strategy)),
                "strategy": strategy,
            },
        )

    def clear_candidate_pool(self) -> Dict[str, Any]:
        self.auto_push.invalidate_push_cache()
        deleted_rows = 0
        cache_path = self.project_root / "data" / "cache" / "candidate_pool.json"
        if cache_path.exists():
            cache_path.write_text(
                json.dumps(
                    {
                        "date": datetime.now().strftime("%Y%m%d"),
                        "candidates": [],
                        "created_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
        try:
            if self.db.query_one(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='candidate_pool'"
            ):
                deleted_rows = self.db.execute("DELETE FROM candidate_pool")
        except Exception as exc:
            logger.warning("清理 candidate_pool 表失败: %s", exc)
        return {"deleted_rows": int(deleted_rows), "cache_path": str(cache_path)}

    def clear_history_records(self) -> Dict[str, Any]:
        self.auto_push.invalidate_push_cache()
        history_db_path = self.project_root / self.config.get(
            "feedback.history_recommendation_db",
            "data/history_recommendation.db",
        )
        counts: Dict[str, int] = {}
        if history_db_path.exists():
            conn = sqlite3.connect(str(history_db_path))
            try:
                cursor = conn.cursor()
                for table_name in ["recommendations", "signal_feedback_run", "signal_feedback_summary", "signal_feedback_detail"]:
                    if cursor.execute(
                        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                        (table_name,),
                    ).fetchone():
                        cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
                        counts[table_name] = int(cursor.fetchone()[0] or 0)
                        cursor.execute(f"DELETE FROM {table_name}")
                conn.commit()
            finally:
                conn.close()

        main_counts = 0
        try:
            if self.db.query_one(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='secondary_launch_selection_history'"
            ):
                row = self.db.query_one("SELECT COUNT(*) AS cnt FROM secondary_launch_selection_history")
                main_counts = int((row or {}).get("cnt") or 0)
                self.db.execute("DELETE FROM secondary_launch_selection_history")
        except Exception as exc:
            logger.warning("清理二次启动历史失败: %s", exc)
        counts["secondary_launch_selection_history"] = main_counts
        counts["total_deleted"] = sum(counts.values())
        return counts

    def clear_virtual_trades(self) -> Dict[str, Any]:
        self.auto_push.invalidate_push_cache()
        filepath = self.project_root / "data" / "cache" / "virtual_trades.json"
        old_counts = {"open_count": 0, "closed_count": 0}
        if filepath.exists():
            try:
                payload = json.loads(filepath.read_text(encoding="utf-8"))
                old_counts["open_count"] = len(payload.get("open_trades") or [])
                old_counts["closed_count"] = len(payload.get("closed_trades") or [])
            except Exception:
                pass
        filepath.write_text(
            json.dumps(
                {
                    "config": {},
                    "open_trades": [],
                    "closed_trades": [],
                    "statistics": {},
                    "save_time": datetime.now().isoformat(),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return {"filepath": str(filepath), **old_counts}

    def _run_task_thread(self, task_id: str, action_key: str, target: Callable[[], Dict[str, Any]]) -> None:
        self._update_task(task_id, status="running", message="任务执行中，请稍候。")
        try:
            result = target() or {}
            message = self._build_task_message(result)
            self._update_task(
                task_id,
                status="success",
                message=message,
                payload=result,
                ended_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            )
            self.action_record_service.record(
                action_key=action_key,
                status="success",
                message=message,
                payload=result,
            )
        except Exception as exc:
            logger.exception("后台任务执行失败")
            self._update_task(
                task_id,
                status="failed",
                message=str(exc),
                payload={},
                ended_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            )
            self.action_record_service.record(
                action_key=action_key,
                status="failed",
                message=str(exc),
                payload={},
            )

    def _build_task_message(self, payload: Dict[str, Any]) -> str:
        if payload.get("message"):
            return str(payload.get("message"))
        if "selected_count" in payload:
            return f"选股完成，产出 {int(payload.get('selected_count', 0) or 0)} 只。"
        if "daily_data_count" in payload:
            return (
                f"数据更新完成，日线 {int(payload.get('daily_data_count', 0) or 0)} 条，"
                f"指数 {int(payload.get('index_data_count', 0) or 0)} 条。"
            )
        if "push_ok" in payload:
            return "企业微信推送完成。" if payload.get("push_ok") else "企业微信推送失败。"
        return "任务执行完成。"

    def _run_update_stock_data_task(self) -> Dict[str, Any]:
        self.auto_push.invalidate_push_cache()
        return self.data_updater.run_full_update()

    def _run_startup_market_data_sync_task(self) -> Dict[str, Any]:
        self.auto_push.invalidate_push_cache()
        return self.data_updater.ensure_latest_market_data()

    def _load_state(self) -> Dict[str, Any]:
        if not self.state_path.exists():
            return {"tasks": []}
        try:
            return json.loads(self.state_path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("读取任务状态失败: %s", exc)
            return {"tasks": []}

    def _save_state(self, state: Dict[str, Any]) -> None:
        self.state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

    def _upsert_task(self, row: Dict[str, Any]) -> None:
        with self._lock:
            state = self._load_state()
            tasks = [task for task in state.get("tasks", []) if task.get("task_id") != row.get("task_id")]
            tasks.insert(0, row)
            state["tasks"] = tasks[:50]
            self._save_state(state)

    def _update_task(self, task_id: str, **fields: Any) -> None:
        with self._lock:
            state = self._load_state()
            tasks = state.get("tasks", [])
            for row in tasks:
                if row.get("task_id") == task_id:
                    row.update(fields)
                    row["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    break
            state["tasks"] = tasks
            self._save_state(state)
