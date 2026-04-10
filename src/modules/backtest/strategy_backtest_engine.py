# -*- coding: utf-8 -*-
"""
策略验证回测引擎
核心目标：验证选股策略与日内买点策略的有效性
移除：仓位计算、头寸限制、资金分配等仓位控制逻辑
保留：信号检测、时间对齐、T+1约束、止盈止损策略
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from collections import defaultdict
from enum import Enum

from src.core.logger import get_logger
from src.modules.backtest.history_recommendation_db import HistoryRecommendationDB

logger = get_logger("strategy_backtest_engine")


class StockState(Enum):
    """股票状态枚举"""
    WATCH = "watch"        # 观察中
    HOLDING = "holding"    # 持仓中
    COOLDOWN = "cooldown"  # 冷却期


@dataclass
class Trade:
    """交易记录"""
    symbol: str
    name: str
    entry_time: datetime
    entry_price: float
    exit_time: datetime = None
    exit_price: float = None
    pnl_pct: float = 0.0
    holding_minutes: float = 0.0
    signal_type: str = ""
    signal_score: float = 0.0
    exit_reason: str = ""
    highest_price: float = 0.0


@dataclass
class Position:
    """持仓信息"""
    symbol: str
    name: str
    entry_price: float
    entry_time: datetime
    entry_date: str
    highest_price: float = 0.0
    trailing_stop_price: float = 0.0


@dataclass
class StockStateInfo:
    """股票状态信息"""
    symbol: str
    state: StockState = StockState.WATCH
    cooldown_until: datetime = None
    last_signal_score: float = 0.0


@dataclass
class Signal:
    """交易信号"""
    symbol: str
    signal_type: str
    direction: str
    score: float
    price: float
    time: datetime
    reason: str = ""


@dataclass
class BacktestConfig:
    """回测配置（仅策略相关参数）"""
    window_size: int = 50
    signal_window: int = 20
    stop_loss_pct: float = -0.03
    take_profit_pct: float = 0.05
    trailing_stop_pct: float = 0.02
    trailing_stop_activate: float = 0.03
    cooldown_minutes: int = 60
    min_signal_score: float = 0.3
    max_holding_days: int = 5


class StrategyBacktestEngine:
    """策略验证回测引擎"""
    
    def __init__(self, db: HistoryRecommendationDB = None, config: BacktestConfig = None):
        if db is None:
            db = HistoryRecommendationDB()
        if config is None:
            config = BacktestConfig()
        
        self.db = db
        self.config = config
        
        self.positions: Dict[str, Position] = {}
        self.trades: List[Trade] = []
        
        self.data_windows: Dict[str, List[Dict]] = defaultdict(list)
        self.stock_states: Dict[str, StockStateInfo] = {}
        
        self.pending_buy_signals: List[Signal] = []
        self.pending_sell_signals: List[Signal] = []
        
        self.stats = {
            'total_trades': 0,
            'win_trades': 0,
            'loss_trades': 0,
            'total_pnl_pct': 0.0,
            'avg_pnl_pct': 0.0,
        }
        
        logger.info("策略验证回测引擎初始化完成")
    
    def run(self, start_date: str, end_date: str, show_progress: bool = True) -> Dict:
        """
        运行回测
        
        Args:
            start_date: 开始日期 (YYYY-MM-DD)
            end_date: 结束日期 (YYYY-MM-DD)
            show_progress: 是否显示进度
        """
        logger.info("=" * 70)
        logger.info("开始策略验证回测")
        logger.info(f"时间范围: {start_date} ~ {end_date}")
        logger.info("=" * 70)
        
        recommendations = self._load_recommendations(start_date, end_date)
        
        if not recommendations:
            logger.warning("无推荐记录")
            return self._get_results()
        
        recommendations_df = pd.DataFrame(recommendations)
        recommendations_df['recommendation_date'] = pd.to_datetime(recommendations_df['recommendation_date'])
        
        all_dates = sorted(recommendations_df['recommendation_date'].unique())
        
        for i, rec_date in enumerate(all_dates):
            trade_date = rec_date + timedelta(days=1)
            trade_date_str = trade_date.strftime('%Y-%m-%d')
            
            prev_date = rec_date.strftime('%Y-%m-%d')
            day_recs = recommendations_df[recommendations_df['recommendation_date'] == prev_date]
            candidates = day_recs['symbol'].tolist()
            
            all_symbols = list(set(candidates + list(self.positions.keys())))
            
            if not all_symbols:
                continue
            
            intraday_data = self._load_intraday_data(all_symbols, trade_date_str)
            
            if intraday_data.empty:
                continue
            
            if show_progress:
                logger.info(f"[{i+1}/{len(all_dates)}] {trade_date_str} | 候选: {len(candidates)}只 | 持仓: {len(self.positions)}只")
            
            self._run_single_day(trade_date, candidates, intraday_data)
        
        self._force_close_positions()
        self._calculate_results()
        
        logger.info("=" * 70)
        logger.info("策略验证回测完成")
        logger.info("=" * 70)
        
        return self._get_results()
    
    def _run_single_day(self, trade_date: datetime, candidates: List[str], 
                        intraday_data: pd.DataFrame):
        """单日回测"""
        trade_date_str = trade_date.strftime('%Y-%m-%d')
        
        for symbol in candidates:
            if symbol not in self.stock_states:
                self.stock_states[symbol] = StockStateInfo(symbol=symbol)
        
        grouped = intraday_data.groupby('trade_time')
        
        for trade_time, group in grouped:
            bars = {}
            for _, row in group.iterrows():
                symbol = row['symbol']
                bars[symbol] = {
                    'open': row['open'],
                    'high': row['high'],
                    'low': row['low'],
                    'close': row['close'],
                    'volume': row['volume'],
                    'amount': row.get('amount', 0),
                }
            
            self._update_data_windows(bars)
            
            self._update_cooldown_states(trade_time)
            
            self._update_position_tracking(bars)
            
            self.pending_buy_signals = []
            self.pending_sell_signals = []
            
            for symbol in list(self.positions.keys()):
                if symbol in bars:
                    sell_signal = self._check_sell_signal(symbol, bars[symbol], trade_time)
                    if sell_signal:
                        self.pending_sell_signals.append(sell_signal)
            
            for symbol in candidates:
                if symbol in bars and symbol not in self.positions:
                    state_info = self.stock_states.get(symbol)
                    if state_info and state_info.state == StockState.COOLDOWN:
                        continue
                    
                    buy_signal = self._check_buy_signal(symbol, bars[symbol], trade_time)
                    if buy_signal:
                        self.pending_buy_signals.append(buy_signal)
            
            self._execute_sell_signals(bars, trade_time, trade_date_str)
            
            self._execute_buy_signals(bars, trade_time)
    
    def _update_data_windows(self, bars: Dict[str, Dict]):
        """更新数据窗口（跨日连续）"""
        for symbol, bar in bars.items():
            self.data_windows[symbol].append(bar)
            
            max_window = max(self.config.window_size, self.config.signal_window * 2)
            if len(self.data_windows[symbol]) > max_window:
                self.data_windows[symbol] = self.data_windows[symbol][-max_window:]
    
    def _update_cooldown_states(self, current_time: datetime):
        """更新冷却状态"""
        for symbol, state_info in self.stock_states.items():
            if state_info.state == StockState.COOLDOWN:
                if state_info.cooldown_until and current_time >= state_info.cooldown_until:
                    state_info.state = StockState.WATCH
                    state_info.cooldown_until = None
                    logger.debug(f"{symbol} 冷却结束，恢复观察状态")
    
    def _update_position_tracking(self, bars: Dict[str, Dict]):
        """更新持仓跟踪（跟踪止盈）"""
        for symbol, position in self.positions.items():
            if symbol not in bars:
                continue
            
            current_price = bars[symbol]['close']
            
            if current_price > position.highest_price:
                position.highest_price = current_price
                
                pnl_pct = (current_price - position.entry_price) / position.entry_price
                if pnl_pct >= self.config.trailing_stop_activate:
                    new_trailing_stop = current_price * (1 - self.config.trailing_stop_pct)
                    if new_trailing_stop > position.trailing_stop_price:
                        position.trailing_stop_price = new_trailing_stop
                        logger.debug(f"{symbol} 更新跟踪止损: {new_trailing_stop:.2f}")
    
    def _check_buy_signal(self, symbol: str, bar: Dict, 
                          current_time: datetime) -> Optional[Signal]:
        """买入信号检测（使用t-1数据）"""
        window = self.data_windows.get(symbol, [])
        
        if len(window) < self.config.signal_window:
            return None
        
        prev_window = window[:-1]
        if len(prev_window) < self.config.signal_window:
            return None
        
        prev_prices = np.array([x['close'] for x in prev_window])
        current_price = bar['open']
        
        signal_type, score = self._evaluate_buy_signals(prev_prices, prev_window, current_price)
        
        if signal_type and score >= self.config.min_signal_score:
            return Signal(
                symbol=symbol,
                signal_type=signal_type,
                direction='buy',
                score=score,
                price=current_price,
                time=current_time,
                reason=signal_type
            )
        
        return None
    
    def _evaluate_buy_signals(self, prev_prices: np.ndarray, prev_window: List[Dict], 
                              current_price: float) -> Tuple[str, float]:
        """评估买入信号"""
        ma5 = prev_prices[-5:].mean()
        ma10 = prev_prices[-10:].mean() if len(prev_prices) >= 10 else ma5
        ma20 = prev_prices[-20:].mean() if len(prev_prices) >= 20 else ma10
        
        last_price = prev_prices[-1]
        
        if last_price > ma20:
            if abs(last_price - ma5) / ma5 < 0.015:
                lows = [x['low'] for x in prev_window[-4:]]
                older_lows = [x['low'] for x in prev_window[-11:-4]] if len(prev_window) >= 11 else lows
                
                if min(lows) >= min(older_lows):
                    trend_score = (last_price - ma20) / ma20
                    strength_score = (last_price - prev_prices[-20:].min()) / (prev_prices[-20:].max() - prev_prices[-20:].min() + 0.001)
                    score = min(0.3 + trend_score * 2 + strength_score * 0.5, 1.0)
                    return "回踩均线", round(score, 2)
        
        recent_high = prev_prices[-20:].max()
        if last_price > recent_high * 1.005:
            breakout_strength = (last_price - recent_high) / recent_high
            volume_ratio = 1.0
            if len(prev_window) >= 5:
                recent_vol = prev_window[-1].get('volume', 0)
                avg_vol = np.mean([x.get('volume', 0) for x in prev_window[-5:]])
                if avg_vol > 0:
                    volume_ratio = recent_vol / avg_vol
            
            score = min(0.4 + breakout_strength * 10 + (volume_ratio - 1) * 0.2, 1.0)
            return "突破前高", round(score, 2)
        
        if last_price > ma5 > ma10 > ma20:
            trend_strength = (last_price - ma20) / ma20
            ma_spread = (ma5 - ma20) / ma20
            score = min(0.3 + trend_strength * 2 + ma_spread * 2, 1.0)
            return "趋势跟随", round(score, 2)
        
        return None, 0.0
    
    def _check_sell_signal(self, symbol: str, bar: Dict, 
                           current_time: datetime) -> Optional[Signal]:
        """卖出信号检测"""
        if symbol not in self.positions:
            return None
        
        position = self.positions[symbol]
        current_price = bar['open']
        
        pnl_pct = (current_price - position.entry_price) / position.entry_price
        
        if pnl_pct <= self.config.stop_loss_pct:
            return Signal(
                symbol=symbol,
                signal_type="止损",
                direction='sell',
                score=1.0,
                price=current_price,
                time=current_time,
                reason=f"触发止损 ({pnl_pct*100:.2f}%)"
            )
        
        if pnl_pct >= self.config.take_profit_pct:
            return Signal(
                symbol=symbol,
                signal_type="止盈",
                direction='sell',
                score=0.9,
                price=current_price,
                time=current_time,
                reason=f"触发止盈 ({pnl_pct*100:.2f}%)"
            )
        
        if position.trailing_stop_price > 0:
            if current_price <= position.trailing_stop_price:
                return Signal(
                    symbol=symbol,
                    signal_type="跟踪止盈",
                    direction='sell',
                    score=0.85,
                    price=current_price,
                    time=current_time,
                    reason=f"触发跟踪止盈 (最高{position.highest_price:.2f})"
                )
        
        window = self.data_windows.get(symbol, [])
        if len(window) >= 5:
            prev_prices = [x['close'] for x in window[-5:-1]]
            if prev_prices and current_price < min(prev_prices) * 0.97:
                return Signal(
                    symbol=symbol,
                    signal_type="快速下跌",
                    direction='sell',
                    score=0.8,
                    price=current_price,
                    time=current_time,
                    reason="快速下跌超过3%"
                )
        
        if len(window) >= 20:
            prev_prices = np.array([x['close'] for x in window[-20:-1]])
            ma5 = prev_prices[-5:].mean()
            ma20 = prev_prices[-20:].mean()
            
            if current_price < ma5 and current_price < ma20:
                return Signal(
                    symbol=symbol,
                    signal_type="趋势转弱",
                    direction='sell',
                    score=0.7,
                    price=current_price,
                    time=current_time,
                    reason="跌破均线支撑"
                )
        
        holding_days = (current_time.date() - position.entry_time.date()).days
        if holding_days >= self.config.max_holding_days:
            return Signal(
                symbol=symbol,
                signal_type="超时平仓",
                direction='sell',
                score=0.6,
                price=current_price,
                time=current_time,
                reason=f"持仓超过{self.config.max_holding_days}天"
            )
        
        return None
    
    def _execute_sell_signals(self, bars: Dict[str, Dict], trade_time: datetime, 
                               trade_date_str: str):
        """执行卖出信号"""
        for signal in self.pending_sell_signals:
            symbol = signal.symbol
            
            if symbol not in self.positions:
                continue
            
            if not self._check_t_plus_1(symbol, trade_date_str):
                logger.debug(f"{symbol} T+1限制，无法卖出")
                continue
            
            bar = bars.get(symbol)
            if not bar:
                continue
            
            self._execute_sell(symbol, bar, trade_time, signal.signal_type)
    
    def _execute_buy_signals(self, bars: Dict[str, Dict], trade_time: datetime):
        """执行买入信号（按优先级排序）"""
        if not self.pending_buy_signals:
            return
        
        sorted_signals = sorted(self.pending_buy_signals, key=lambda x: x.score, reverse=True)
        
        for signal in sorted_signals:
            symbol = signal.symbol
            bar = bars.get(symbol)
            if not bar:
                continue
            
            self._execute_buy(symbol, bar, trade_time, signal.signal_type, signal.score)
    
    def _check_t_plus_1(self, symbol: str, current_date: str) -> bool:
        """T+1检查"""
        if symbol not in self.positions:
            return False
        
        entry_date = self.positions[symbol].entry_date
        
        return current_date > entry_date
    
    def _execute_buy(self, symbol: str, bar: Dict, trade_time: datetime, 
                     signal_type: str, signal_score: float) -> bool:
        """执行买入"""
        if bar['open'] >= bar['high'] * 0.99:
            return False
        
        buy_price = bar['open']
        
        position = Position(
            symbol=symbol,
            name="",
            entry_price=buy_price,
            entry_time=trade_time,
            entry_date=trade_time.strftime('%Y-%m-%d'),
            highest_price=buy_price,
            trailing_stop_price=0.0
        )
        
        self.positions[symbol] = position
        
        if symbol in self.stock_states:
            self.stock_states[symbol].state = StockState.HOLDING
            self.stock_states[symbol].last_signal_score = signal_score
        else:
            self.stock_states[symbol] = StockStateInfo(
                symbol=symbol,
                state=StockState.HOLDING,
                last_signal_score=signal_score
            )
        
        logger.debug(f"买入: {symbol} @ {buy_price:.2f} | 信号: {signal_type} ({signal_score:.2f})")
        
        return True
    
    def _execute_sell(self, symbol: str, bar: Dict, trade_time: datetime, 
                      exit_reason: str) -> bool:
        """执行卖出"""
        if symbol not in self.positions:
            return False
        
        position = self.positions[symbol]
        
        sell_price = bar['open']
        
        pnl_pct = (sell_price - position.entry_price) / position.entry_price
        holding_minutes = (trade_time - position.entry_time).total_seconds() / 60
        
        trade = Trade(
            symbol=symbol,
            name=position.name,
            entry_time=position.entry_time,
            entry_price=position.entry_price,
            exit_time=trade_time,
            exit_price=sell_price,
            pnl_pct=pnl_pct,
            holding_minutes=holding_minutes,
            signal_type="",
            signal_score=position.highest_price / position.entry_price - 1 if position.entry_price > 0 else 0,
            exit_reason=exit_reason,
            highest_price=position.highest_price
        )
        
        self.trades.append(trade)
        
        del self.positions[symbol]
        
        if symbol in self.stock_states:
            self.stock_states[symbol].state = StockState.COOLDOWN
            self.stock_states[symbol].cooldown_until = trade_time + timedelta(minutes=self.config.cooldown_minutes)
        
        logger.debug(f"卖出: {symbol} @ {sell_price:.2f} | 收益: {pnl_pct*100:.2f}% | {exit_reason}")
        
        return True
    
    def _force_close_positions(self):
        """强制平仓（仅在回测结束时）"""
        if not self.positions:
            return
        
        logger.info("强制平仓所有持仓...")
        
        for symbol, position in list(self.positions.items()):
            sell_price = position.highest_price
            
            pnl_pct = 0.0
            if position.entry_price > 0:
                pnl_pct = (sell_price - position.entry_price) / position.entry_price
            
            trade = Trade(
                symbol=symbol,
                name=position.name,
                entry_time=position.entry_time,
                entry_price=position.entry_price,
                exit_time=datetime.now(),
                exit_price=sell_price,
                pnl_pct=pnl_pct,
                holding_minutes=0,
                signal_type="",
                exit_reason="回测结束强制平仓",
                highest_price=position.highest_price
            )
            
            self.trades.append(trade)
            
            logger.info(f"  强制平仓: {symbol} @ {sell_price:.2f} ({pnl_pct*100:+.2f}%)")
        
        self.positions.clear()
    
    def _load_recommendations(self, start_date: str, end_date: str) -> List[Dict]:
        """加载推荐记录"""
        return self.db.get_recommendations(start_date=start_date, end_date=end_date)
    
    def _load_intraday_data(self, symbols: List[str], trade_date: str) -> pd.DataFrame:
        """加载分时数据"""
        all_data = []
        
        for symbol in symbols:
            df = self.db.get_intraday_data(symbol)
            
            if df.empty:
                continue
            
            df['trade_date_str'] = df['trade_time'].dt.strftime('%Y-%m-%d')
            day_data = df[df['trade_date_str'] == trade_date].copy()
            
            if not day_data.empty:
                day_data['symbol'] = symbol
                all_data.append(day_data)
        
        if not all_data:
            return pd.DataFrame()
        
        result = pd.concat(all_data, ignore_index=True)
        result = result.sort_values('trade_time').reset_index(drop=True)
        
        return result
    
    def _calculate_results(self):
        """计算结果"""
        if not self.trades:
            return
        
        self.stats['total_trades'] = len(self.trades)
        self.stats['win_trades'] = sum(1 for t in self.trades if t.pnl_pct > 0)
        self.stats['loss_trades'] = sum(1 for t in self.trades if t.pnl_pct <= 0)
        self.stats['total_pnl_pct'] = sum(t.pnl_pct for t in self.trades)
        self.stats['avg_pnl_pct'] = self.stats['total_pnl_pct'] / self.stats['total_trades']
        
        if self.stats['win_trades'] > 0:
            self.stats['avg_win'] = np.mean([t.pnl_pct for t in self.trades if t.pnl_pct > 0])
        else:
            self.stats['avg_win'] = 0
        
        if self.stats['loss_trades'] > 0:
            self.stats['avg_loss'] = np.mean([t.pnl_pct for t in self.trades if t.pnl_pct <= 0])
        else:
            self.stats['avg_loss'] = 0
        
        if self.stats['avg_loss'] != 0:
            self.stats['profit_loss_ratio'] = abs(self.stats['avg_win'] / self.stats['avg_loss'])
        else:
            self.stats['profit_loss_ratio'] = 0
        
        self.stats['win_rate'] = self.stats['win_trades'] / self.stats['total_trades'] if self.stats['total_trades'] > 0 else 0
        
        self.stats['avg_holding_minutes'] = np.mean([t.holding_minutes for t in self.trades])
        
        exit_reasons = {}
        for t in self.trades:
            reason = t.exit_reason or "未知"
            exit_reasons[reason] = exit_reasons.get(reason, 0) + 1
        self.stats['exit_reasons'] = exit_reasons
        
        signal_types = {}
        for t in self.trades:
            sig = t.signal_type if t.signal_type else "未知"
            signal_types[sig] = signal_types.get(sig, 0) + 1
        self.stats['signal_types'] = signal_types
    
    def _get_results(self) -> Dict:
        """获取结果"""
        return {
            'stats': self.stats,
            'trades': self.trades,
        }
    
    def save_results(self, output_file: str):
        """保存结果"""
        if not self.trades:
            logger.warning("无交易记录可保存")
            return
        
        df = pd.DataFrame([
            {
                'symbol': t.symbol,
                'entry_time': t.entry_time.strftime('%Y-%m-%d %H:%M') if t.entry_time else '',
                'entry_price': t.entry_price,
                'exit_time': t.exit_time.strftime('%Y-%m-%d %H:%M') if t.exit_time else '',
                'exit_price': t.exit_price,
                'pnl_pct': t.pnl_pct,
                'holding_minutes': t.holding_minutes,
                'signal_type': t.signal_type,
                'signal_score': t.signal_score,
                'exit_reason': t.exit_reason,
                'highest_price': t.highest_price
            }
            for t in self.trades
        ])
        
        df.to_csv(output_file, index=False, encoding='utf-8-sig')
        logger.info(f"结果已保存: {output_file}")
    
    def print_results(self):
        """打印结果"""
        print("\n" + "=" * 70)
        print("策略验证回测结果")
        print("=" * 70)
        
        print(f"\n【交易统计】")
        print(f"  总交易次数: {self.stats.get('total_trades', 0)}")
        print(f"  盈利次数: {self.stats.get('win_trades', 0)}")
        print(f"  亏损次数: {self.stats.get('loss_trades', 0)}")
        print(f"  胜率: {self.stats.get('win_rate', 0)*100:.1f}%")
        
        print(f"\n【收益分析】")
        print(f"  累计收益率: {self.stats.get('total_pnl_pct', 0)*100:.2f}%")
        print(f"  平均收益率: {self.stats.get('avg_pnl_pct', 0)*100:.2f}%")
        print(f"  平均盈利: {self.stats.get('avg_win', 0)*100:.2f}%")
        print(f"  平均亏损: {self.stats.get('avg_loss', 0)*100:.2f}%")
        print(f"  盈亏比: {self.stats.get('profit_loss_ratio', 0):.2f}")
        
        print(f"\n【持仓时间】")
        print(f"  平均持仓: {self.stats.get('avg_holding_minutes', 0):.0f}分钟")
        
        exit_reasons = self.stats.get('exit_reasons', {})
        if exit_reasons:
            print(f"\n【卖出原因分布】")
            for reason, count in sorted(exit_reasons.items(), key=lambda x: -x[1]):
                print(f"  - {reason}: {count}笔")
        
        if self.trades:
            print(f"\n【交易明细】")
            print("-" * 70)
            for t in self.trades[:20]:
                entry_time = t.entry_time.strftime('%m-%d %H:%M') if t.entry_time else ''
                exit_time = t.exit_time.strftime('%m-%d %H:%M') if t.exit_time else ''
                pnl_str = f"{t.pnl_pct*100:+.2f}%"
                print(f"  {t.symbol:12s} | {entry_time:11s} -> {exit_time:11s} | {pnl_str:8s} | {t.exit_reason}")
            
            if len(self.trades) > 20:
                print(f"  ... 共 {len(self.trades)} 条记录")
