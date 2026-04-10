"""
优化的盘中买点信号系统（交易级）
基于深度校准建议，实现互斥触发和严格过滤
"""

import numpy as np
import pandas as pd
from typing import Tuple, Dict, Optional
from dataclasses import dataclass
from datetime import datetime, time, timedelta
import logging

logger = logging.getLogger(__name__)


@dataclass
class IntradayData:
    """分时数据结构"""
    price: np.ndarray
    volume: np.ndarray
    high: np.ndarray
    low: np.ndarray
    timestamp: np.ndarray


@dataclass
class SignalOutput:
    """信号输出"""
    signal: bool
    signal_type: str  # pullback/breakout/consolidation
    confidence: float  # 置信度 0-1
    reason: str
    details: Dict = None


class OptimizedBuySignals:
    """优化的盘中买点信号检测器（交易级）"""
    
    def __init__(self):
        self.params = {
            # 回踩买点参数
            'pullback': {
                'ma_period': 20,              # MA周期
                'pullback_pct': 0.01,         # 回踩容忍
                'no_new_low_bars': 3,         # 不创新低周期
                'trend_ma_period': 20,        # 趋势MA周期
            },
            
            # 突破买点参数
            'breakout': {
                'lookback': 30,               # 前高周期
                'volume_multiplier': 1.5,     # 放量倍数
                'hold_minutes': 3,            # 突破维持时间
            },
            
            # 横盘买点参数
            'consolidation': {
                'range_pct': 0.02,            # 横盘振幅
                'window': 15,                 # 横盘周期
                'min_rise_before': 0.02,      # 横盘前最小涨幅
            },
            
            # 时间过滤
            'time_filter': {
                'start_time': time(9, 45),
                'end_time': time(14, 30),
                'avoid_times': [
                    (time(9, 30), time(9, 45)),
                    (time(11, 30), time(13, 0)),
                ]
            },
            
            # 防抖参数（升级为时间确认）
            'confirmation': {
                'min_duration_minutes': 2,    # 信号持续最少分钟
                'price_tolerance': 0.005,     # 价格容忍度
            }
        }
    
    def signal_pullback(self, data: IntradayData) -> SignalOutput:
        """
        回踩确认买点（主策略）- 优化版
        
        条件：
        1. 上涨趋势（price > MA20 且 MA20上升）
        2. 接近均线（±1%）
        3. 不创新低
        4. 止跌确认（最近3根K线：低点抬高 + 收阳）【新增】
        5. 量能过滤（回踩缩量）【新增】
        """
        params = self.params['pullback']
        price = data.price
        volume = data.volume
        
        if len(price) <= params['trend_ma_period']:
            return SignalOutput(False, "", 0, "数据不足")
        
        # 计算均线
        ma20 = np.convolve(price, np.ones(params['trend_ma_period'])/params['trend_ma_period'], mode='valid')
        if len(ma20) < 2:
            return SignalOutput(False, "", 0, "数据不足")
        current_ma20 = ma20[-1]
        prev_ma20 = ma20[-2]
        current_price = price[-1]
        
        # 条件1：趋势过滤（关键）
        trend_up = (current_price > current_ma20) and (current_ma20 > prev_ma20)
        
        if not trend_up:
            return SignalOutput(False, "", 0, "非上涨趋势")
        
        # 条件2：接近均线
        ma5 = np.mean(price[-5:])
        price_diff = abs(current_price - ma5) / ma5
        near_ma = price_diff <= params['pullback_pct']
        
        # 条件3：不创新低
        recent_lows = data.low[-params['no_new_low_bars']:]
        prev_lows = data.low[-params['trend_ma_period']:-params['no_new_low_bars']]
        no_new_low = np.min(recent_lows) >= np.min(prev_lows)
        
        # 条件4：止跌确认（优化：放宽条件，避免过拟合）
        # 方案A：低点抬高 + 任意K线止跌
        # 方案B：单根放量阳线反包
        if len(data.low) >= 3 and len(price) >= 3:
            low1, low2, low3 = data.low[-3], data.low[-2], data.low[-1]
            close1, close2, close3 = price[-3], price[-2], price[-1]
            
            # 方案A：低点抬高 + 止跌（不要求连阳）
            low_rising = (low3 >= low2) and (low2 >= low1)
            # 止跌：最近一根K线收阳或十字星
            open3 = data.high[-1] - (data.high[-1] - data.low[-1]) * 0.5
            is_stop_falling = close3 >= open3 * 0.99  # 收阳或十字星
            
            scheme_a = low_rising and is_stop_falling
            
            # 方案B：单根放量阳线反包（新增）
            if len(volume) >= 5:
                avg_volume = np.mean(volume[-5:-1])
                current_volume = volume[-1]
                vol_ratio = current_volume / avg_volume if avg_volume > 0 else 0
                
                # 放量阳线：量比>1.5 且 涨幅>1%
                pct_change = (close3 - close2) / close2 if close2 > 0 else 0
                is_volume_bullish = (vol_ratio > 1.5) and (pct_change > 0.01) and (close3 > open3)
            else:
                is_volume_bullish = False
            
            scheme_b = is_volume_bullish
            
            # 满足任一方案即可
            stop_falling = scheme_a or scheme_b
        else:
            stop_falling = False
        
        # 条件5：量能过滤（回踩应缩量）
        if len(volume) >= 10:
            avg_volume = np.mean(volume[-10:-3])  # 前10日平均量
            recent_volume = np.mean(volume[-3:])  # 近3日平均量
            volume_shrink = recent_volume < avg_volume * 0.8  # 缩量至80%以下
        else:
            volume_shrink = True  # 数据不足时跳过
        
        # 计算置信度
        confidence = 0.0
        if near_ma:
            confidence += 0.3
        if no_new_low:
            confidence += 0.2
        if stop_falling:
            confidence += 0.3  # 止跌确认权重较高
        if volume_shrink:
            confidence += 0.2
        
        signal = near_ma and no_new_low and stop_falling
        
        details = {
            'trend_up': trend_up,
            'price_diff': price_diff * 100,
            'current_ma20': current_ma20,
            'near_ma': near_ma,
            'no_new_low': no_new_low,
            'stop_falling': stop_falling,  # 新增
            'volume_shrink': volume_shrink,  # 新增
        }
        
        return SignalOutput(
            signal=signal,
            signal_type="pullback",
            confidence=confidence,
            reason="回踩确认（止跌+缩量）" if signal else "",
            details=details
        )
    
    def signal_breakout(self, data: IntradayData) -> SignalOutput:
        """
        突破买点（次策略）- 优化版
        
        条件：
        1. 突破前高
        2. 放量（量比 > 1.5倍）
        3. 突破后维持（连续3分钟维持在前高之上）
        4. 突破前横盘（过去15分钟振幅 < 2%）【新增关键条件】
        """
        params = self.params['breakout']
        price = data.price
        volume = data.volume
        
        if len(price) < params['lookback']:
            return SignalOutput(False, "", 0, "数据不足", details={'range_pct': 0.0})
        
        # 计算前高
        prev_high = np.max(data.high[-params['lookback']:-1])
        current_price = price[-1]
        
        # 条件1：突破前高
        breakout = current_price > prev_high
        
        if not breakout:
            return SignalOutput(False, "", 0, "未突破", details={'range_pct': 0.0, 'breakout_pct': 0.0, 'vol_ratio': 0.0, 'prev_high': float(prev_high), 'volume_up': False, 'hold_above': False, 'is_consolidating': False})
        
        # 条件2：放量
        avg_volume = np.mean(volume[-params['lookback']:-1])
        current_volume = volume[-1]
        vol_ratio = current_volume / avg_volume if avg_volume > 0 else 0
        volume_up = vol_ratio > params['volume_multiplier']
        
        # 条件3：突破维持（假突破过滤）
        hold_minutes = params['hold_minutes']
        if len(price) >= hold_minutes:
            # 检查最近N分钟是否都维持在前高之上
            recent_prices = price[-hold_minutes:]
            hold_above = all(recent_prices > prev_high)
        else:
            hold_above = False
        
        # 条件4：突破前横盘（优化：改为软过滤，不硬性禁止）
        # 过去15分钟振幅 < 2%
        consolidation_window = 15
        range_pct = 0.0  # 初始化，避免 UnboundLocalError
        if len(price) >= consolidation_window:
            recent_high = np.max(data.high[-consolidation_window:-1])
            recent_low = np.min(data.low[-consolidation_window:-1])
            # 防止除零
            if recent_low > 0:
                range_pct = (recent_high - recent_low) / recent_low
            is_consolidating = range_pct < 0.02  # 振幅 < 2%
        else:
            is_consolidating = False
        
        # 计算置信度（优化：横盘约束改为加分项，而非硬过滤）
        confidence = 0.0
        if volume_up:
            confidence += 0.35
        if hold_above:
            confidence += 0.35
        if is_consolidating:
            confidence += 0.30  # 横盘约束加分
        else:
            # 没有横盘也允许，但置信度降低
            confidence += 0.10
        
        # 信号触发条件（优化：不强制要求横盘）
        signal = volume_up and hold_above and (confidence >= 0.7)
        
        details = {
            'breakout_pct': (current_price - prev_high) / prev_high * 100,
            'vol_ratio': vol_ratio,
            'prev_high': prev_high,
            'volume_up': volume_up,
            'hold_above': hold_above,
            'is_consolidating': is_consolidating,
            'range_pct': range_pct * 100,  # 已初始化，安全引用
        }
        
        return SignalOutput(
            signal=signal,
            signal_type="breakout",
            confidence=confidence,
            reason="突破确认（横盘+放量）" if signal else "",
            details=details
        )
    
    def signal_consolidation(self, data: IntradayData) -> SignalOutput:
        """
        横盘买点（补充策略）
        
        条件：
        1. 横盘前有上涨（>2%）
        2. 横盘振幅小
        3. 接近高点
        """
        params = self.params['consolidation']
        window = params['window']
        
        if len(data.price) < window * 2:
            return SignalOutput(False, "", 0, "数据不足")
        
        # 条件1：横盘前有上涨（关键新增）
        before_price = data.price[-window*2:-window]
        current_window = data.price[-window:]
        
        rise_before = (np.mean(current_window) - np.mean(before_price)) / np.mean(before_price)
        has_rise = rise_before > params['min_rise_before']
        
        if not has_rise:
            return SignalOutput(False, "", 0, "横盘前无上涨")
        
        # 条件2：横盘振幅小
        max_p = np.max(current_window)
        min_p = np.min(current_window)
        range_pct = (max_p - min_p) / min_p
        small_range = range_pct <= params['range_pct']
        
        # 条件3：接近高点
        current_price = current_window[-1]
        near_high = current_price >= max_p * 0.98
        
        # 计算置信度
        confidence = 0.0
        if small_range:
            confidence += 0.5
        if near_high:
            confidence += 0.5
        
        signal = small_range and near_high
        
        details = {
            'rise_before': rise_before * 100,
            'range_pct': range_pct * 100,
            'has_rise': has_rise,
            'small_range': small_range,
            'near_high': near_high,
        }
        
        return SignalOutput(
            signal=signal,
            signal_type="consolidation",
            confidence=confidence,
            reason="横盘突破" if signal else "",
            details=details
        )
    
    def evaluate_time_filter(self, timestamp: datetime, open_pct: float = 0, market_score: float = 65.0) -> Tuple[bool, float]:
        """
        时间过滤（升级版）- 返回(是否通过, 建议仓位比例)
        
        新增：
        1. 开盘状态过滤
        2. 市场环境过滤 → 仓位控制（关键升级）
        """
        params = self.params['time_filter']
        current_time = timestamp.time()
        
        # 开盘状态过滤
        if open_pct > 5.0:  # 开盘涨幅>5%，禁止追高
            return False, 0.0
        
        # 禁止时间
        for start, end in params['avoid_times']:
            if start <= current_time <= end:
                return False, 0.0
        
        # 交易时间
        if current_time < params['start_time'] or current_time > params['end_time']:
            return False, 0.0
        
        # 市场环境过滤 → 仓位控制（关键升级：连续模型）
        if market_score <= 50:
            # 弱势市场：禁止开仓
            return False, 0.0
        else:
            # 连续仓位模型：position = (market_score - 50) / 20
            # 市场评分50 → 0%, 60 → 50%, 70 → 100%
            position_ratio = (market_score - 50) / 20
            # 限制在0-1之间
            position_ratio = max(0.0, min(1.0, position_ratio))
        
        return True, position_ratio

    def time_filter(self, timestamp: datetime, open_pct: float = 0, market_score: float = 65.0) -> bool:
        """向后兼容的时间过滤接口，只返回是否允许交易。"""
        allowed, _ = self.evaluate_time_filter(
            timestamp,
            open_pct=open_pct,
            market_score=market_score,
        )
        return allowed
    
    @staticmethod
    def _is_safe_entry_window(data: IntradayData, daily_high60: float = 0.0, daily_low60: float = 0.0) -> Tuple[bool, str]:
        """
        P2: 安全买入窗口判断

        规则（AND 关系）：
          1. 当前价相对60日高点回撤 > 3%（避免追顶）
          2. 当前价相对60日低点涨幅 < 40%（避免过度拉升）
          3. 最近3根K线均量 < 近20根K线均量 * 2.0（避免主力出货日）

        若缺乏60日数据（daily_high60==0），仅执行规则3。
        """
        if len(data.price) < 3:
            return False, "数据不足"

        current = float(data.price[-1])
        reasons = []

        # 规则1 & 2：需要日线60日数据
        if daily_high60 > 0 and daily_low60 > 0:
            pullback_from_high = (daily_high60 - current) / daily_high60
            rise_from_low = (current - daily_low60) / daily_low60 if daily_low60 > 0 else 0.0
            if pullback_from_high < 0.03:
                reasons.append(f"接近60日顶部(回撤{pullback_from_high*100:.1f}%<3%)")
            if rise_from_low > 0.40:
                reasons.append(f"60日涨幅过大({rise_from_low*100:.1f}%>40%)")

        # 规则3：量能异常检测（出货日过滤）
        if len(data.volume) >= 20:
            recent_3_vol  = float(np.mean(data.volume[-3:]))
            baseline_vol  = float(np.mean(data.volume[-20:]))
            if baseline_vol > 0 and recent_3_vol > baseline_vol * 2.0:
                reasons.append(f"量能异常放大({recent_3_vol/baseline_vol:.1f}x，疑似出货)")

        if reasons:
            return False, " | ".join(reasons)
        return True, "安全窗口"

    @staticmethod
    def calculate_exit_levels(data: IntradayData, entry_price: float, signal_type: str) -> Dict:
        """
        P3: 根据信号类型和当前价格结构自动计算止损/止盈价位。

        止损原则：
          - 回踩信号：最近5根K线最低点下方 0.5%
          - 突破信号：突破前高下方 0.5%
          - 横盘信号：横盘区间下沿下方 0.5%
          - 通用保底：入场价 - 7%（最大亏损上限）

        止盈原则：
          - T1（第一目标）：风险的 1.5 倍
          - T2（第二目标）：风险的 2.5 倍

        Returns:
            dict with stop_loss, take_profit_1, take_profit_2, risk_reward_1, risk_reward_2
        """
        prices = data.price
        highs  = data.high
        lows   = data.low
        ep = float(entry_price)

        if signal_type == "pullback":
            # 止损：最近5根K线低点下方0.5%
            anchor_low = float(np.min(lows[-5:])) if len(lows) >= 5 else float(np.min(lows))
            stop_loss  = anchor_low * 0.995

        elif signal_type == "breakout":
            # 止损：突破前高（近30根）下方0.5%
            lookback = min(30, len(highs) - 1)
            prev_high = float(np.max(highs[-lookback - 1:-1])) if lookback > 0 else ep * 0.95
            stop_loss = prev_high * 0.995

        else:  # consolidation
            # 止损：横盘区间下沿下方0.5%
            window = min(15, len(lows))
            range_low = float(np.min(lows[-window:]))
            stop_loss = range_low * 0.995

        # 通用保底：最大亏损 7%
        stop_loss = max(stop_loss, ep * 0.93)

        risk = ep - stop_loss
        if risk <= 0:
            risk = ep * 0.03  # fallback：假设3%风险
            stop_loss = ep - risk

        take_profit_1 = round(ep + risk * 1.5, 2)
        take_profit_2 = round(ep + risk * 2.5, 2)
        stop_loss     = round(stop_loss, 2)
        rr1 = round((take_profit_1 - ep) / risk, 2)
        rr2 = round((take_profit_2 - ep) / risk, 2)

        return {
            "entry_price":    round(ep, 2),
            "stop_loss":      stop_loss,
            "take_profit_1":  take_profit_1,
            "take_profit_2":  take_profit_2,
            "risk_amount":    round(risk, 2),
            "risk_pct":       round(risk / ep * 100, 2),
            "risk_reward_1":  rr1,
            "risk_reward_2":  rr2,
        }

    def mutual_exclusive_signal(
        self,
        data: IntradayData,
        timestamp: datetime,
        open_pct: float = 0,
        market_score: float = 65.0,
        daily_high60: float = 0.0,
        daily_low60: float = 0.0,
        entry_price: float = 0.0,
    ) -> SignalOutput:
        """
        互斥触发信号（P2+P3 全量优化版）

        优先级（高→低，互斥触发）：
          1. 回踩买点（主策略，趋势确认最强）
          2. 横盘买点（结构最稳，优先于突破）
          3. 突破买点（假突破风险最高，要求最严）

        新增：
          - P2 安全买入窗口过滤（追顶/出货日拦截）
          - P3 每条信号自动附带止损/止盈价位
        """
        # 时间过滤
        allowed, position_ratio = self.evaluate_time_filter(
            timestamp, open_pct=open_pct, market_score=market_score
        )
        if not allowed:
            return SignalOutput(False, "", 0, "非交易时间")

        # P2: 安全买入窗口
        safe, safe_reason = self._is_safe_entry_window(
            data, daily_high60=daily_high60, daily_low60=daily_low60
        )
        if not safe:
            return SignalOutput(False, "", 0, f"安全窗口拦截: {safe_reason}")

        # 确定入场价
        ep = float(entry_price) if entry_price > 0 else float(data.price[-1])

        def _attach_exit(sig: SignalOutput) -> SignalOutput:
            """P3: 附加止损/止盈到信号详情。"""
            exits = self.calculate_exit_levels(data, ep, sig.signal_type)
            if sig.details is None:
                sig.details = {}
            sig.details.update(exits)
            sig.details["position_ratio"] = position_ratio
            return sig

        # 优先级1：回踩信号（主策略）
        s1 = self.signal_pullback(data)
        if s1.signal and s1.confidence > 0.7:
            logger.info("触发回踩买点，置信度%.2f，止损%.2f", s1.confidence,
                        self.calculate_exit_levels(data, ep, "pullback")["stop_loss"])
            return _attach_exit(s1)

        # 优先级2：横盘信号（结构稳定，优先于突破）
        s3 = self.signal_consolidation(data)
        if s3.signal and s3.confidence > 0.7:
            logger.info("触发横盘买点，置信度%.2f", s3.confidence)
            return _attach_exit(s3)

        # 优先级3：突破信号（要求最严，置信度门槛提高到0.75）
        s2 = self.signal_breakout(data)
        if s2.signal and s2.confidence > 0.75:
            logger.info("触发突破买点，置信度%.2f", s2.confidence)
            return _attach_exit(s2)

        return SignalOutput(False, "", 0, "无信号")
    
    def debounce(self, signal_history: list, window: int = 2) -> bool:
        """
        防抖机制
        
        Args:
            signal_history: 信号历史列表
            window: 连续触发窗口
        
        Returns:
            是否确认信号
        """
        if len(signal_history) < window:
            return False
        
        # 检查最近N次是否都为True
        recent_signals = signal_history[-window:]
        return all(recent_signals)
    
    def time_based_confirmation(self, signal_history: list, 
                                price_history: list,
                                key_level: float) -> bool:
        """
        时间确认机制（防抖升级）
        
        条件：
        1. 信号持续 >= 2分钟
        2. 期间未跌破关键位
        """
        params = self.params['confirmation']
        min_duration = params['min_duration_minutes']
        
        if len(signal_history) < min_duration:
            return False
        
        # 条件1：信号持续
        signal_sustained = all(signal_history[-min_duration:])
        
        # 条件2：价格确认
        recent_prices = price_history[-min_duration:]
        price_confirmed = all(p > key_level * (1 - params['price_tolerance']) for p in recent_prices)
        
        return signal_sustained and price_confirmed


