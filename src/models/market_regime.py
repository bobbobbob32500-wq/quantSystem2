"""
市场状态数据模型

定义市场状态判定的数据结构
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import List, Tuple, Dict, Optional


class TrendState(Enum):
    """趋势状态"""
    STRONG = "STRONG"
    WEAK = "WEAK"


class MoneyState(Enum):
    """资金状态"""
    INFLOW = "INFLOW"
    OUTFLOW = "OUTFLOW"


class MarketRegime(Enum):
    """市场状态"""
    STRONG_BULL = "STRONG_BULL"      # 真牛市
    WEAK_BULL = "WEAK_BULL"          # 假牛
    STRONG_NEUTRAL = "STRONG_NEUTRAL" # 题材轮动
    WEAK_NEUTRAL = "WEAK_NEUTRAL"     # 熊市


@dataclass
class MarketRegimeResult:
    """市场状态判定结果"""
    regime: MarketRegime
    trend_state: TrendState
    money_state: MoneyState
    max_position: Tuple[float, float]  # (最小仓位, 最大仓位)
    allowed_strategies: List[str]      # 允许的策略类型
    forbidden_actions: List[str]       # 禁止的行为
    trigger_time: datetime
    trend_details: Dict
    money_details: Dict

    def __post_init__(self):
        if self.trigger_time is None:
            self.trigger_time = datetime.now()
        if self.trend_details is None:
            self.trend_details = {}
        if self.money_details is None:
            self.money_details = {}

    def to_dict(self) -> Dict:
        """转换为字典"""
        return {
            'regime': self.regime.value,
            'trend_state': self.trend_state.value,
            'money_state': self.money_state.value,
            'max_position': self.max_position,
            'allowed_strategies': self.allowed_strategies,
            'forbidden_actions': self.forbidden_actions,
            'trigger_time': self.trigger_time.isoformat() if self.trigger_time else None,
            'trend_details': self.trend_details,
            'money_details': self.money_details
        }

    def get_max_position(self) -> float:
        """获取最大仓位"""
        return self.max_position[1]

    def is_strategy_allowed(self, strategy: str) -> bool:
        """检查是否允许该策略"""
        return strategy in self.allowed_strategies

    def is_action_forbidden(self, action: str) -> bool:
        """检查是否禁止该行为"""
        return action in self.forbidden_actions


@dataclass
class MarketRegimeConfig:
    """市场状态配置"""
    # 趋势判定参数
    ma60_slope_threshold: float = 0.0
    ma20_slope_threshold: float = 0.0

    # 资金判定参数
    amount_ma_days: int = 20
    up_ratio_threshold: float = 0.5

    # 风险一票否决参数
    limit_down_threshold: int = 30

    # 状态切换冷却参数
    state_hold_days: int = 2  # 状态持续天数
    position_adjust_steps: List[float] = None  # 仓位调整步骤

    def __post_init__(self):
        if self.position_adjust_steps is None:
            self.position_adjust_steps = [1.0, 0.7, 0.4]

    def to_dict(self) -> Dict:
        """转换为字典"""
        return {
            'ma60_slope_threshold': self.ma60_slope_threshold,
            'ma20_slope_threshold': self.ma20_slope_threshold,
            'amount_ma_days': self.amount_ma_days,
            'up_ratio_threshold': self.up_ratio_threshold,
            'limit_down_threshold': self.limit_down_threshold,
            'state_hold_days': self.state_hold_days,
            'position_adjust_steps': self.position_adjust_steps
        }
