"""
信号数据模型

定义买入、减仓、卖出信号的数据结构
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Dict, Optional


class SignalType(Enum):
    """信号类型"""
    BUY = "buy"
    REDUCE = "reduce"
    SELL = "sell"


class SignalStatus(Enum):
    """信号状态"""
    PENDING = "pending"       # 待确认
    CONFIRMED = "confirmed"   # 已确认
    REJECTED = "rejected"     # 已拒绝
    EXPIRED = "expired"       # 已过期


class SignalCategory(Enum):
    """信号类别（卖出信号专用）"""
    RISK = "risk"           # 风险类（最高优先级）
    TREND = "trend"         # 趋势类（中等优先级）
    SENTIMENT = "sentiment" # 情绪类（最低优先级）


class SignalPriority(Enum):
    """信号优先级"""
    HIGHEST = "highest"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class StrategyType(Enum):
    """策略类型"""
    MOMENTUM = "Momentum"
    PULLBACK = "Pullback"


@dataclass
class Signal:
    """信号基类"""
    signal_id: str
    ts_code: str
    name: str
    signal_type: SignalType
    signal_category: Optional[SignalCategory] = None
    strategy_type: Optional[StrategyType] = None
    trigger_time: datetime = None
    trigger_conditions: Dict[str, float] = None
    reason: str = ""
    suggestion: Optional[str] = None
    suggested_price: Optional[float] = None
    suggested_position: Optional[float] = None
    reduce_ratio: Optional[float] = None
    priority_score: Optional[float] = None
    priority_level: Optional[SignalPriority] = None
    current_profit: Optional[float] = None
    status: SignalStatus = SignalStatus.PENDING
    confirm_time: Optional[datetime] = None

    def __post_init__(self):
        if self.trigger_time is None:
            self.trigger_time = datetime.now()
        if self.trigger_conditions is None:
            self.trigger_conditions = {}

    def to_dict(self) -> Dict:
        """转换为字典"""
        return {
            'signal_id': self.signal_id,
            'ts_code': self.ts_code,
            'name': self.name,
            'signal_type': self.signal_type.value,
            'signal_category': self.signal_category.value if self.signal_category else None,
            'strategy_type': self.strategy_type.value if self.strategy_type else None,
            'trigger_time': self.trigger_time.isoformat() if self.trigger_time else None,
            'trigger_conditions': self.trigger_conditions,
            'reason': self.reason,
            'suggestion': self.suggestion,
            'suggested_price': self.suggested_price,
            'suggested_position': self.suggested_position,
            'reduce_ratio': self.reduce_ratio,
            'priority_score': self.priority_score,
            'priority_level': self.priority_level.value if self.priority_level else None,
            'current_profit': self.current_profit,
            'status': self.status.value,
            'confirm_time': self.confirm_time.isoformat() if self.confirm_time else None
        }


@dataclass
class BuySignal(Signal):
    """买入信号"""
    volatility_level: str = "中"  # 高/中/低

    def __post_init__(self):
        super().__post_init__()
        self.signal_type = SignalType.BUY


@dataclass
class ReduceSignal(Signal):
    """减仓信号"""
    def __post_init__(self):
        super().__post_init__()
        self.signal_type = SignalType.REDUCE


@dataclass
class SellSignal(Signal):
    """卖出信号"""
    signal_type_name: str = ""  # 信号类型名称（如：价格止损、闪崩等）

    def __post_init__(self):
        super().__post_init__()
        self.signal_type = SignalType.SELL
