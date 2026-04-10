# -*- coding: utf-8 -*-
"""
仓位控制模块（Position Controller）
提供仓位控制接口，内部调用统一市场状态引擎
"""

from typing import Dict, Optional
from datetime import datetime

from src.core.logger import get_logger
from src.core.config import ConfigManager
from src.core.database import DatabaseManager
from src.engines.market_regime_engine import (
    MarketRegimeEngine,
    TrendState,
    MoneyState,
    SentimentState,
    RiskState,
    MarketRegime
)

logger = get_logger("position_controller")


class PositionController:
    """仓位控制器 - 封装市场状态引擎"""
    
    def __init__(self, config: ConfigManager = None, db: DatabaseManager = None):
        if config is None:
            config = ConfigManager()
        if db is None:
            db = DatabaseManager(config)
        
        self.config = config
        self.db = db
        self._engine = MarketRegimeEngine(config, db)
        
        logger.info("仓位控制器初始化完成")
    
    def analyze_market(self, end_date: str = None) -> Dict:
        """
        分析市场并输出仓位建议
        
        Args:
            end_date: 结束日期（YYYYMMDD格式），默认为当天
        
        Returns:
            仓位控制结果
        """
        return self._engine.analyze_market(end_date)
    
    def get_target_position(self, end_date: str = None) -> float:
        """
        获取目标仓位
        
        Args:
            end_date: 结束日期
        
        Returns:
            目标仓位比例（0-1）
        """
        result = self.analyze_market(end_date)
        return result.get('target_position', 0.3)
    
    def get_position_level(self, end_date: str = None) -> str:
        """
        获取仓位等级
        
        Args:
            end_date: 结束日期
        
        Returns:
            仓位等级描述
        """
        result = self.analyze_market(end_date)
        return result.get('position_level', '轻仓')
    
    def get_strategy_suggestion(self, end_date: str = None) -> str:
        """
        获取策略建议
        
        Args:
            end_date: 结束日期
        
        Returns:
            策略建议
        """
        result = self.analyze_market(end_date)
        return result.get('strategy_suggestion', '谨慎观望')
    
    def is_tradable(self, end_date: str = None) -> bool:
        """
        判断是否适合交易
        
        Args:
            end_date: 结束日期
        
        Returns:
            是否适合交易
        """
        result = self.analyze_market(end_date)
        regime = result.get('market_regime', 'NEUTRAL')
        return regime not in ['STRONG_BEAR', 'BEAR']
    
    def get_risk_level(self, end_date: str = None) -> str:
        """
        获取风险等级
        
        Args:
            end_date: 结束日期
        
        Returns:
            风险等级
        """
        result = self.analyze_market(end_date)
        return result.get('risk_state', 'MEDIUM')


TrendState = TrendState
MoneyState = MoneyState
SentimentState = SentimentState
RiskState = RiskState
MarketRegime = MarketRegime
