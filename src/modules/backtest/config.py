# -*- coding: utf-8 -*-
"""
回测配置
"""

from dataclasses import dataclass
from typing import Dict, Any


@dataclass
class BacktestConfig:
    """回测配置"""
    
    # 资金配置
    initial_capital: float = 100000.0  # 初始资金
    max_positions: int = 5             # 最大持仓数
    position_size: float = 0.2         # 单只仓位比例
    
    # 交易成本
    buy_slippage: float = 0.001        # 买入滑点 0.1%
    sell_slippage: float = 0.001       # 卖出滑点 0.1%
    buy_fee: float = 0.0003            # 买入手续费 0.03%
    sell_fee: float = 0.0013           # 危出手续费 0.13%（含印花税）
    
    # 信号阈值
    buy_signal_threshold: float = 30.0  # 买入信号阈值
    sell_signal_threshold: float = 40.0 # 危出信号阈值
    
    # 持仓限制
    max_hold_days: int = 10            # 最大持仓天数
    max_wait_buy_days: int = 5         # 最多等待买入天数
    
    # 止损止盈
    stop_loss_pct: float = -0.05       # 止损 -5%
    take_profit_pct: float = 0.10      # 止盈 +10%
    trailing_stop_pct: float = 0.03    # 移动止盈回撤 3%
    
    # A股规则
    enable_t1_rule: bool = True        # 启用T+1规则
    enable_limit_rule: bool = True     # 启用涨跌停规则
    limit_up_pct: float = 0.10         # 涨停幅度 10%
    limit_down_pct: float = -0.10      # 跌停幅度 -10%
    
    # 数据配置
    use_cache: bool = True             # 使用缓存
    window_size: int = 50              # 数据窗口大小
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'initial_capital': self.initial_capital,
            'max_positions': self.max_positions,
            'position_size': self.position_size,
            'buy_slippage': self.buy_slippage,
            'sell_slippage': self.sell_slippage,
            'buy_fee': self.buy_fee,
            'sell_fee': self.sell_fee,
            'buy_signal_threshold': self.buy_signal_threshold,
            'sell_signal_threshold': self.sell_signal_threshold,
            'max_hold_days': self.max_hold_days,
            'max_wait_buy_days': self.max_wait_buy_days,
            'stop_loss_pct': self.stop_loss_pct,
            'take_profit_pct': self.take_profit_pct,
            'trailing_stop_pct': self.trailing_stop_pct,
            'enable_t1_rule': self.enable_t1_rule,
            'enable_limit_rule': self.enable_limit_rule,
            'limit_up_pct': self.limit_up_pct,
            'limit_down_pct': self.limit_down_pct,
            'use_cache': self.use_cache,
            'window_size': self.window_size,
        }
    
    @classmethod
    def from_dict(cls, config_dict: Dict[str, Any]) -> 'BacktestConfig':
        """从字典创建配置"""
        return cls(**config_dict)
