# -*- coding: utf-8 -*-
"""
Quant service runner with runtime health monitoring and alerting.
"""

import os
import signal
import sys
import time
from datetime import datetime
from time import perf_counter

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.core.config import ConfigManager
from src.core.database import DatabaseManager
from src.core.logger import setup_logger
from src.core.runtime_monitor import IncidentCategory, RuntimeHealthMonitor
from src.modules.data_updater import DataUpdater
from src.modules.enhanced_hybrid_system import EnhancedHybridSystem
from src.modules.message_pusher import MessagePusher
from src.modules.monitoring_store import MonitoringStore
from src.modules.task_scheduler import QuantTaskManager

logger = setup_logger("service")


class QuantService:
    """Long-running background service."""

    def __init__(self):
        self.logger = setup_logger("quant_service")
        self.config = ConfigManager()
        self.db = DatabaseManager(self.config)
        self.monitoring_store = MonitoringStore(self.db)
        self.message_pusher = MessagePusher(self.config)
        self.health_monitor = RuntimeHealthMonitor(
            alert_callback=self._push_system_alert,
            incident_callback=self._persist_incident,
            alert_cooldown_seconds=self.config.get("monitor.alert_cooldown_seconds", 900),
            heartbeat_timeout_seconds=self.config.get("monitor.heartbeat_timeout_seconds", 600),
        )

        self.is_running = False
        self.task_manager = None
        self.monitor = None
        self.last_status_report = None
        self.health_snapshot_interval = int(
            self.config.get("monitor.health_snapshot_interval_seconds", 60)
        )
        self.last_health_snapshot_at = None

        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        self.health_monitor.record_success("service.lifecycle", context={"action": "initialized"})
        logger.info("Quant service initialized")

    def _signal_handler(self, signum, frame):
        logger.info(f"Received stop signal: {signum}")
        self.stop()

    def _push_system_alert(self, incident):
        if not self.message_pusher.enabled:
            return
        self.message_pusher.push_system_alert(incident)

    def _persist_incident(self, incident):
        try:
            self.monitoring_store.save_incident(incident)
        except Exception as exc:
            logger.error(f"Persist incident failed: {exc}")

    def _persist_health_snapshot(self, source: str = "service"):
        try:
            snapshot = self.health_monitor.get_snapshot()
            self.monitoring_store.save_health_snapshot(snapshot, source=source)
        except Exception as exc:
            logger.error(f"Persist health snapshot failed: {exc}")

    def _maybe_persist_health_snapshot(self, now: datetime):
        if self.health_snapshot_interval <= 0:
            return
        if self.last_health_snapshot_at is None:
            self._persist_health_snapshot(source="service")
            self.last_health_snapshot_at = now
            return
        if (now - self.last_health_snapshot_at).total_seconds() >= self.health_snapshot_interval:
            self._persist_health_snapshot(source="service")
            self.last_health_snapshot_at = now

    def start(self):
        if self.is_running:
            logger.warning("Service is already running")
            return

        self.is_running = True
        self._print_banner()

        try:
            print("\n[1/3] Starting scheduler...")
            self.task_manager = QuantTaskManager(
                self.config,
                self.db,
                runtime_monitor=self.health_monitor,
            )
            self.task_manager.setup_auto_push_tasks()

            # 注册每日17:30自动增量数据更新
            data_updater = DataUpdater(self.config, self.db)
            auto_data_update_enabled = bool(
                self.config.get("data_source.auto_daily_update_enabled", True)
            )
            if auto_data_update_enabled:
                self.task_manager.setup_default_tasks(
                    data_update_func=data_updater.ensure_latest_market_data,
                )
                logger.info("已注册每日17:30自动增量数据更新任务")

            self.task_manager.start()
            jobs = self.task_manager.get_task_list()
            self.health_monitor.record_success(
                "service.scheduler_startup",
                context={"jobs": len(jobs)},
            )
            print(f"      Scheduler started with {len(jobs)} jobs")

            print("\n[2/3] Starting intraday monitor...")
            self.monitor = EnhancedHybridSystem(runtime_monitor=self.health_monitor)
            if self.monitor.load_candidate_pool():
                print(f"      Candidate pool size: {len(self.monitor.candidate_pool)}")
            else:
                print("      Candidate pool is empty")
            self.health_monitor.record_success(
                "service.monitor_startup",
                context={"candidate_count": len(self.monitor.candidate_pool)},
            )

            print("\n[3/3] Service started")
            print("\n" + "-" * 60)
            print("  Status: running")
            print(f"  Monitor interval: {self.config.get('monitor.interval_minutes', 2)} minutes")
            print("  Stop with Ctrl+C")
            print("-" * 60)

            logger.info("Quant service started")
            self.health_monitor.record_success("service.lifecycle", context={"action": "started"})
            self._persist_health_snapshot(source="service")
            self._main_loop()

        except Exception as exc:
            self.health_monitor.record_incident(
                exception=exc,
                title="Service startup failed",
                component="service.startup",
                category=IncidentCategory.SERVICE,
                context={"stage": "startup"},
                force_alert=True,
            )
            self.stop()
            raise

    def _main_loop(self):
        last_monitor_time = None
        monitor_interval = self.config.get("monitor.interval_minutes", 2) * 60
        status_interval = self.config.get("monitor.service_status_interval_minutes", 5) * 60
        last_lifecycle_heartbeat_at = None

        while self.is_running:
            loop_started = perf_counter()
            try:
                now = datetime.now()
                in_trade_time = self._is_trade_time(now)
                self.health_monitor.heartbeat(
                    "service.main_loop",
                    {"in_trade_time": in_trade_time},
                )

                # 实盘级：补齐生命周期心跳，避免看板/快照将启动类组件长期标记为 stale
                if last_lifecycle_heartbeat_at is None or (now - last_lifecycle_heartbeat_at).total_seconds() >= 30:
                    try:
                        self.health_monitor.heartbeat("service.lifecycle", {"action": "running"})
                        self.health_monitor.heartbeat("service.scheduler_startup", {"jobs": len(self.task_manager.get_task_list()) if self.task_manager else 0})
                        self.health_monitor.heartbeat("service.monitor_startup", {"candidate_count": len(getattr(self.monitor, "candidate_pool", []) or []) if self.monitor else 0})
                    except Exception:
                        pass
                    last_lifecycle_heartbeat_at = now

                if in_trade_time:
                    should_monitor = (
                        last_monitor_time is None
                        or (now - last_monitor_time).total_seconds() >= monitor_interval
                    )
                    if should_monitor and self._has_candidate_pool():
                        self._run_monitor_check(now)
                        last_monitor_time = now

                if self._should_emit_status(now, status_interval):
                    self._show_heartbeat()
                    self.last_status_report = now

                self._maybe_persist_health_snapshot(now)

                time.sleep(1)
                self.health_monitor.record_success(
                    "service.main_loop",
                    latency_seconds=perf_counter() - loop_started,
                )

            except Exception as exc:
                self.health_monitor.record_incident(
                    exception=exc,
                    title="Service main loop failed",
                    component="service.main_loop",
                    category=IncidentCategory.SERVICE,
                    context={"sleep_seconds": 5},
                )
                time.sleep(5)

    def _should_emit_status(self, now: datetime, status_interval: int) -> bool:
        if self.last_status_report is None:
            return True
        return (now - self.last_status_report).total_seconds() >= status_interval

    def _has_candidate_pool(self) -> bool:
        if self.monitor is None:
            return False
        if self.monitor.candidate_pool:
            return True
        return self.monitor.load_candidate_pool()

    def _is_trade_time(self, now: datetime) -> bool:
        if now.weekday() >= 5:
            return False

        current_time = now.strftime("%H:%M")
        if "09:30" <= current_time <= "11:30":
            return True
        if "13:00" <= current_time <= "15:00":
            return True
        return False

    def _run_monitor_check(self, now: datetime = None):
        started_at = perf_counter()
        current_time = now or datetime.now()
        display_time = current_time.strftime("%H:%M:%S")

        try:
            print(f"\n[{display_time}] Running monitor check...")
            signals = self.monitor.monitor_candidates() if self.monitor else []

            if signals:
                print(f"[{display_time}] Found {len(signals)} buy signals")
                self.monitor.print_buy_signals(signals)
                if self.monitor.push_enabled:
                    self.monitor._push_buy_signals(signals, current_time)
            else:
                print(f"[{display_time}] No buy signals")

            self.health_monitor.record_success(
                "service.monitor_check",
                latency_seconds=perf_counter() - started_at,
                context={"signals": len(signals)},
            )
            return signals

        except Exception as exc:
            self.health_monitor.record_incident(
                exception=exc,
                title="Monitor check failed",
                component="service.monitor_check",
                category=IncidentCategory.MONITOR,
                context={"display_time": display_time},
            )
            return []

    def _show_heartbeat(self):
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        jobs = self.task_manager.get_task_list() if self.task_manager else []
        snapshot = self.health_monitor.get_snapshot()
        incidents = sum(snapshot["incident_counter"].values())
        print(
            f"\n[{now}] Service alive | jobs={len(jobs)} | "
            f"incidents={incidents} | uptime={snapshot['uptime_seconds']}s"
        )

    def stop(self):
        if not self.is_running:
            return

        print("\n\nStopping service...")
        self.is_running = False

        if self.task_manager:
            self.task_manager.stop()
            print("  - Scheduler stopped")

        if self.monitor:
            print("  - Intraday monitor stopped")

        self.health_monitor.record_success("service.lifecycle", context={"action": "stopped"})
        self._persist_health_snapshot(source="service")
        print(f"\nService stopped at {datetime.now().strftime('%H:%M:%S')}")
        logger.info("Quant service stopped")

    @staticmethod
    def _print_banner():
        print("\n" + "=" * 60)
        print("  A-share Quant Trading Assistant - Service Mode")
        print("=" * 60)
        print(f"  Start time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 60)


def main():
    print(
        """
    ================================================================
    |  A-share Quant Trading Assistant - Background Service         |
    |                                                              |
    |  Features:                                                   |
    |    - Scheduled jobs                                          |
    |    - Intraday monitoring                                     |
    |    - Runtime health monitoring and alerts                    |
    |                                                              |
    |  Usage: python run_service.py                                |
    |  Stop : Ctrl+C                                               |
    ================================================================
    """
    )

    service = QuantService()
    service.start()


if __name__ == "__main__":
    main()
