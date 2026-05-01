"""Monitor lifecycle helpers for EnhancedHybridSystem."""

from __future__ import annotations

from datetime import datetime
import logging
import threading
import time as time_module

from src.modules.trade_day_guard import is_cn_a_share_trade_day

logger = logging.getLogger(__name__)


def is_trade_time(now: datetime, system=None) -> bool:
    """Return whether current time is inside the A-share trading session."""
    if system is not None:
        cache = getattr(system, "_trade_day_cache", None)
        if not isinstance(cache, dict):
            cache = {}
            setattr(system, "_trade_day_cache", cache)

        config = getattr(system, "system_config", None)
        db = getattr(system, "db", None)
        is_open_day, source = is_cn_a_share_trade_day(
            now=now,
            db=db,
            config=config,
            cache=cache,
        )
        if not is_open_day:
            key = f"{now.strftime('%Y%m%d')}::{source}"
            if getattr(system, "_last_non_trade_day_log_key", None) != key:
                logger.info("Monitor paused: non-trade day (%s) at %s", source, now.strftime("%Y-%m-%d"))
                setattr(system, "_last_non_trade_day_log_key", key)
            return False
    elif now.weekday() >= 5:
        return False

    current_time = now.strftime("%H:%M")
    if "09:30" <= current_time <= "11:30":
        return True
    if "13:00" <= current_time <= "15:00":
        return True
    return False


def _bootstrap_optimizers(system) -> None:
    if not getattr(system, "optimization_auto_start", False):
        return

    if (
        getattr(system, "enable_enhanced_optimization", False)
        and getattr(system, "enhanced_optimizer", None)
        and getattr(system, "optimization_bootstrap_enabled", False)
    ):
        try:
            bootstrap_result = system._bootstrap_enhanced_optimizer_real_samples()
            logger.info(
                "增强优化实盘样本启动校准: status=%s samples=%s",
                bootstrap_result.get("status"),
                bootstrap_result.get("samples"),
            )
        except Exception as exc:
            logger.warning("增强优化启动校准失败，继续监控流程: %s", exc)

    if getattr(system, "enable_auto_optimization", False) and getattr(system, "auto_optimizer", None):
        try:
            if not bool(getattr(system.auto_optimizer, "is_running", False)):
                system.start_auto_optimization()
        except Exception as exc:
            logger.warning("自动优化启动失败，继续监控流程: %s", exc)


def _print_start_banner(system, interval_seconds: int) -> None:
    print("\n" + "=" * 80)
    print("实时监控已启动")
    print("=" * 80)
    print(f"监控股票: {len(system.candidate_pool)}只")
    print(f"核心池: {sum(1 for c in system.candidate_pool if c['pool_type'] == 'core')}只")
    print(f"备选池: {sum(1 for c in system.candidate_pool if c['pool_type'] == 'reserve')}只")
    print(f"轮询间隔: {interval_seconds}秒")
    print("按 Ctrl+C 停止监控")
    print("=" * 80)


def _spawn_monitor_thread(system, interval_seconds: int) -> None:
    system.monitor_thread = threading.Thread(
        target=system._monitor_loop,
        args=(interval_seconds,),
        daemon=True,
        name="EnhancedHybridMonitor",
    )
    system.monitor_thread.start()


def _wait_for_monitor_loop(system) -> None:
    try:
        while system.is_monitoring:
            if system.monitor_thread is not None and not system.monitor_thread.is_alive():
                logger.warning("监控线程已退出，主循环停止等待")
                system.is_monitoring = False
                break
            time_module.sleep(1)
    except KeyboardInterrupt:
        system.stop_realtime_monitor()


def start_realtime_monitor(system, interval_seconds: int = 10) -> None:
    """Start realtime monitoring and keep the foreground process alive."""
    if not system.candidate_pool:
        print("\n候选池为空，请先执行盘后选股")
        return

    if system.is_monitoring:
        print("\n监控已在运行中")
        return

    _bootstrap_optimizers(system)

    system.is_monitoring = True
    _print_start_banner(system, interval_seconds)
    _spawn_monitor_thread(system, interval_seconds)
    _wait_for_monitor_loop(system)


def stop_realtime_monitor(system) -> None:
    """Stop realtime monitoring and join the background thread."""
    if not system.is_monitoring:
        return

    print("\n\n正在停止监控...")
    system.is_monitoring = False

    if system.monitor_thread:
        system.monitor_thread.join(timeout=2)

    print("监控已停止")