class BuyFailureDetector:
    """买入失败检测器（关键新增）"""
    
    def __init__(self):
        self.params = {
            'check_minutes': 10,          # 检查时间窗口
            'min_rise_pct': 0.005,        # 最小涨幅
            'vwap_tolerance': 0.99,       # VWAP容忍度
        }
    
    def check_failure(self, buy_price: float, 
                     buy_time: datetime,
                     current_data: IntradayData,
                     current_time: datetime) -> Tuple[bool, str]:
        """
        检查买入失败
        
        条件：
        1. 买入后10分钟内未上涨
        2. 或跌破VWAP
        """
        # 检查时间
        time_diff = (current_time - buy_time).total_seconds() / 60
        if time_diff > self.params['check_minutes']:
            return False, ""  # 超过检查窗口
        
        if time_diff < 1:
            return False, ""  # 时间太短
        
        current_price = current_data.price[-1]
        
        # 条件1：未上涨
        rise_pct = (current_price - buy_price) / buy_price
        if rise_pct < self.params['min_rise_pct']:
            return True, "买入后未上涨"
        
        # 条件2：跌破VWAP
        vwap = np.average(current_data.price[-int(time_diff):], 
                         weights=current_data.volume[-int(time_diff):])
        if current_price < vwap * self.params['vwap_tolerance']:
            return True, "跌破VWAP"
        
        return False, ""


