# -*- coding: utf-8 -*-
"""
技术指标分析模块
提供完整的技术指标计算和分析功能
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Tuple, Optional, Union
from src.core.logger import get_logger

logger = get_logger("technical_indicators")


class TechnicalIndicators:
    """技术指标计算类"""
    
    @staticmethod
    def MA(prices: pd.Series, window: int) -> pd.Series:
        """
        简单移动平均线 (Simple Moving Average)
        
        Args:
            prices: 价格序列
            window: 窗口期
        
        Returns:
            MA序列
        """
        return prices.rolling(window=window).mean()
    
    @staticmethod
    def EMA(prices: pd.Series, span: int) -> pd.Series:
        """
        指数移动平均线 (Exponential Moving Average)
        
        Args:
            prices: 价格序列
            span: 跨度
        
        Returns:
            EMA序列
        """
        return prices.ewm(span=span, adjust=False).mean()
    
    @staticmethod
    def SMA(prices: pd.Series, window: int) -> pd.Series:
        """
        平滑移动平均线 (Smoothed Moving Average)
        
        Args:
            prices: 价格序列
            window: 窗口期
        
        Returns:
            SMA序列
        """
        alpha = 1.0 / window
        return prices.ewm(alpha=alpha, adjust=False).mean()
    
    @staticmethod
    def WMA(prices: pd.Series, window: int) -> pd.Series:
        """
        加权移动平均线 (Weighted Moving Average)
        
        Args:
            prices: 价格序列
            window: 窗口期
        
        Returns:
            WMA序列
        """
        weights = np.arange(1, window + 1)
        return prices.rolling(window=window).apply(
            lambda x: np.dot(x, weights) / weights.sum(), raw=True
        )
    
    @staticmethod
    def RSI(prices: pd.Series, period: int = 14) -> pd.Series:
        """
        相对强弱指标 (Relative Strength Index)
        
        Args:
            prices: 价格序列
            period: 周期
        
        Returns:
            RSI序列 (0-100)
        """
        delta = prices.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        return rsi
    
    @staticmethod
    def MACD(
        prices: pd.Series,
        fast: int = 12,
        slow: int = 26,
        signal: int = 9
    ) -> Dict[str, pd.Series]:
        """
        MACD指标 (Moving Average Convergence Divergence)
        
        Args:
            prices: 价格序列
            fast: 快线周期
            slow: 慢线周期
            signal: 信号线周期
        
        Returns:
            包含macd、signal、histogram的字典
        """
        ema_fast = TechnicalIndicators.EMA(prices, fast)
        ema_slow = TechnicalIndicators.EMA(prices, slow)
        
        macd_line = ema_fast - ema_slow
        signal_line = TechnicalIndicators.EMA(macd_line, signal)
        histogram = macd_line - signal_line
        
        return {
            'macd': macd_line,
            'signal': signal_line,
            'histogram': histogram
        }
    
    @staticmethod
    def KDJ(
        high: pd.Series,
        low: pd.Series,
        close: pd.Series,
        n: int = 9,
        m1: int = 3,
        m2: int = 3
    ) -> Dict[str, pd.Series]:
        """
        KDJ随机指标
        
        Args:
            high: 最高价序列
            low: 最低价序列
            close: 收盘价序列
            n: RSV周期
            m1: K值平滑周期
            m2: D值平滑周期
        
        Returns:
            包含K、D、J的字典
        """
        # 计算RSV
        lowest_low = low.rolling(window=n).min()
        highest_high = high.rolling(window=n).max()
        
        rsv = (close - lowest_low) / (highest_high - lowest_low) * 100
        
        # 计算K、D、J
        K = rsv.ewm(alpha=1/m1, adjust=False).mean()
        D = K.ewm(alpha=1/m2, adjust=False).mean()
        J = 3 * K - 2 * D
        
        return {
            'K': K,
            'D': D,
            'J': J
        }
    
    @staticmethod
    def BOLL(
        prices: pd.Series,
        period: int = 20,
        std_dev: float = 2.0
    ) -> Dict[str, pd.Series]:
        """
        布林带 (Bollinger Bands)
        
        Args:
            prices: 价格序列
            period: 周期
            std_dev: 标准差倍数
        
        Returns:
            包含upper、middle、lower的字典
        """
        middle = TechnicalIndicators.MA(prices, period)
        std = prices.rolling(window=period).std()
        
        upper = middle + std_dev * std
        lower = middle - std_dev * std
        
        return {
            'upper': upper,
            'middle': middle,
            'lower': lower
        }
    
    @staticmethod
    def ATR(
        high: pd.Series,
        low: pd.Series,
        close: pd.Series,
        period: int = 14
    ) -> pd.Series:
        """
        平均真实波幅 (Average True Range)
        
        Args:
            high: 最高价序列
            low: 最低价序列
            close: 收盘价序列
            period: 周期
        
        Returns:
            ATR序列
        """
        tr1 = high - low
        tr2 = abs(high - close.shift(1))
        tr3 = abs(low - close.shift(1))
        
        true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = true_range.rolling(window=period).mean()
        
        return atr
    
    @staticmethod
    def OBV(close: pd.Series, volume: pd.Series) -> pd.Series:
        """
        能量潮指标 (On Balance Volume)
        
        Args:
            close: 收盘价序列
            volume: 成交量序列
        
        Returns:
            OBV序列
        """
        direction = np.sign(close.diff())
        direction.iloc[0] = 0
        obv = (direction * volume).cumsum()
        return obv
    
    @staticmethod
    def VOL_MA(volume: pd.Series, short: int = 5, long: int = 10) -> Dict[str, pd.Series]:
        """
        成交量均线
        
        Args:
            volume: 成交量序列
            short: 短期周期
            long: 长期周期
        
        Returns:
            包含短期和长期成交量均线的字典
        """
        return {
            'vol_ma_short': TechnicalIndicators.MA(volume, short),
            'vol_ma_long': TechnicalIndicators.MA(volume, long)
        }
    
    @staticmethod
    def WR(
        high: pd.Series,
        low: pd.Series,
        close: pd.Series,
        period: int = 14
    ) -> pd.Series:
        """
        威廉指标 (Williams %R)
        
        Args:
            high: 最高价序列
            low: 最低价序列
            close: 收盘价序列
            period: 周期
        
        Returns:
            WR序列 (-100到0)
        """
        highest_high = high.rolling(window=period).max()
        lowest_low = low.rolling(window=period).min()
        
        wr = (highest_high - close) / (highest_high - lowest_low) * -100
        return wr
    
    @staticmethod
    def CCI(
        high: pd.Series,
        low: pd.Series,
        close: pd.Series,
        period: int = 14
    ) -> pd.Series:
        """
        顺势指标 (Commodity Channel Index)
        
        Args:
            high: 最高价序列
            low: 最低价序列
            close: 收盘价序列
            period: 周期
        
        Returns:
            CCI序列
        """
        tp = (high + low + close) / 3
        ma = tp.rolling(window=period).mean()
        md = tp.rolling(window=period).apply(
            lambda x: np.abs(x - x.mean()).mean(), raw=True
        )
        
        cci = (tp - ma) / (0.015 * md)
        return cci
    
    @staticmethod
    def DMI(
        high: pd.Series,
        low: pd.Series,
        close: pd.Series,
        period: int = 14
    ) -> Dict[str, pd.Series]:
        """
        动向指标 (Directional Movement Index)
        
        Args:
            high: 最高价序列
            low: 最低价序列
            close: 收盘价序列
            period: 周期
        
        Returns:
            包含PDI、MDI、ADX、ADXR的字典
        """
        # 计算+DM和-DM
        up = high.diff()
        down = -low.diff()
        
        plus_dm = np.where((up > down) & (up > 0), up, 0)
        minus_dm = np.where((down > up) & (down > 0), down, 0)
        
        # 计算TR
        tr1 = high - low
        tr2 = abs(high - close.shift(1))
        tr3 = abs(low - close.shift(1))
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        
        # 平滑处理
        atr = tr.rolling(window=period).mean()
        plus_di = 100 * pd.Series(plus_dm).rolling(window=period).mean() / atr
        minus_di = 100 * pd.Series(minus_dm).rolling(window=period).mean() / atr
        
        # 计算DX和ADX
        dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di)
        adx = dx.rolling(window=period).mean()
        adxr = (adx + adx.shift(period)) / 2
        
        return {
            'PDI': plus_di,
            'MDI': minus_di,
            'ADX': adx,
            'ADXR': adxr
        }
    
    @staticmethod
    def SAR(
        high: pd.Series,
        low: pd.Series,
        af_start: float = 0.02,
        af_increment: float = 0.02,
        af_max: float = 0.2
    ) -> pd.Series:
        """
        抛物线指标 (Parabolic SAR)
        
        Args:
            high: 最高价序列
            low: 最低价序列
            af_start: 初始加速因子
            af_increment: 加速因子增量
            af_max: 最大加速因子
        
        Returns:
            SAR序列
        """
        sar = pd.Series(index=high.index, dtype=float)
        sar.iloc[0] = low.iloc[0]
        
        # 简化实现,实际应用中需要更复杂的逻辑
        is_long = True
        ep = high.iloc[0]
        af = af_start
        
        for i in range(1, len(high)):
            if is_long:
                sar.iloc[i] = sar.iloc[i-1] + af * (ep - sar.iloc[i-1])
                if low.iloc[i] < sar.iloc[i]:
                    is_long = False
                    sar.iloc[i] = ep
                    ep = low.iloc[i]
                    af = af_start
                else:
                    if high.iloc[i] > ep:
                        ep = high.iloc[i]
                        af = min(af + af_increment, af_max)
            else:
                sar.iloc[i] = sar.iloc[i-1] + af * (ep - sar.iloc[i-1])
                if high.iloc[i] > sar.iloc[i]:
                    is_long = True
                    sar.iloc[i] = ep
                    ep = high.iloc[i]
                    af = af_start
                else:
                    if low.iloc[i] < ep:
                        ep = low.iloc[i]
                        af = min(af + af_increment, af_max)
        
        return sar
    
    @staticmethod
    def BIAS(prices: pd.Series, period: int = 6) -> pd.Series:
        """
        乖离率指标 (Bias)
        
        Args:
            prices: 价格序列
            period: 周期
        
        Returns:
            BIAS序列
        """
        ma = TechnicalIndicators.MA(prices, period)
        bias = (prices - ma) / ma * 100
        return bias
    
    @staticmethod
    def ROC(prices: pd.Series, period: int = 12) -> pd.Series:
        """
        变动率指标 (Rate of Change)
        
        Args:
            prices: 价格序列
            period: 周期
        
        Returns:
            ROC序列
        """
        roc = (prices - prices.shift(period)) / prices.shift(period) * 100
        return roc


class IndicatorAnalyzer:
    """技术指标分析器"""
    
    def __init__(self, df: pd.DataFrame):
        """
        初始化分析器
        
        Args:
            df: 包含OHLCV数据的DataFrame
        """
        self.df = df.copy()
        self.validate_data()
    
    def validate_data(self):
        """验证数据格式"""
        required_columns = ['open', 'high', 'low', 'close', 'volume']
        missing = [col for col in required_columns if col not in self.df.columns]
        
        if missing:
            raise ValueError(f"缺少必需的列: {missing}")
    
    def calculate_all_indicators(
        self,
        ma_periods: List[int] = [5, 10, 20, 60],
        rsi_period: int = 14,
        macd_params: Tuple[int, int, int] = (12, 26, 9),
        boll_period: int = 20,
        kdj_params: Tuple[int, int, int] = (9, 3, 3)
    ) -> pd.DataFrame:
        """
        计算所有常用技术指标
        
        Args:
            ma_periods: MA周期列表
            rsi_period: RSI周期
            macd_params: MACD参数 (fast, slow, signal)
            boll_period: 布林带周期
            kdj_params: KDJ参数 (n, m1, m2)
        
        Returns:
            包含所有指标的DataFrame
        """
        logger.info("开始计算所有技术指标...")
        
        # 移动平均线
        for period in ma_periods:
            self.df[f'MA{period}'] = TechnicalIndicators.MA(self.df['close'], period)
        
        # RSI
        self.df['RSI'] = TechnicalIndicators.RSI(self.df['close'], rsi_period)
        
        # MACD
        macd = TechnicalIndicators.MACD(
            self.df['close'],
            *macd_params
        )
        self.df['MACD'] = macd['macd']
        self.df['MACD_SIGNAL'] = macd['signal']
        self.df['MACD_HIST'] = macd['histogram']
        
        # KDJ
        kdj = TechnicalIndicators.KDJ(
            self.df['high'],
            self.df['low'],
            self.df['close'],
            *kdj_params
        )
        self.df['K'] = kdj['K']
        self.df['D'] = kdj['D']
        self.df['J'] = kdj['J']
        
        # 布林带
        boll = TechnicalIndicators.BOLL(self.df['close'], boll_period)
        self.df['BOLL_UPPER'] = boll['upper']
        self.df['BOLL_MID'] = boll['middle']
        self.df['BOLL_LOWER'] = boll['lower']
        
        # ATR
        self.df['ATR'] = TechnicalIndicators.ATR(
            self.df['high'],
            self.df['low'],
            self.df['close']
        )
        
        # OBV
        self.df['OBV'] = TechnicalIndicators.OBV(
            self.df['close'],
            self.df['volume']
        )
        
        # WR
        self.df['WR'] = TechnicalIndicators.WR(
            self.df['high'],
            self.df['low'],
            self.df['close']
        )
        
        # CCI
        self.df['CCI'] = TechnicalIndicators.CCI(
            self.df['high'],
            self.df['low'],
            self.df['close']
        )
        
        # BIAS
        self.df['BIAS'] = TechnicalIndicators.BIAS(self.df['close'])
        
        # ROC
        self.df['ROC'] = TechnicalIndicators.ROC(self.df['close'])
        
        logger.info(f"技术指标计算完成,共计算 {len(self.df.columns) - 5} 个指标")
        
        return self.df
    
    def get_signals(self) -> Dict[str, pd.Series]:
        """
        根据技术指标生成交易信号
        
        Returns:
            信号字典
        """
        signals = {}
        
        # MACD金叉死叉
        signals['macd_golden_cross'] = (
            (self.df['MACD'] > self.df['MACD_SIGNAL']) & 
            (self.df['MACD'].shift(1) <= self.df['MACD_SIGNAL'].shift(1))
        )
        signals['macd_death_cross'] = (
            (self.df['MACD'] < self.df['MACD_SIGNAL']) & 
            (self.df['MACD'].shift(1) >= self.df['MACD_SIGNAL'].shift(1))
        )
        
        # KDJ金叉死叉
        signals['kdj_golden_cross'] = (
            (self.df['K'] > self.df['D']) & 
            (self.df['K'].shift(1) <= self.df['D'].shift(1))
        )
        signals['kdj_death_cross'] = (
            (self.df['K'] < self.df['D']) & 
            (self.df['K'].shift(1) >= self.df['D'].shift(1))
        )
        
        # RSI超买超卖
        signals['rsi_oversold'] = self.df['RSI'] < 30
        signals['rsi_overbought'] = self.df['RSI'] > 70
        
        # 布林带突破
        signals['boll_breakout_up'] = self.df['close'] > self.df['BOLL_UPPER']
        signals['boll_breakout_down'] = self.df['close'] < self.df['BOLL_LOWER']
        
        return signals
    
    def get_indicator_summary(self) -> Dict[str, Dict]:
        """
        获取指标统计摘要
        
        Returns:
            指标统计摘要字典
        """
        summary = {}
        
        # RSI统计
        if 'RSI' in self.df.columns:
            rsi = self.df['RSI'].dropna()
            summary['RSI'] = {
                'current': rsi.iloc[-1] if len(rsi) > 0 else None,
                'mean': rsi.mean(),
                'std': rsi.std(),
                'oversold_count': (rsi < 30).sum(),
                'overbought_count': (rsi > 70).sum()
            }
        
        # MACD统计
        if 'MACD' in self.df.columns:
            macd = self.df['MACD'].dropna()
            summary['MACD'] = {
                'current': macd.iloc[-1] if len(macd) > 0 else None,
                'mean': macd.mean(),
                'std': macd.std(),
                'positive_count': (macd > 0).sum(),
                'negative_count': (macd < 0).sum()
            }
        
        # KDJ统计
        if 'K' in self.df.columns:
            k = self.df['K'].dropna()
            d = self.df['D'].dropna()
            j = self.df['J'].dropna()
            summary['KDJ'] = {
                'K_current': k.iloc[-1] if len(k) > 0 else None,
                'D_current': d.iloc[-1] if len(d) > 0 else None,
                'J_current': j.iloc[-1] if len(j) > 0 else None,
                'K_mean': k.mean(),
                'D_mean': d.mean()
            }
        
        return summary


def calculate_indicators_for_stock(
    df: pd.DataFrame,
    indicators: List[str] = None
) -> pd.DataFrame:
    """
    为股票数据计算指定指标
    
    Args:
        df: 股票OHLCV数据
        indicators: 要计算的指标列表,默认计算所有
    
    Returns:
        包含指标的DataFrame
    """
    analyzer = IndicatorAnalyzer(df)
    
    if indicators is None:
        return analyzer.calculate_all_indicators()
    else:
        # 根据指定指标计算
        result_df = df.copy()
        
        for indicator in indicators:
            indicator = indicator.upper()
            
            if indicator.startswith('MA'):
                period = int(indicator[2:]) if len(indicator) > 2 else 20
                result_df[indicator] = TechnicalIndicators.MA(df['close'], period)
            
            elif indicator == 'RSI':
                result_df['RSI'] = TechnicalIndicators.RSI(df['close'])
            
            elif indicator == 'MACD':
                macd = TechnicalIndicators.MACD(df['close'])
                result_df['MACD'] = macd['macd']
                result_df['MACD_SIGNAL'] = macd['signal']
                result_df['MACD_HIST'] = macd['histogram']
            
            elif indicator == 'KDJ':
                kdj = TechnicalIndicators.KDJ(df['high'], df['low'], df['close'])
                result_df['K'] = kdj['K']
                result_df['D'] = kdj['D']
                result_df['J'] = kdj['J']
            
            elif indicator == 'BOLL':
                boll = TechnicalIndicators.BOLL(df['close'])
                result_df['BOLL_UPPER'] = boll['upper']
                result_df['BOLL_MID'] = boll['middle']
                result_df['BOLL_LOWER'] = boll['lower']
            
            elif indicator == 'ATR':
                result_df['ATR'] = TechnicalIndicators.ATR(
                    df['high'], df['low'], df['close']
                )
            
            elif indicator == 'OBV':
                result_df['OBV'] = TechnicalIndicators.OBV(df['close'], df['volume'])
        
        return result_df
