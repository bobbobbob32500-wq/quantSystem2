# -*- coding: utf-8 -*-
"""
运行时健康监控与异常分级组件。
"""

from __future__ import annotations

import sqlite3
from collections import Counter, defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from statistics import mean
from time import perf_counter
from typing import Any, Callable, Deque, Dict, Optional

import requests
import os
import shutil

from src.core.exceptions import (
    ConfigException,
    DatabaseException,
    DataSourceException,
    PushException,
    QuantSystemException,
    RiskControlException,
    SchedulerException,
)
from src.core.logger import setup_logger

logger = setup_logger("runtime_monitor")


class AlertSeverity(str, Enum):
    """告警严重级别。"""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class IncidentCategory(str, Enum):
    """运行时事件分类。"""

    SYSTEM = "system"
    CONFIG = "config"
    DATABASE = "database"
    DATA_SOURCE = "data_source"
    PUSH = "push"
    SCHEDULER = "scheduler"
    STRATEGY = "strategy"
    RISK = "risk"
    MONITOR = "monitor"
    SERVICE = "service"


@dataclass
class SystemIncident:
    """统一的运行时事件记录。"""

    title: str
    message: str
    severity: AlertSeverity
    category: IncidentCategory
    component: str
    timestamp: str
    retryable: bool = False
    error_code: Optional[str] = None
    exception_type: Optional[str] = None
    context: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "message": self.message,
            "severity": self.severity.value,
            "category": self.category.value,
            "component": self.component,
            "timestamp": self.timestamp,
            "retryable": self.retryable,
            "error_code": self.error_code,
            "exception_type": self.exception_type,
            "context": self.context,
        }


class MonitoredOperation:
    """用于统计时延的轻量上下文管理器。"""

    def __init__(
        self,
        monitor: "RuntimeHealthMonitor",
        component: str,
        context: Optional[Dict[str, Any]] = None,
    ):
        self.monitor = monitor
        self.component = component
        self.context = context or {}
        self._start = 0.0

    def __enter__(self):
        self._start = perf_counter()
        return self

    def __exit__(self, exc_type, exc, tb):
        latency = perf_counter() - self._start
        if exc is None:
            self.monitor.record_success(self.component, latency_seconds=latency, context=self.context)
            return False

        self.monitor.record_incident(
            exception=exc,
            title=f"{self.component} 执行失败",
            component=self.component,
            category=IncidentCategory.MONITOR,
            context={**self.context, "latency_seconds": round(latency, 6)},
        )
        return False


def classify_exception(
    exception: Exception,
    component: str = "",
    category: Optional[IncidentCategory] = None,
) -> Dict[str, Any]:
    """将异常映射为统一的告警等级与分类。"""
    if isinstance(exception, QuantSystemException):
        resolved_category = category or IncidentCategory(exception.category)
        return {
            "severity": AlertSeverity(exception.severity),
            "category": resolved_category,
            "retryable": exception.retryable,
            "error_code": exception.error_code,
            "context": exception.context,
        }

    if isinstance(exception, ConfigException):
        return {
            "severity": AlertSeverity.CRITICAL,
            "category": category or IncidentCategory.CONFIG,
            "retryable": False,
            "error_code": "CONFIG_ERROR",
            "context": {},
        }

    if isinstance(exception, (DatabaseException, sqlite3.Error)):
        return {
            "severity": AlertSeverity.ERROR,
            "category": category or IncidentCategory.DATABASE,
            "retryable": isinstance(exception, sqlite3.OperationalError),
            "error_code": "DB_ERROR",
            "context": {},
        }

    if isinstance(exception, (DataSourceException, TimeoutError, ConnectionError, requests.RequestException)):
        return {
            "severity": AlertSeverity.WARNING,
            "category": category or IncidentCategory.DATA_SOURCE,
            "retryable": True,
            "error_code": "DATA_SOURCE_ERROR",
            "context": {},
        }

    if isinstance(exception, PushException):
        return {
            "severity": AlertSeverity.WARNING,
            "category": category or IncidentCategory.PUSH,
            "retryable": True,
            "error_code": exception.error_code,
            "context": exception.context,
        }

    if isinstance(exception, SchedulerException):
        return {
            "severity": AlertSeverity.ERROR,
            "category": category or IncidentCategory.SCHEDULER,
            "retryable": True,
            "error_code": exception.error_code,
            "context": exception.context,
        }

    if isinstance(exception, RiskControlException):
        return {
            "severity": AlertSeverity.ERROR,
            "category": category or IncidentCategory.RISK,
            "retryable": False,
            "error_code": exception.error_code,
            "context": exception.context,
        }

    if isinstance(exception, ValueError):
        return {
            "severity": AlertSeverity.WARNING,
            "category": category or IncidentCategory.STRATEGY,
            "retryable": False,
            "error_code": "VALUE_ERROR",
            "context": {},
        }

    return {
        "severity": AlertSeverity.ERROR,
        "category": category or IncidentCategory.SYSTEM,
        "retryable": False,
        "error_code": exception.__class__.__name__.upper(),
        "context": {},
    }