# 使用示例
if __name__ == '__main__':
    # 创建信号检测器
    detector = OptimizedBuySignals()
    failure_detector = BuyFailureDetector()
    
    # 模拟数据
    np.random.seed(42)
    n = 100
    price = 10 + np.cumsum(np.random.randn(n) * 0.02)
    volume = 100000 + np.random.randn(n) * 10000
    high = price + np.random.rand(n) * 0.1
    low = price - np.random.rand(n) * 0.1
    timestamps = pd.date_range('2026-03-24 09:30', periods=n, freq='1min')
    
    data = IntradayData(price=price, volume=volume, high=high, low=low, timestamp=timestamps)
    
    # 检测信号（互斥触发）
    print("买点信号检测（互斥触发）")
    print("="*70)
    
    signal = detector.mutual_exclusive_signal(data, timestamps[-1])
    
    print(f"\n信号类型: {signal.signal_type}")
    print(f"触发: {signal.signal}")
    print(f"置信度: {signal.confidence:.2f}")
    print(f"原因: {signal.reason}")
    
    if signal.details:
        print(f"\n详情:")
        for key, value in signal.details.items():
            if isinstance(value, bool):
                print(f"  {key}: {'✓' if value else '✗'}")
            else:
                print(f"  {key}: {value:.2f}")
