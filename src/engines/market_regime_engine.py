# -*- coding: utf-8 -*-
"""
统一市场状态引擎（Unified Market Regime Engine）
整合趋势、资金、情绪、风险四维分析
"""

import numpy as np
import pandas as pd
from typing import Dict, Optional, Tuple, List
from datetime import datetime, timedelta
from enum import Enum
from dataclasses import dataclass

from src.core.logger import get_logger
from src.core.config import ConfigManager
from src.core.database import DatabaseManager

logger = get_logger("market_regime_engine")


class TrendState(Enum):
    """趋势状态"""
    UP = "UP"
    NEUTRAL = "NEUTRAL"
    DOWN = "DOWN"


class MoneyState(Enum):
    """资金状态"""
    INFLOW = "INFLOW"
    NEUTRAL = "NEUTRAL"
    OUTFLOW = "OUTFLOW"


class SentimentState(Enum):
    """情绪状态"""
    HOT = "HOT"
    NORMAL = "NORMAL"
    COLD = "COLD"
    OVERHEATED = "OVERHEATED"


class RiskState(Enum):
    """风险状态"""
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class MarketRegime(Enum):
    """市场状态"""
    STRONG_BULL = "STRONG_BULL"   # 强势上涨
    BULL = "BULL"                 # 上涨
    WEAK_BULL = "WEAK_BULL"       # 弱上涨
    NEUTRAL = "NEUTRAL"           # 震荡
    WEAK_BEAR = "WEAK_BEAR"       # 弱下跌
    BEAR = "BEAR"                 # 下跌
    STRONG_BEAR = "STRONG_BEAR"   # 强势下跌


@dataclass
class MarketRegimeResult:
    """市场状态判定结果"""
    regime: MarketRegime
    trend_state: TrendState
    money_state: MoneyState
    sentiment_state: SentimentState
    risk_state: RiskState
    trend_strength: float
    money_strength: float
    sentiment_strength: float
    risk_strength: float
    target_position: float
    position_level: str
    strategy_suggestion: str
    analyze_time: str
    details: Dict