class RuntimeHealthMonitor:
    """统一收集服务心跳、事件与性能指标。"""

    def __init__(
        self,
        alert_callback: Optional[Callable[[SystemIncident], None]] = None,
        incident_callback: Optional[Callable[[SystemIncident], None]] = None,
        alert_cooldown_seconds: int = 900,
        heartbeat_timeout_seconds: int = 600,
        max_recent_incidents: int = 100,
        max_latency_samples: int = 300,
    ):
        self.alert_callback = alert_callback
        self.incident_callback = incident_callback
        self.alert_cooldown_seconds = alert_cooldown_seconds
        self.heartbeat_timeout_seconds = heartbeat_timeout_seconds
        self.started_at = datetime.now()
        self.recent_incidents: Deque[SystemIncident] = deque(maxlen=max_recent_incidents)
        self.component_heartbeats: Dict[str, Dict[str, Any]] = {}
        self.success_counter: Counter = Counter()
        self.incident_counter: Counter = Counter()
        self.severity_counter: Counter = Counter()
        self.latency_samples: Dict[str, Deque[float]] = defaultdict(
            lambda: deque(maxlen=max_latency_samples)
        )
        self._last_alert_at: Dict[str, datetime] = {}

    def monitor_operation(self, component: str, context: Optional[Dict[str, Any]] = None) -> MonitoredOperation:
        """返回一个自动统计成功与失败的上下文管理器。"""
        return MonitoredOperation(self, component=component, context=context)

    def heartbeat(self, component: str, details: Optional[Dict[str, Any]] = None):
        """记录组件心跳。"""
        self.component_heartbeats[component] = {
            "last_seen": datetime.now(),
            "details": details or {},
        }

    def record_success(
        self,
        component: str,
        latency_seconds: Optional[float] = None,
        context: Optional[Dict[str, Any]] = None,
    ):
        """记录成功执行。"""
        self.success_counter[component] += 1
        self.heartbeat(component, details=context)
        if latency_seconds is not None:
            self.latency_samples[component].append(float(latency_seconds))

    def record_incident(
        self,
        exception: Exception,
        title: str,
        component: str,
        category: Optional[IncidentCategory] = None,
        severity: Optional[AlertSeverity] = None,
        context: Optional[Dict[str, Any]] = None,
        force_alert: bool = False,
    ) -> SystemIncident:
        """记录异常事件，并按策略发送告警。"""
        classification = classify_exception(exception, component=component, category=category)
        incident = SystemIncident(
            title=title,
            message=str(exception),
            severity=severity or classification["severity"],
            category=classification["category"],
            component=component,
            timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            retryable=classification["retryable"],
            error_code=classification["error_code"],
            exception_type=exception.__class__.__name__,
            context={**classification.get("context", {}), **(context or {})},
        )

        self.recent_incidents.append(incident)
        self.incident_counter[component] += 1
        self.severity_counter[incident.severity.value] += 1

        log_message = f"{incident.title} | {incident.component} | {incident.message}"
        if incident.severity == AlertSeverity.CRITICAL:
            logger.critical(log_message)
        elif incident.severity == AlertSeverity.ERROR:
            logger.error(log_message)
        elif incident.severity == AlertSeverity.WARNING:
            logger.warning(log_message)
        else:
            logger.info(log_message)

        if self.incident_callback is not None:
            try:
                self.incident_callback(incident)
            except Exception as exc:
                logger.error(f"运行时事件持久化失败: {exc}")

        if self._should_alert(incident) or force_alert:
            self._dispatch_alert(incident)

        return incident

    def get_component_status(self) -> Dict[str, Dict[str, Any]]:
        """返回当前组件健康状态。"""
        now = datetime.now()
        status: Dict[str, Dict[str, Any]] = {}
        for component, info in self.component_heartbeats.items():
            last_seen = info["last_seen"]
            lag_seconds = (now - last_seen).total_seconds()
            health = "healthy" if lag_seconds <= self.heartbeat_timeout_seconds else "stale"
            status[component] = {
                "health": health,
                "last_seen": last_seen.strftime("%Y-%m-%d %H:%M:%S"),
                "lag_seconds": round(lag_seconds, 2),
                "details": info.get("details", {}),
            }
        return status

    def get_snapshot(self) -> Dict[str, Any]:
        """获取运行时快照。"""
        uptime_seconds = (datetime.now() - self.started_at).total_seconds()
        latency_summary = {}
        for component, samples in self.latency_samples.items():
            if not samples:
                continue
            ordered = sorted(samples)
            p95_index = min(len(ordered) - 1, max(0, int(len(ordered) * 0.95) - 1))
            latency_summary[component] = {
                "avg_ms": round(mean(samples) * 1000, 3),
                "p95_ms": round(ordered[p95_index] * 1000, 3),
                "max_ms": round(max(samples) * 1000, 3),
                "samples": len(samples),
            }

        snapshot = {
            "started_at": self.started_at.strftime("%Y-%m-%d %H:%M:%S"),
            "uptime_seconds": round(uptime_seconds, 2),
            "success_counter": dict(self.success_counter),
            "incident_counter": dict(self.incident_counter),
            "severity_counter": dict(self.severity_counter),
            "component_status": self.get_component_status(),
            "latency_summary": latency_summary,
            "recent_incidents": [incident.to_dict() for incident in list(self.recent_incidents)[-10:]],
        }
        snapshot["system_metrics"] = self._collect_system_metrics()
        return snapshot

    @staticmethod
    def _collect_system_metrics() -> Dict[str, Any]:
        """
        采集最小可用的资源指标，便于实盘定位卡顿/资源打满问题。
        - 优先使用 psutil（若环境已安装）
        - 无 psutil 时退化为磁盘占用与进程基础信息
        """
        metrics: Dict[str, Any] = {
            "pid": os.getpid(),
            "collected_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

        try:
            usage = shutil.disk_usage(os.getcwd())
            metrics["disk"] = {
                "cwd": os.getcwd(),
                "total_gb": round(usage.total / (1024**3), 3),
                "used_gb": round(usage.used / (1024**3), 3),
                "free_gb": round(usage.free / (1024**3), 3),
                "free_pct": round(usage.free / usage.total * 100, 2) if usage.total else None,
            }
        except Exception:
            metrics["disk"] = {}

        try:
            import psutil  # type: ignore

            p = psutil.Process(os.getpid())
            mem = p.memory_info()
            metrics["process"] = {
                "rss_mb": round(mem.rss / (1024**2), 3),
                "vms_mb": round(mem.vms / (1024**2), 3),
                "threads": int(p.num_threads()),
            }
            try:
                metrics["process"]["cpu_percent"] = float(p.cpu_percent(interval=None))
            except Exception:
                metrics["process"]["cpu_percent"] = None

            try:
                vm = psutil.virtual_memory()
                metrics["memory"] = {
                    "total_gb": round(vm.total / (1024**3), 3),
                    "available_gb": round(vm.available / (1024**3), 3),
                    "used_pct": round(float(vm.percent), 2),
                }
            except Exception:
                metrics["memory"] = {}
        except Exception:
            # psutil 不可用时不报错，保持最小指标
            metrics.setdefault("process", {})
            metrics.setdefault("memory", {})

        return metrics

    def _should_alert(self, incident: SystemIncident) -> bool:
        if self.alert_callback is None:
            return False

        if incident.severity not in {AlertSeverity.ERROR, AlertSeverity.CRITICAL}:
            return False

        cooldown_key = f"{incident.component}:{incident.error_code or incident.exception_type}"
        last_alert_at = self._last_alert_at.get(cooldown_key)
        if last_alert_at is None:
            return True

        elapsed = (datetime.now() - last_alert_at).total_seconds()
        return elapsed >= self.alert_cooldown_seconds

    def _dispatch_alert(self, incident: SystemIncident):
        if self.alert_callback is None:
            return

        cooldown_key = f"{incident.component}:{incident.error_code or incident.exception_type}"
        self._last_alert_at[cooldown_key] = datetime.now()

        try:
            self.alert_callback(incident)
        except Exception as exc:
            logger.error(f"运行时告警发送失败: {exc}")
