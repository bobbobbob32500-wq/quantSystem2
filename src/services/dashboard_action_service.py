from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from src.core.config import ConfigManager
from src.core.database import DatabaseManager
from src.core.logger import get_logger
from src.modules.daily_report import DailyReportGenerator
from src.modules.monitoring_store import MonitoringStore
from src.services.dashboard_action_record_service import DashboardActionRecordService
from src.services.dashboard_process_manager import DashboardProcessManager
from src.services.dashboard_task_runner import DashboardTaskRunner
from src.services.monitor_session_service import MonitorSessionService
from src.services.stock_service import HoldStockService
from src.services.terminal_runtime_service import TerminalRuntimeService

logger = get_logger("dashboard_action_service")


class DashboardActionService:
    """看板动作服务：把页面按钮映射到可执行后端动作。"""

    def __init__(
        self,
        config: Optional[ConfigManager] = None,
        db: Optional[DatabaseManager] = None,
        task_runner: Optional[DashboardTaskRunner] = None,
        process_manager: Optional[DashboardProcessManager] = None,
        terminals_directory: Optional[str | Path] = None,
    ):
        self.config = config or ConfigManager()
        self.db = db or DatabaseManager(self.config)
        self.project_root = Path(__file__).resolve().parents[2]
        self.daily_report = DailyReportGenerator(self.config, self.db)
        self.monitor_session = MonitorSessionService(self.config)
        self.monitoring_store = MonitoringStore(self.db)
        self.action_record_service = DashboardActionRecordService(self.config, self.db)
        self.process_manager = process_manager or DashboardProcessManager(project_root=self.project_root)
        self.task_runner = task_runner or DashboardTaskRunner(
            config=self.config,
            db=self.db,
            project_root=self.project_root,
            process_manager=self.process_manager,
        )
        self.hold_service = HoldStockService(self.config, self.db)
        self.terminal_runtime = TerminalRuntimeService(
            terminals_directory=terminals_directory or self._resolve_terminals_directory(),
        )

    def execute(
        self,
        action: str,
        payload: Optional[Dict[str, Any]] = None,
        confirmed: bool = False,
    ) -> Dict[str, Any]:
        action_key = str(action or "").strip()
        payload = payload or {}
        try:
            if action_key == "generate_plan":
                result = self._submit_generate_plan()
            elif action_key == "enter_stage":
                result = self._enter_current_stage()
            elif action_key == "start_intraday_watch":
                result = self._start_intraday_watch()
            elif action_key == "start_monitor_runtime":
                result = self._start_monitor_runtime()
            elif action_key == "stop_monitor_runtime":
                result = self._stop_monitor_runtime()
            elif action_key == "generate_post_market_review":
                result = self._submit_generate_post_market_review()
            elif action_key == "refresh_intraday_status":
                result = self._refresh_intraday_status()
            elif action_key == "update_stock_data":
                result = self._update_stock_data()
            elif action_key == "run_stock_selection":
                result = self._run_stock_selection(payload)
            elif action_key == "export_diagnostic_bundle":
                result = self._export_diagnostic_bundle()
            elif action_key == "push_selection_wecom":
                result = self._push_selection_wecom(payload)
            elif action_key == "push_review_wecom":
                result = self._push_review_wecom(payload)
            elif action_key == "retry_push_outbox":
                result = self._retry_push_outbox()
            elif action_key == "update_holding":
                result = self._update_holding(payload)
            elif action_key == "remove_holding":
                result = self._remove_holding(payload, confirmed=confirmed)
            elif action_key == "clear_candidate_pool":
                result = self._clear_candidate_pool(confirmed=confirmed)
            elif action_key == "clear_history_records":
                result = self._clear_history_records(confirmed=confirmed)
            elif action_key == "clear_virtual_trades":
                result = self._clear_virtual_trades(confirmed=confirmed)
            else:
                raise ValueError(f"不支持的动作: {action_key}")
            self.action_record_service.record(
                action_key=action_key,
                status="success",
                message=result.get("message", ""),
                payload={
                    "task_id": result.get("task_id"),
                    "payload": result.get("payload", {}),
                },
            )
            return result
        except Exception as exc:
            self.action_record_service.record(
                action_key=action_key or "unknown",
                status="failed",
                message=str(exc),
                payload={},
            )
            raise

    def retry_background_task(self, task_id: str) -> Dict[str, Any]:
        task = self.task_runner.get_task(task_id)
        if not task:
            raise LookupError("任务不存在")
        action_key = str(task.get("action_key") or "").strip()
        if not action_key:
            raise ValueError("任务缺少 action_key，无法重试")
        payload = task.get("payload") if isinstance(task.get("payload"), dict) else {}
        strategy = str(payload.get("strategy") or "secondary_launch")

        if action_key == "generate_plan":
            return self._submit_generate_plan()
        if action_key == "generate_post_market_review":
            return self._submit_generate_post_market_review()
        if action_key == "run_stock_selection":
            return self._run_stock_selection({"strategy": strategy})
        if action_key == "update_stock_data":
            return self._update_stock_data()
        if action_key == "push_selection_wecom":
            return self._push_selection_wecom({"strategy": strategy})
        if action_key == "push_review_wecom":
            return self._push_review_wecom({"strategy": strategy})
        raise ValueError(f"当前任务类型暂不支持重试: {action_key}")

    def _retry_push_outbox(self) -> Dict[str, Any]:
        """
        重试通用推送 Outbox。
        """
        from src.modules.auto_push_manager import AutoPushManager

        manager = AutoPushManager(self.config, self.db)
        ok = bool(manager.retry_push_outbox())
        return {
            "success": True,
            "action": "retry_push_outbox",
            "message": "推送队列已触发重试。" if ok else "已触发重试，但本轮可能无可重试消息或部分仍失败。",
            "payload": {
                "stage_target": "todayBoardSection",
                "result": "ok" if ok else "partial",
                "triggered_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            },
        }

    def _export_diagnostic_bundle(self) -> Dict[str, Any]:
        """
        导出诊断包（zip），用于实盘问题定位与留档。
        内容包含：
        - 近几日日志（logs/quant_system_*.log）
        - 近24小时 health_snapshot/runtime_incident 摘要
        - push_outbox 统计
        - 脱敏后的 src/config/config.yaml（不含 token/webhook）
        """
        import zipfile

        now = datetime.now()
        stamp = now.strftime("%Y%m%d_%H%M%S")
        results_dir = self.project_root / "results"
        results_dir.mkdir(parents=True, exist_ok=True)
        bundle_path = results_dir / f"diagnostic_bundle_{stamp}.zip"

        def _safe_add(zf: zipfile.ZipFile, path: Path, arcname: str):
            try:
                if path.exists() and path.is_file():
                    zf.write(path, arcname=arcname)
            except Exception:
                pass

        def _redact_config(text: str) -> str:
            # 只做最小脱敏：覆盖 token/webhook
            lines = []
            for line in (text or "").splitlines():
                s = line.strip()
                if s.startswith("tushare_token:"):
                    lines.append("  tushare_token: \"\"")
                    continue
                if s.startswith("wechat_webhook:"):
                    lines.append("  wechat_webhook: \"\"")
                    continue
                if s.startswith("position_wechat_webhook:"):
                    lines.append("  position_wechat_webhook: \"\"")
                    continue
                lines.append(line)
            return "\n".join(lines) + "\n"

        # 1) 组装摘要 JSON
        summary: Dict[str, Any] = {
            "generated_at": now.strftime("%Y-%m-%d %H:%M:%S"),
            "project_root": str(self.project_root),
            "quant_db_path": str(self.config.get("database.path", "data/database/quant_system.db")),
            "monitor_snapshot": {},
            "outbox": {},
        }
        try:
            latest = self.monitoring_store.get_latest_snapshot(source="service") or {}
            recent_incidents = self.monitoring_store.get_recent_incidents(limit=30) or []
            summary["monitor_snapshot"] = {
                "latest_snapshot_time": latest.get("snapshot_time"),
                "latest_uptime_seconds": latest.get("uptime_seconds"),
                "latest_success_total": latest.get("success_total"),
                "latest_incident_total": latest.get("incident_total"),
                "latest_system_metrics": (latest.get("snapshot") or {}).get("system_metrics", {}),
                "recent_incidents": recent_incidents,
            }
        except Exception as exc:
            summary["monitor_snapshot"] = {"error": str(exc)}

        try:
            row = self.db.query_one(
                """
                SELECT
                    SUM(CASE WHEN status IN ('pending') THEN 1 ELSE 0 END) AS pending_count,
                    SUM(CASE WHEN status IN ('failed') THEN 1 ELSE 0 END) AS failed_count,
                    SUM(CASE WHEN status IN ('success') THEN 1 ELSE 0 END) AS success_count
                FROM push_outbox
                """
            )
            if row:
                summary["outbox"] = {
                    "pending": int(row.get("pending_count") or 0),
                    "failed": int(row.get("failed_count") or 0),
                    "success": int(row.get("success_count") or 0),
                }
        except Exception as exc:
            summary["outbox"] = {"error": str(exc)}

        summary_bytes = json.dumps(summary, ensure_ascii=False, indent=2).encode("utf-8")

        # 2) 写入 zip
        logs_dir = self.project_root / "logs"
        config_path = self.project_root / "src" / "config" / "config.yaml"
        with zipfile.ZipFile(bundle_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            # 摘要
            zf.writestr("summary.json", summary_bytes)

            # 脱敏配置
            try:
                raw_cfg = config_path.read_text(encoding="utf-8")
                zf.writestr("config_redacted.yaml", _redact_config(raw_cfg).encode("utf-8"))
            except Exception:
                pass

            # 最近日志（最多取 5 个）
            try:
                if logs_dir.exists():
                    candidates = sorted(
                        [p for p in logs_dir.glob("quant_system_*.log") if p.is_file()],
                        key=lambda p: p.stat().st_mtime,
                        reverse=True,
                    )[:5]
                    for p in candidates:
                        _safe_add(zf, p, f"logs/{p.name}")
            except Exception:
                pass

        return {
            "success": True,
            "action": "export_diagnostic_bundle",
            "message": f"诊断包已生成：{bundle_path.name}",
            "payload": {
                "stage_target": "todayBoardSection",
                "bundle_file": bundle_path.name,
                "bundle_path": str(bundle_path),
                "generated_at": now.strftime("%Y-%m-%d %H:%M:%S"),
            },
        }

    def _generate_plan(self) -> Dict[str, Any]:
        report = self.daily_report.generate_report(skip_data_update=True)
        secondary = list(report.get("secondary_launch_selection") or [])
        market = report.get("market_analysis") or {}
        target_position = float(market.get("target_position", 0.0) or 0.0)
        return {
            "success": True,
            "action": "generate_plan",
            "message": (
                f"今日计划已生成，当前二次启动候选 {len(secondary)} 只，"
                f"建议仓位 {target_position * 100:.0f}%。"
            ),
            "payload": {
                "stage_target": "preMarketSection",
                "recommended_count": len(secondary),
                "position_pct": round(target_position * 100, 2),
                "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            },
        }

    def _submit_generate_plan(self) -> Dict[str, Any]:
        task = self.task_runner.submit_background_task(
            action_key="generate_plan",
            action_label="生成今日计划",
            target=self._generate_plan,
        )
        return {
            "success": True,
            "action": "generate_plan",
            "task_id": task.get("task_id"),
            "message": "生成计划任务已提交，正在后台执行，请稍后在历史记录查看结果。",
            "payload": {
                "stage_target": "preMarketSection",
                "task": task,
            },
        }

    def _enter_current_stage(self) -> Dict[str, Any]:
        now = datetime.now()
        clock = now.strftime("%H:%M")
        weekday = now.weekday()
        if weekday >= 5:
            stage = "postMarketSection"
            label = "盘后"
        elif clock < "09:15":
            stage = "preMarketSection"
            label = "盘前"
        elif clock <= "15:00":
            stage = "intradaySection"
            label = "盘中"
        else:
            stage = "postMarketSection"
            label = "盘后"
        return {
            "success": True,
            "action": "enter_stage",
            "message": f"已定位到当前阶段：{label}。",
            "payload": {
                "stage_target": stage,
                "stage_label": label,
            },
        }

    def _start_intraday_watch(self) -> Dict[str, Any]:
        session = self.monitor_session.start_session(source="dashboard")
        runtime_state = self._get_runtime_state()
        message = "已进入盘中盯盘状态，接下来只关注候选观察池和触发信号。"
        if not runtime_state["runtime_online"]:
            message = (
                "已进入盘中盯盘状态，但当前未检测到实时监控在线。"
                "请确保 `main.py` 或 `run_service.py` 正在运行。"
            )
        elif not runtime_state["runtime_usable"]:
            if str(runtime_state.get("status_label") or "") == "候选池为空":
                message = (
                    "已进入盘中盯盘状态，但候选池为空。"
                    "你仍可以查看最近信号与实时行情用于盯盘，但建议尽快运行选股/生成盘前计划补齐候选池。"
                )
            else:
                message = f"已进入盘中盯盘状态，但当前监控可用性不足：{runtime_state['status_label']}。"
        return {
            "success": True,
            "action": "start_intraday_watch",
            "message": message,
            "payload": {
                "stage_target": "intradaySection",
                "watch_mode": "intraday",
                "monitor_session": session,
                "runtime_state": runtime_state,
            },
        }

    def _start_monitor_runtime(self) -> Dict[str, Any]:
        process_result = self.task_runner.start_monitor_runtime()
        self.monitor_session.start_session(source="dashboard")
        return {
            "success": True,
            "action": "start_monitor_runtime",
            "message": str(process_result.get("message") or "监控服务已启动。"),
            "payload": {
                "stage_target": "intradaySection",
                "process": process_result.get("process"),
            },
        }

    def _stop_monitor_runtime(self) -> Dict[str, Any]:
        process_result = self.task_runner.stop_monitor_runtime()
        return {
            "success": True,
            "action": "stop_monitor_runtime",
            "message": str(process_result.get("message") or "监控服务已停止。"),
            "payload": {
                "stage_target": "intradaySection",
                "process": process_result.get("process"),
            },
        }

    def _generate_post_market_review(self) -> Dict[str, Any]:
        report = self.daily_report.generate_report(skip_data_update=True)
        intraday_review = list(report.get("secondary_launch_intraday_review") or [])
        triggered_count = sum(1 for item in intraday_review if item.get("has_buy_signal"))
        blockers = [
            str(item.get("not_pushed_reason", "") or "").strip()
            for item in intraday_review
            if not item.get("has_buy_signal")
        ]
        return {
            "success": True,
            "action": "generate_post_market_review",
            "message": (
                f"今日复盘已生成，推荐 {len(report.get('secondary_launch_selection') or [])} 只，"
                f"触发 {triggered_count} 只。"
            ),
            "payload": {
                "stage_target": "postMarketSection",
                "triggered_count": triggered_count,
                "top_block_reason": blockers[0] if blockers else "暂无明显阻塞项",
                "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            },
        }

    def _submit_generate_post_market_review(self) -> Dict[str, Any]:
        task = self.task_runner.submit_background_task(
            action_key="generate_post_market_review",
            action_label="生成收盘复盘",
            target=self._generate_post_market_review,
        )
        return {
            "success": True,
            "action": "generate_post_market_review",
            "task_id": task.get("task_id"),
            "message": "收盘复盘任务已提交，正在后台执行，请稍后在历史记录查看结果。",
            "payload": {
                "stage_target": "postMarketSection",
                "task": task,
            },
        }

    def _refresh_intraday_status(self) -> Dict[str, Any]:
        session = self.monitor_session.refresh_session()
        runtime_state = self._get_runtime_state()
        message = "盘中状态已刷新，请优先看顶部结论和信号卡片。"
        if runtime_state["runtime_online"] and runtime_state["runtime_usable"]:
            message = "盘中状态已刷新，实时监控在线且可用。"
        elif runtime_state["runtime_online"]:
            if str(runtime_state.get("status_label") or "") == "候选池为空":
                message = (
                    "盘中状态已刷新，当前候选池为空。"
                    "你仍可以查看最近信号与实时行情用于盯盘，但建议尽快运行选股/生成盘前计划补齐候选池。"
                )
            else:
                message = f"盘中状态已刷新，但当前监控可用性不足：{runtime_state['status_label']}。"
        else:
            message = (
                "盘中状态已刷新，但当前未检测到实时监控在线。"
                "请检查主监控是否已启动。"
            )
        return {
            "success": True,
            "action": "refresh_intraday_status",
            "message": message,
            "payload": {
                "stage_target": "intradaySection",
                "refreshed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "monitor_session": session,
                "runtime_state": runtime_state,
            },
        }

    def _update_stock_data(self) -> Dict[str, Any]:
        task = self.task_runner.run_update_stock_data()
        return {
            "success": True,
            "action": "update_stock_data",
            "task_id": task.get("task_id"),
            "message": "股票数据更新任务已提交，后台执行中。",
            "payload": {
                "stage_target": "todayBoardSection",
                "task": task,
            },
        }

    def _run_stock_selection(self, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        strategy = str(payload.get("strategy", "secondary_launch") if isinstance(payload, dict) else "secondary_launch")
        task = self.task_runner.run_stock_selection(strategy=strategy)
        return {
            "success": True,
            "action": "run_stock_selection",
            "task_id": task.get("task_id"),
            "message": f"今日选股任务已提交，策略：{self._push_strategy_label(strategy)}。",
            "payload": {
                "stage_target": "preMarketSection",
                "strategy": strategy,
                "task": task,
            },
        }

    def _push_selection_wecom(self, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        strategy = str(payload.get("strategy", "secondary_launch") if isinstance(payload, dict) else "secondary_launch")
        task = self.task_runner.run_push_selection_wecom(strategy=strategy)
        return {
            "success": True,
            "action": "push_selection_wecom",
            "task_id": task.get("task_id"),
            "message": f"选股推送任务已提交，策略：{self._push_strategy_label(strategy)}。",
            "payload": {
                "stage_target": "preMarketSection",
                "strategy": strategy,
                "task": task,
            },
        }

    def _push_review_wecom(self, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        strategy = str(payload.get("strategy", "secondary_launch") if isinstance(payload, dict) else "secondary_launch")
        task = self.task_runner.run_push_review_wecom(strategy=strategy)
        return {
            "success": True,
            "action": "push_review_wecom",
            "task_id": task.get("task_id"),
            "message": f"复盘推送任务已提交，策略：{self._push_strategy_label(strategy)}。",
            "payload": {
                "stage_target": "postMarketSection",
                "strategy": strategy,
                "task": task,
            },
        }

    def _update_holding(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        ts_code = str(payload.get("ts_code", "") or "").strip()
        name = str(payload.get("name", "") or "").strip()
        hold_price = float(payload.get("hold_price", 0) or 0)
        hold_num = int(payload.get("hold_num", 0) or 0)
        if not ts_code or not name:
            raise ValueError("更新持仓需要填写股票代码和名称。")
        if hold_price <= 0 or hold_num <= 0:
            raise ValueError("持仓成本和持仓数量必须大于 0。")
        hold_date = str(payload.get("hold_date", "") or "").strip() or datetime.now().strftime("%Y-%m-%d")
        self.hold_service.add_hold(
            {
                "ts_code": ts_code,
                "name": name,
                "hold_price": hold_price,
                "hold_num": hold_num,
                "target_profit": payload.get("target_profit"),
                "target_stop": payload.get("target_stop"),
                "hold_date": hold_date,
            }
        )
        return {
            "success": True,
            "action": "update_holding",
            "message": f"持仓已更新：{ts_code} {name}，共 {hold_num} 股。",
            "payload": {
                "stage_target": "todayBoardSection",
                "ts_code": ts_code,
            },
        }

    def _remove_holding(self, payload: Dict[str, Any], confirmed: bool) -> Dict[str, Any]:
        self._require_confirmed(confirmed, "删除持仓属于高风险动作，请确认后再执行。")
        ts_code = str(payload.get("ts_code", "") or "").strip()
        if not ts_code:
            raise ValueError("删除持仓需要填写股票代码。")
        affected = int(self.hold_service.remove_hold(ts_code) or 0)
        return {
            "success": True,
            "action": "remove_holding",
            "message": f"持仓删除完成：{ts_code}，影响 {affected} 条记录。",
            "payload": {
                "stage_target": "todayBoardSection",
                "affected_rows": affected,
            },
        }

    def _clear_candidate_pool(self, confirmed: bool) -> Dict[str, Any]:
        self._require_confirmed(confirmed, "清空候选池前请先确认。")
        result = self.task_runner.clear_candidate_pool()
        return {
            "success": True,
            "action": "clear_candidate_pool",
            "message": f"候选池已清空，数据库清理 {int(result.get('deleted_rows', 0) or 0)} 条。",
            "payload": {
                "stage_target": "preMarketSection",
                **result,
            },
        }

    def _clear_history_records(self, confirmed: bool) -> Dict[str, Any]:
        self._require_confirmed(confirmed, "清理历史推荐/跟踪记录前请先确认。")
        result = self.task_runner.clear_history_records()
        return {
            "success": True,
            "action": "clear_history_records",
            "message": f"历史记录已清理，共删除 {int(result.get('total_deleted', 0) or 0)} 条。",
            "payload": {
                "stage_target": "preMarketSection",
                **result,
            },
        }

    def _clear_virtual_trades(self, confirmed: bool) -> Dict[str, Any]:
        self._require_confirmed(confirmed, "清理虚拟交易记录前请先确认。")
        result = self.task_runner.clear_virtual_trades()
        total_deleted = int(result.get("open_count", 0) or 0) + int(result.get("closed_count", 0) or 0)
        return {
            "success": True,
            "action": "clear_virtual_trades",
            "message": f"虚拟交易记录已清理，共移除 {total_deleted} 笔。",
            "payload": {
                "stage_target": "todayBoardSection",
                **result,
            },
        }

    def _get_runtime_state(self) -> Dict[str, Any]:
        latest = self.monitoring_store.get_latest_snapshot(source="service")
        timeout_seconds = int(self.config.get("monitor.heartbeat_timeout_seconds", 600) or 600)
        candidate_count = self._get_candidate_count()
        recent_incidents = self.monitoring_store.get_recent_incidents(limit=8)
        degraded_messages = self._collect_degraded_messages(recent_incidents)
        terminal_state = self.terminal_runtime.inspect()
        if not latest:
            return {
                "runtime_online": bool(terminal_state.get("terminal_online", False)),
                "runtime_usable": False,
                "status_label": (
                    "终端监控运行中，但未检测到健康快照"
                    if terminal_state.get("terminal_online")
                    else "未检测到实时监控"
                ),
                "source": "service",
                "candidate_count": candidate_count,
                "degraded_reasons": degraded_messages,
                "terminal_runtime": terminal_state,
            }

        snapshot_time = str(latest.get("snapshot_time", "") or "")
        age_seconds = None
        if snapshot_time:
            try:
                age_seconds = int((datetime.now() - datetime.strptime(snapshot_time, "%Y-%m-%d %H:%M:%S")).total_seconds())
            except Exception:
                age_seconds = None

        runtime_online = (
            age_seconds is not None and age_seconds <= timeout_seconds
        ) or bool(terminal_state.get("terminal_online", False))
        runtime_usable = runtime_online and candidate_count > 0 and not degraded_messages
        if not runtime_online:
            status_label = "实时监控停更"
        elif candidate_count <= 0:
            status_label = "候选池为空"
        elif degraded_messages:
            status_label = "数据源已降级"
        else:
            status_label = "实时监控在线且可用"
        return {
            "runtime_online": runtime_online,
            "runtime_usable": runtime_usable,
            "status_label": status_label,
            "source": "service",
            "snapshot_time": snapshot_time,
            "age_seconds": age_seconds,
            "candidate_count": candidate_count,
            "degraded_reasons": degraded_messages,
            "terminal_runtime": terminal_state,
        }

    def _get_candidate_count(self) -> int:
        # 兼容：部分环境没有 candidate_pool 表，候选池以 JSON 缓存为准。
        try:
            row = self.db.query_one("SELECT name FROM sqlite_master WHERE type='table' AND name='candidate_pool'")
            if row:
                cnt_row = self.db.query_one("SELECT COUNT(*) AS cnt FROM candidate_pool")
                if cnt_row and cnt_row.get("cnt") is not None:
                    return int(cnt_row.get("cnt") or 0)
        except Exception:
            return 0

        try:
            cache_path = self.project_root / "data" / "cache" / "candidate_pool.json"
            if not cache_path.exists():
                return 0
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
            if isinstance(payload, list):
                return len(payload)
            if isinstance(payload, dict):
                raw = payload.get("candidates")
                if isinstance(raw, list):
                    return len(raw)
                raw_top = payload.get("top_candidates")
                if isinstance(raw_top, list):
                    return len(raw_top)
                return int(payload.get("count") or 0)
        except Exception:
            return 0
        return 0

    @staticmethod
    def _collect_degraded_messages(incidents: Any) -> list[str]:
        degraded = []
        for item in incidents or []:
            message = str(item.get("message", "") or "")
            title = str(item.get("title", "") or "")
            merged = f"{title} {message}"
            if "降级" in merged or "No realtime market data available" in merged or "获取失败" in merged:
                degraded.append(merged[:60])
        return degraded[:3]

    @staticmethod
    def _require_confirmed(confirmed: bool, message: str) -> None:
        if not confirmed:
            raise ValueError(message)

    @staticmethod
    def _push_strategy_label(strategy: str) -> str:
        mapping = {
            "secondary_launch": "二次启动策略",
            "secondary": "二次启动策略",
            "legacy": "原策略",
            "both": "双推送",
            "breakout": "突破策略",
            "strong_start": "强势股刚启动",
        }
        return mapping.get(str(strategy or "").strip().lower(), str(strategy or "默认策略"))

    def _resolve_terminals_directory(self) -> str | None:
        configured = self.config.get("dashboard.terminals_directory") or os.environ.get("DASHBOARD_TERMINALS_DIR")
        if configured:
            return str(configured)

        project_name = str(self.project_root).replace(":", "").replace("\\", "-").replace("/", "-")
        default_path = Path.home() / ".cursor" / "projects" / project_name / "terminals"
        if default_path.exists():
            return str(default_path)
        return None
