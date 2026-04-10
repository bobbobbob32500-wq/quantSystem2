# -*- coding: utf-8 -*-
"""运行时健康监控测试。"""

from src.core.exceptions import ConfigException, DataSourceException
from src.core.runtime_monitor import AlertSeverity, IncidentCategory, RuntimeHealthMonitor


def test_runtime_monitor_records_warning_incident_without_alert():
    pushed_alerts = []
    monitor = RuntimeHealthMonitor(
        alert_callback=pushed_alerts.append,
        alert_cooldown_seconds=0,
        heartbeat_timeout_seconds=60,
    )

    incident = monitor.record_incident(
        exception=DataSourceException("行情接口超时", data_source="tushare"),
        title="数据源异常",
        component="data.fetcher",
        category=IncidentCategory.DATA_SOURCE,
    )

    snapshot = monitor.get_snapshot()
    assert incident.severity == AlertSeverity.WARNING
    assert incident.retryable is True
    assert snapshot["incident_counter"]["data.fetcher"] == 1
    assert pushed_alerts == []


def test_runtime_monitor_pushes_critical_alert():
    pushed_alerts = []
    monitor = RuntimeHealthMonitor(
        alert_callback=pushed_alerts.append,
        alert_cooldown_seconds=0,
        heartbeat_timeout_seconds=60,
    )

    incident = monitor.record_incident(
        exception=ConfigException("关键配置缺失", config_key="push.wechat_webhook"),
        title="配置异常",
        component="service.startup",
    )

    assert incident.severity == AlertSeverity.CRITICAL
    assert len(pushed_alerts) == 1
    assert pushed_alerts[0].component == "service.startup"
