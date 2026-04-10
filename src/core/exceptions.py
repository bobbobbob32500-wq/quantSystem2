# -*- coding: utf-8 -*-
"""
异常处理模块
定义系统自定义异常类型，并补充运行时分类信息。
"""

from typing import Any, Dict, Optional


class QuantSystemException(Exception):
    """系统基础异常类。"""

    def __init__(
        self,
        message: str,
        error_code: Optional[str] = None,
        severity: str = "error",
        category: str = "system",
        retryable: bool = False,
        context: Optional[Dict[str, Any]] = None,
    ):
        self.message = message
        self.error_code = error_code
        self.severity = severity
        self.category = category
        self.retryable = retryable
        self.context = context or {}
        super().__init__(self.message)

    def to_dict(self) -> Dict[str, Any]:
        """将异常转换为统一字典，便于监控与告警使用。"""
        return {
            "message": self.message,
            "error_code": self.error_code,
            "severity": self.severity,
            "category": self.category,
            "retryable": self.retryable,
            "context": self.context,
            "exception_type": self.__class__.__name__,
        }

    def __str__(self):
        if self.error_code:
            return f"[{self.error_code}] {self.message}"
        return self.message


class DataSourceException(QuantSystemException):
    """数据源异常。"""

    def __init__(
        self,
        message: str,
        data_source: Optional[str] = None,
        retryable: bool = True,
        severity: str = "warning",
        context: Optional[Dict[str, Any]] = None,
    ):
        self.data_source = data_source
        error_code = f"DATA_SOURCE_{data_source}" if data_source else "DATA_SOURCE_ERROR"
        merged_context = {"data_source": data_source, **(context or {})}
        super().__init__(
            message,
            error_code,
            severity=severity,
            category="data_source",
            retryable=retryable,
            context=merged_context,
        )


class DatabaseException(QuantSystemException):
    """数据库异常。"""

    def __init__(
        self,
        message: str,
        table_name: Optional[str] = None,
        retryable: bool = False,
        severity: str = "error",
        context: Optional[Dict[str, Any]] = None,
    ):
        self.table_name = table_name
        error_code = f"DB_{table_name}" if table_name else "DB_ERROR"
        merged_context = {"table_name": table_name, **(context or {})}
        super().__init__(
            message,
            error_code,
            severity=severity,
            category="database",
            retryable=retryable,
            context=merged_context,
        )


class ConfigException(QuantSystemException):
    """配置异常。"""

    def __init__(
        self,
        message: str,
        config_key: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
    ):
        self.config_key = config_key
        error_code = f"CONFIG_{config_key}" if config_key else "CONFIG_ERROR"
        merged_context = {"config_key": config_key, **(context or {})}
        super().__init__(
            message,
            error_code,
            severity="critical",
            category="config",
            retryable=False,
            context=merged_context,
        )


class MarketAnalysisException(QuantSystemException):
    """市场分析异常。"""

    def __init__(self, message: str, context: Optional[Dict[str, Any]] = None):
        super().__init__(
            message,
            "MARKET_ANALYSIS_ERROR",
            severity="warning",
            category="strategy",
            retryable=False,
            context=context,
        )


class StockSelectionException(QuantSystemException):
    """选股异常。"""

    def __init__(self, message: str, context: Optional[Dict[str, Any]] = None):
        super().__init__(
            message,
            "STOCK_SELECTION_ERROR",
            severity="warning",
            category="strategy",
            retryable=False,
            context=context,
        )


class RiskControlException(QuantSystemException):
    """风控异常。"""

    def __init__(self, message: str, context: Optional[Dict[str, Any]] = None):
        super().__init__(
            message,
            "RISK_CONTROL_ERROR",
            severity="error",
            category="risk",
            retryable=False,
            context=context,
        )


class PushException(QuantSystemException):
    """消息推送异常。"""

    def __init__(
        self,
        message: str,
        push_channel: Optional[str] = None,
        retryable: bool = True,
        severity: str = "warning",
        context: Optional[Dict[str, Any]] = None,
    ):
        self.push_channel = push_channel
        error_code = f"PUSH_{push_channel}" if push_channel else "PUSH_ERROR"
        merged_context = {"push_channel": push_channel, **(context or {})}
        super().__init__(
            message,
            error_code,
            severity=severity,
            category="push",
            retryable=retryable,
            context=merged_context,
        )


class SchedulerException(QuantSystemException):
    """定时任务异常。"""

    def __init__(
        self,
        message: str,
        task_name: Optional[str] = None,
        retryable: bool = True,
        severity: str = "error",
        context: Optional[Dict[str, Any]] = None,
    ):
        self.task_name = task_name
        error_code = f"SCHEDULER_{task_name}" if task_name else "SCHEDULER_ERROR"
        merged_context = {"task_name": task_name, **(context or {})}
        super().__init__(
            message,
            error_code,
            severity=severity,
            category="scheduler",
            retryable=retryable,
            context=merged_context,
        )