class MarketRegimeEngine:
    """统一市场状态引擎"""
    
    _instance = None
    
    def __new__(cls, config: ConfigManager = None, db: DatabaseManager = None):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self, config: ConfigManager = None, db: DatabaseManager = None):
        if hasattr(self, '_initialized') and self._initialized:
            return
        
        if config is None:
            config = ConfigManager()
        if db is None:
            db = DatabaseManager(config)
        
        self.config = config
        self.db = db
        
        self.trend_ma_period = 20
        self.trend_slope_period = 10
        self.sentiment_limit_up_threshold = 50
        self.sentiment_limit_down_threshold = 20
        self.risk_volatility_threshold = 0.25
        self.risk_limit_down_threshold = 30
        
        self.current_regime: Optional[MarketRegime] = None
        self.state_hold_days = 0
        self.min_hold_days = 3

        # P4: 从数据库恢复上次持久化的市场状态
        self._restore_regime_state()

        self._initialized = True
        logger.info("市场状态引擎初始化完成")
    
    def analyze(self, end_date: str = None) -> MarketRegimeResult:
        """
        分析市场状态
        
        Args:
            end_date: 结束日期（YYYYMMDD格式）
        
        Returns:
            市场状态判定结果
        """
        trend_state, trend_strength, trend_details = self._analyze_trend(end_date)
        money_state, money_strength, money_details = self._analyze_money(end_date)
        sentiment_state, sentiment_strength, sentiment_details = self._analyze_sentiment(end_date)
        risk_state, risk_strength, risk_details = self._analyze_risk(end_date)
        
        if self._check_risk_veto(risk_state, risk_strength):
            logger.warning("触发风险一票否决")
            regime = MarketRegime.STRONG_BEAR
        else:
            regime = self._determine_regime(
                trend_state, money_state, sentiment_state, risk_state
            )
        
        if self.current_regime == regime:
            self.state_hold_days += 1
        else:
            if self.state_hold_days >= self.min_hold_days:
                self.current_regime = regime
                self.state_hold_days = 1
                logger.info(f"市场状态切换: {regime.value}")
            else:
                regime = self.current_regime or regime
        
        target_position = self._calculate_target_position(regime, sentiment_state)
        position_level = self._get_position_level(target_position)
        strategy_suggestion = self._get_strategy_suggestion(regime)
        
        result = MarketRegimeResult(
            regime=regime,
            trend_state=trend_state,
            money_state=money_state,
            sentiment_state=sentiment_state,
            risk_state=risk_state,
            trend_strength=round(trend_strength, 2),
            money_strength=round(money_strength, 2),
            sentiment_strength=round(sentiment_strength, 2),
            risk_strength=round(risk_strength, 2),
            target_position=target_position,
            position_level=position_level,
            strategy_suggestion=strategy_suggestion,
            analyze_time=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            details={
                'trend': trend_details,
                'money': money_details,
                'sentiment': sentiment_details,
                'risk': risk_details
            }
        )
        
        logger.info(f"市场状态判定完成: {regime.value}, 目标仓位: {target_position*100:.0f}%")
        # P4: 持久化市场状态
        self._save_regime_state()
        return result

    def _save_regime_state(self) -> None:
        """P4: 将当前市场状态持久化到 system_log，重启后可恢复。"""
        import json as _json
        if self.current_regime is None:
            return
        try:
            payload = _json.dumps({
                "regime": self.current_regime.value,
                "hold_days": int(self.state_hold_days),
            }, ensure_ascii=False)
            self.db.execute(
                "INSERT INTO system_log (log_time, log_level, module_name, log_content, create_time) "
                "VALUES (?, 'INFO', 'market_regime', ?, ?)",
                (
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    payload,
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                ),
            )
        except Exception as e:
            logger.warning("市场状态持久化失败: %s", e)

    def _restore_regime_state(self) -> None:
        """P4: 从 system_log 恢复上次持久化的市场状态。"""
        import json as _json
        try:
            rows = self.db.query(
                "SELECT log_content FROM system_log "
                "WHERE module_name='market_regime' "
                "ORDER BY log_time DESC LIMIT 1"
            )
            if not rows:
                return
            data = _json.loads(rows[0]["log_content"])
            self.current_regime = MarketRegime(data["regime"])
            self.state_hold_days = int(data.get("hold_days", 0))
            logger.info(
                "市场状态已从数据库恢复: %s (hold_days=%d)",
                self.current_regime.value,
                self.state_hold_days,
            )
        except Exception as e:
            logger.warning("市场状态恢复失败，使用默认值: %s", e)
    
    def analyze_market(self, end_date: str = None) -> Dict:
        """
        分析市场并返回字典结果（兼容旧接口）
        
        Args:
            end_date: 结束日期
        
        Returns:
            仓位控制结果字典
        """
        result = self.analyze(end_date)
        
        return {
            'market_regime': result.regime.value,
            'target_position': result.target_position,
            'position_level': result.position_level,
            'strategy_suggestion': result.strategy_suggestion,
            'trend_state': result.trend_state.value,
            'money_state': result.money_state.value,
            'sentiment_state': result.sentiment_state.value,
            'risk_state': result.risk_state.value,
            'trend_strength': result.trend_strength,
            'money_strength': result.money_strength,
            'sentiment_strength': result.sentiment_strength,
            'risk_strength': result.risk_strength,
            'analyze_time': result.analyze_time,
            'details': result.details
        }
    
    def _analyze_trend(self, end_date: str = None) -> Tuple[TrendState, float, Dict]:
        """分析趋势模块"""
        df = self._get_index_data(end_date, days=60)
        
        if df.empty or len(df) < 5:
            return TrendState.NEUTRAL, 0.5, {'error': '数据不足'}
        
        latest_price = df.iloc[-1]['close']
        up_votes = 0
        down_votes = 0
        details = {}
        
        ma5 = df['close'].rolling(window=5).mean().iloc[-1]
        if not pd.isna(ma5):
            position_ratio = (latest_price - ma5) / ma5
            details['ma5_position'] = round(position_ratio * 100, 2)
            if position_ratio > 0.01:
                up_votes += 1
            elif position_ratio < -0.01:
                down_votes += 1
        
        ma10 = df['close'].rolling(window=10).mean().iloc[-1]
        if not pd.isna(ma10):
            position_ratio = (latest_price - ma10) / ma10
            details['ma10_position'] = round(position_ratio * 100, 2)
            if position_ratio > 0.01:
                up_votes += 1
            elif position_ratio < -0.01:
                down_votes += 1
        
        ma20 = df['close'].rolling(window=20).mean().iloc[-1]
        if not pd.isna(ma20):
            position_ratio = (latest_price - ma20) / ma20
            details['ma20_position'] = round(position_ratio * 100, 2)
            if position_ratio > 0.02:
                up_votes += 1
            elif position_ratio < -0.02:
                down_votes += 1
        
        if len(df) >= 5:
            short_slope = df['close'].tail(5).values
            x = np.arange(len(short_slope))
            slope, _ = np.polyfit(x, short_slope, 1)
            if not pd.isna(slope):
                slope_ratio = slope / latest_price if latest_price > 0 else 0
                details['short_slope'] = round(slope_ratio * 100, 3)
                if slope_ratio > 0.002:
                    up_votes += 1
                elif slope_ratio < -0.002:
                    down_votes += 1
        
        details['up_votes'] = up_votes
        details['down_votes'] = down_votes
        
        if up_votes >= 3:
            return TrendState.UP, 0.8, details
        elif down_votes >= 3:
            return TrendState.DOWN, 0.2, details
        else:
            return TrendState.NEUTRAL, 0.5, details
    
    def _analyze_money(self, end_date: str = None) -> Tuple[MoneyState, float, Dict]:
        """分析资金模块"""
        df = self._get_index_data(end_date, days=10)
        
        if df.empty or len(df) < 5:
            return MoneyState.NEUTRAL, 0.5, {'error': '数据不足'}
        
        details = {}
        
        latest_amount = df.iloc[-1]['amount']
        avg_amount = df['amount'].tail(5).mean()
        
        if avg_amount > 0:
            amount_ratio = (latest_amount - avg_amount) / avg_amount
        else:
            amount_ratio = 0
        
        details['amount_ratio'] = round(amount_ratio * 100, 2)
        
        latest_price = df.iloc[-1]['close']
        prev_price = df.iloc[-2]['close']
        
        if prev_price > 0:
            price_change = (latest_price - prev_price) / prev_price
        else:
            price_change = 0
        
        details['price_change'] = round(price_change * 100, 2)
        
        if amount_ratio > 0.1 and price_change > 0:
            return MoneyState.INFLOW, 0.8, details
        elif amount_ratio > 0.1 and price_change < 0:
            return MoneyState.OUTFLOW, 0.3, details
        elif amount_ratio < -0.1 and price_change > 0:
            return MoneyState.NEUTRAL, 0.6, details
        elif amount_ratio < -0.1 and price_change < 0:
            return MoneyState.OUTFLOW, 0.2, details
        else:
            return MoneyState.NEUTRAL, 0.5, details
    
    def _analyze_sentiment(self, end_date: str = None) -> Tuple[SentimentState, float, Dict]:
        """分析情绪模块（全市场统计用 SQL 聚合，避免拉取当日全部股票日线到内存）。"""
        if end_date is None:
            end_date = datetime.now().strftime("%Y%m%d")

        row = self.db.query_one(
            """
            SELECT
                COUNT(*) AS total_count,
                SUM(CASE WHEN pct_chg > 9.5 THEN 1 ELSE 0 END) AS limit_up,
                SUM(CASE WHEN pct_chg < -9.5 THEN 1 ELSE 0 END) AS limit_down,
                SUM(CASE WHEN pct_chg > 0 THEN 1 ELSE 0 END) AS up_count,
                SUM(CASE WHEN pct_chg < 0 THEN 1 ELSE 0 END) AS down_count
            FROM stock_daily
            WHERE trade_date = ?
            """,
            (end_date,),
        )
        if not row or int(row.get("total_count") or 0) == 0:
            return SentimentState.NORMAL, 0.5, {'error': '数据不足'}

        details = {}

        limit_up = int(row.get("limit_up") or 0)
        limit_down = int(row.get("limit_down") or 0)
        up_count = int(row.get("up_count") or 0)
        down_count = int(row.get("down_count") or 0)
        total_count = int(row["total_count"])

        if total_count == 0:
            return SentimentState.NORMAL, 0.5, {'error': '无股票数据'}
        
        up_ratio = up_count / total_count
        limit_up_ratio = limit_up / total_count
        limit_down_ratio = limit_down / total_count
        
        details['up_count'] = up_count
        details['down_count'] = down_count
        details['limit_up'] = limit_up
        details['limit_down'] = limit_down
        details['up_ratio'] = round(up_ratio * 100, 2)
        
        if limit_up > self.sentiment_limit_up_threshold or up_ratio > 0.8:
            return SentimentState.OVERHEATED, 0.9, details
        elif limit_up > 30 or up_ratio > 0.65:
            return SentimentState.HOT, 0.7, details
        elif limit_down > self.sentiment_limit_down_threshold or up_ratio < 0.3:
            return SentimentState.COLD, 0.2, details
        else:
            return SentimentState.NORMAL, 0.5, details
    
    def _analyze_risk(self, end_date: str = None) -> Tuple[RiskState, float, Dict]:
        """分析风险模块"""
        df = self._get_index_data(end_date, days=30)
        
        if df.empty or len(df) < 10:
            return RiskState.MEDIUM, 0.5, {'error': '数据不足'}
        
        details = {}
        
        returns = df['close'].pct_change().dropna()
        volatility = returns.std() * np.sqrt(252) if len(returns) > 1 else 0
        
        details['volatility'] = round(volatility * 100, 2)
        
        max_price = df['close'].max()
        current_price = df['close'].iloc[-1]
        drawdown = (max_price - current_price) / max_price if max_price > 0 else 0
        
        details['drawdown'] = round(drawdown * 100, 2)
        
        risk_score = 0
        
        if volatility > self.risk_volatility_threshold:
            risk_score += 1
            details['volatility_risk'] = True
        
        if drawdown > 0.1:
            risk_score += 1
            details['drawdown_risk'] = True
        
        if risk_score >= 2:
            return RiskState.HIGH, 0.8, details
        elif risk_score == 1:
            return RiskState.MEDIUM, 0.5, details
        else:
            return RiskState.LOW, 0.2, details
    
    def _check_risk_veto(self, risk_state: RiskState, risk_strength: float) -> bool:
        """检查风险一票否决"""
        return risk_state == RiskState.HIGH and risk_strength > 0.7
    
    def _determine_regime(
        self,
        trend_state: TrendState,
        money_state: MoneyState,
        sentiment_state: SentimentState,
        risk_state: RiskState
    ) -> MarketRegime:
        """判定市场状态"""
        score = 0
        
        if trend_state == TrendState.UP:
            score += 2
        elif trend_state == TrendState.DOWN:
            score -= 2
        
        if money_state == MoneyState.INFLOW:
            score += 1
        elif money_state == MoneyState.OUTFLOW:
            score -= 1
        
        if sentiment_state == SentimentState.HOT:
            score += 1
        elif sentiment_state == SentimentState.OVERHEATED:
            score += 0.5
        elif sentiment_state == SentimentState.COLD:
            score -= 1
        
        if risk_state == RiskState.HIGH:
            score -= 1
        elif risk_state == RiskState.LOW:
            score += 0.5
        
        if score >= 3:
            return MarketRegime.STRONG_BULL
        elif score >= 2:
            return MarketRegime.BULL
        elif score >= 1:
            return MarketRegime.WEAK_BULL
        elif score <= -3:
            return MarketRegime.STRONG_BEAR
        elif score <= -2:
            return MarketRegime.BEAR
        elif score <= -1:
            return MarketRegime.WEAK_BEAR
        else:
            return MarketRegime.NEUTRAL
    
    def _calculate_target_position(
        self,
        regime: MarketRegime,
        sentiment_state: SentimentState
    ) -> float:
        """计算目标仓位"""
        position_map = {
            MarketRegime.STRONG_BULL: 0.9,
            MarketRegime.BULL: 0.7,
            MarketRegime.WEAK_BULL: 0.5,
            MarketRegime.NEUTRAL: 0.3,
            MarketRegime.WEAK_BEAR: 0.2,
            MarketRegime.BEAR: 0.1,
            MarketRegime.STRONG_BEAR: 0.0,
        }
        
        base_position = position_map.get(regime, 0.3)
        
        if sentiment_state == SentimentState.OVERHEATED:
            base_position = min(base_position, 0.5)
        elif sentiment_state == SentimentState.COLD:
            base_position = min(base_position, 0.3)
        
        return base_position
    
    def _get_position_level(self, target_position: float) -> str:
        """获取仓位等级"""
        if target_position >= 0.8:
            return "重仓"
        elif target_position >= 0.5:
            return "中仓"
        elif target_position >= 0.3:
            return "轻仓"
        else:
            return "空仓"
    
    def _get_strategy_suggestion(self, regime: MarketRegime) -> str:
        """获取策略建议"""
        suggestion_map = {
            MarketRegime.STRONG_BULL: "强势市场，积极做多，重仓持有",
            MarketRegime.BULL: "上涨趋势，逢低加仓，持股待涨",
            MarketRegime.WEAK_BULL: "弱上涨，精选个股，适度参与",
            MarketRegime.NEUTRAL: "震荡市场，控制仓位，高抛低吸",
            MarketRegime.WEAK_BEAR: "弱下跌，轻仓观望，等待企稳",
            MarketRegime.BEAR: "下跌趋势，减仓避险，观望为主",
            MarketRegime.STRONG_BEAR: "强势下跌，空仓观望，等待机会",
        }
        return suggestion_map.get(regime, "谨慎观望")
    
    def _get_index_data(self, end_date: str = None, days: int = 60) -> pd.DataFrame:
        """获取指数数据"""
        if end_date is None:
            end_date = datetime.now().strftime("%Y%m%d")
        
        start_date = (datetime.strptime(end_date, "%Y%m%d") - timedelta(days=days * 2)).strftime("%Y%m%d")
        
        sql = """
            SELECT trade_date, close, high, low, vol, amount
            FROM stock_daily
            WHERE ts_code = '000001.SH'
            AND trade_date >= ? AND trade_date <= ?
            ORDER BY trade_date DESC
        """
        
        results = self.db.query(sql, (start_date, end_date))
        
        if not results:
            return pd.DataFrame()
        
        df = pd.DataFrame(results)
        df['trade_date'] = pd.to_datetime(df['trade_date'], format='%Y%m%d', errors='coerce')
        df = df.sort_values('trade_date').reset_index(drop=True)
        
        if len(df) > days:
            df = df.tail(days)
        
        return df


market_regime_engine = MarketRegimeEngine()
