"""
交易计划数据模型

定义交易计划的数据结构
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional


class TradePlanStatus(Enum):
    """交易计划状态"""
    PENDING = "pending"       # 待执行
    EXECUTED = "executed"     # 已执行
    CANCELLED = "cancelled"   # 已取消
    EXPIRED = "expired"       # 已过期
    PARTIAL = "partial"       # 部分执行
    FAILED = "failed"         # 执行失败


class OperationType(Enum):
    """操作类型"""
    BUY = "buy"
    SELL = "sell"
    REDUCE = "reduce"


@dataclass
class TradePlan:
    """交易计划"""
    plan_id: str
    signal_id: str
    ts_code: str
    name: str
    operation_type: OperationType
    suggested_price: float
    suggested_quantity: int
    execute_window_start: datetime
    execute_window_end: datetime
    status: TradePlanStatus = TradePlanStatus.PENDING
    execute_status: Optional[str] = None
    execute_time: Optional[datetime] = None
    create_time: datetime = None

    def __post_init__(self):
        if self.create_time is None:
            self.create_time = datetime.now()

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            'plan_id': self.plan_id,
            'signal_id': self.signal_id,
            'ts_code': self.ts_code,
            'name': self.name,
            'operation_type': self.operation_type.value,
            'suggested_price': self.suggested_price,
            'suggested_quantity': self.suggested_quantity,
            'execute_window_start': self.execute_window_start.isoformat() if self.execute_window_start else None,
            'execute_window_end': self.execute_window_end.isoformat() if self.execute_window_end else None,
            'status': self.status.value,
            'execute_status': self.execute_status,
            'execute_time': self.execute_time.isoformat() if self.execute_time else None,
            'create_time': self.create_time.isoformat() if self.create_time else None
        }

    def is_expired(self) -> bool:
        """检查计划是否过期"""
        return datetime.now() > self.execute_window_end

    def is_in_window(self) -> bool:
        """检查是否在执行时间窗口内"""
        now = datetime.now()
        return self.execute_window_start <= now <= self.execute_window_end
