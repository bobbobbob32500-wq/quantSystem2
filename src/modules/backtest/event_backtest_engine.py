# -*- coding: utf-8 -*-
"""
事件驱动回测引擎
基于已有选股结果进行历史交易模拟
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from collections import defaultdict

from src.core.logger import get_logger
from src.modules.backtest.history_recommendation_db import HistoryRecommendationDB

logger = get_logger("event_backtest_engine")


@dataclass
class Trade:
    """交易记录"""
    symbol: str
    name: str
    entry_time: datetime
    entry_price: float
    exit_time: datetime = None
    exit_price: float = None
    shares: int = 0
    pnl_pct: float = 0.0
    pnl_amount: float = 0.0
    holding_minutes: float = 0.0
    signal_type: str = ""
    exit_reason: str = ""


@dataclass
class Position:
    """持仓信息"""
    symbol: str
    name: str
    shares: int
    entry_price: float
    entry_time: datetime
    entry_date: str
    cost: float = 0.0


@dataclass
class BacktestConfig:
    """回测配置"""
    initial_capital: float = 100000.0
    position_size: float = 0.2
    max_positions: int = 5
    window_size: int = 50
    stop_loss_pct: float = -0.03
    take_profit_pct: float = 0.05
    commission_rate: float = 0.0003
    stamp_duty_rate: float = 0.001
    slippage_rate: float = 0.001


class EventDrivenBacktest:
    """事件驱动回测引擎"""
    
    def __init__(self, db: HistoryRecommendationDB = None, config: BacktestConfig = None):
        if db is None:
            db = HistoryRecommendationDB()
        if config is None:
            config = BacktestConfig()
        
        self.db = db
        self.config = config
        
        self.cash = config.initial_capital
        self.initial_capital = config.initial_capital
        self.positions: Dict[str, Position] = {}
        self.trades: List[Trade] = []
        self.equity_curve: List[Dict] = []
        
        self.data_windows: Dict[str, List[Dict]] = defaultdict(list)
        
        self.stats = {
            'total_trades': 0,
            'win_trades': 0,
            'loss_trades': 0,
            'total_pnl': 0.0,
            'total_pnl_pct': 0.0,
        }
        
        logger.info("事件驱动回测引擎初始化完成")
    
    def run(self, start_date: str, end_date: str, show_progress: bool = True) -> Dict:
        """
        运行回测
        
        Args:
            start_date: 开始日期 (YYYY-MM-DD)
            end_date: 结束日期 (YYYY-MM-DD)
            show_progress: 是否显示进度
        
        Returns:
            回测结果
        """
        logger.info("=" * 70)
        logger.info("开始事件驱动回测")
        logger.info("=" * 70)
        logger.info(f"回测区间: {start_date} ~ {end_date}")
        logger.info(f"初始资金: {self.initial_capital:,.0f}")
        
        recommendations = self._load_recommendations(start_date, end_date)
        
        if not recommendations:
            logger.warning("无推荐记录，回测终止")
            return self._get_results()
        
        logger.info(f"推荐记录: {len(recommendations)}条")
        
        recommendations_df = pd.DataFrame(recommendations)
        recommendations_df['recommendation_date'] = pd.to_datetime(recommendations_df['recommendation_date'])
        
        all_dates = recommendations_df['recommendation_date'].unique()
        all_dates = sorted(all_dates)
        
        logger.info(f"交易日数: {len(all_dates)}天")
        
        for i, rec_date in enumerate(all_dates, 1):
            trade_date = rec_date + timedelta(days=1)
            trade_date_str = trade_date.strftime('%Y-%m-%d')
            
            prev_date = rec_date.strftime('%Y-%m-%d')
            day_recs = recommendations_df[recommendations_df['recommendation_date'] == prev_date]
            candidates = day_recs['symbol'].tolist()
            
            if not candidates:
                candidates = []
            
            all_symbols = list(set(candidates + list(self.positions.keys())))
            
            if not all_symbols:
                continue
            
            intraday_data = self._load_intraday_data(all_symbols, trade_date_str)
            
            if intraday_data.empty:
                continue
            
            if show_progress:
                logger.info(f"[{i}/{len(all_dates)}] {trade_date_str} | 候选: {len(candidates)}只 | 持仓: {len(self.positions)}只")
            
            self._run_single_day(trade_date, candidates, intraday_data)
        
        self._force_close_positions()
        self._calculate_results()
        
        logger.info("=" * 70)
        logger.info("回测完成")
        logger.info("=" * 70)
        
        return self._get_results()
    
    def _force_close_positions(self):
        """强制平仓所有持仓（回测结束时）"""
        if not self.positions:
            return
        
        logger.info(f"回测结束，强制平仓 {len(self.positions)} 个持仓")
        
        for symbol, position in list(self.positions.items()):
            last_price = position.entry_price
            
            df = self.db.get_intraday_data(symbol)
            if not df.empty:
                df = df.sort_values('trade_time')
                last_price = df.iloc[-1]['close']
            
            sell_price = last_price * (1 - self.config.slippage_rate)
            revenue = position.shares * sell_price * (1 - self.config.commission_rate - self.config.stamp_duty_rate)
            
            self.cash += revenue
            
            pnl_amount = revenue - position.cost
            pnl_pct = (sell_price - position.entry_price) / position.entry_price
            
            trade = Trade(
                symbol=symbol,
                name=position.name,
                entry_time=position.entry_time,
                entry_price=position.entry_price,
                exit_time=datetime.now(),
                exit_price=sell_price,
                shares=position.shares,
                pnl_pct=pnl_pct,
                pnl_amount=pnl_amount,
                holding_minutes=0,
                signal_type="",
                exit_reason="回测结束"
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
    
    def _run_single_day(self, trade_date: datetime, candidates: List[str], intraday_data: pd.DataFrame):
        """运行单日回测"""
        trade_date_str = trade_date.strftime('%Y-%m-%d')
        
        for symbol in list(self.positions.keys()):
            self.data_windows[symbol] = []
        
        for symbol in candidates:
            if symbol not in self.data_windows:
                self.data_windows[symbol] = []
        
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
            
            for symbol in candidates:
                if symbol not in bars:
                    continue
                
                if symbol not in self.positions:
                    buy_signal, signal_type = self._check_buy_signal(symbol)
                    
                    if buy_signal:
                        self._execute_buy(symbol, bars[symbol], trade_time, signal_type)
            
            for symbol in list(self.positions.keys()):
                if symbol not in bars:
                    continue
                
                sell_signal, exit_reason = self._check_sell_signal(symbol, bars[symbol])
                
                if sell_signal:
                    can_sell = self._check_t_plus_1(symbol, trade_date_str)
                    
                    if can_sell:
                        self._execute_sell(symbol, bars[symbol], trade_time, exit_reason)
        
        self._end_of_day_processing(trade_date, intraday_data)
    
    def _update_data_windows(self, bars: Dict[str, Dict]):
        """更新数据窗口"""
        for symbol, bar in bars.items():
            self.data_windows[symbol].append(bar)
            
            if len(self.data_windows[symbol]) > self.config.window_size:
                self.data_windows[symbol].pop(0)
    
    def _check_buy_signal(self, symbol: str) -> Tuple[bool, str]:
        """检查买入信号"""
        window = self.data_windows.get(symbol, [])
        
        if len(window) < 20:
            return False, ""
        
        if self._signal_pullback(window):
            return True, "回踩均线"
        
        if self._signal_breakout(window):
            return True, "突破前高"
        
        return False, ""
    
    def _signal_pullback(self, window: List[Dict]) -> bool:
        """回踩均线信号"""
        if len(window) < 20:
            return False
        
        prices = np.array([x['close'] for x in window[:-1]])
        
        if len(prices) < 20:
            return False
        
        ma5 = prices[-5:].mean()
        ma20 = prices[-20:].mean()
        
        if prices[-1] < ma20:
            return False
        
        cond1 = abs(prices[-1] - ma5) / ma5 < 0.01
        
        lows = [x['low'] for x in window[-4:-1]]
        cond2 = min(lows) >= min([x['low'] for x in window[-11:-4]])
        
        return cond1 and cond2
    
    def _signal_breakout(self, window: List[Dict]) -> bool:
        """突破信号"""
        if len(window) < 20:
            return False
        
        prices = np.array([x['close'] for x in window[:-1]])
        
        if len(prices) < 20:
            return False
        
        recent_high = prices[-20:-1].max()
        current = prices[-1]
        
        if current > recent_high * 1.01:
            return True
        
        return False
    
    def _check_sell_signal(self, symbol: str, bar: Dict) -> Tuple[bool, str]:
        """检查卖出信号"""
        if symbol not in self.positions:
            return False, ""
        
        position = self.positions[symbol]
        current_price = bar['close']
        
        pnl_pct = (current_price - position.entry_price) / position.entry_price
        
        if pnl_pct <= self.config.stop_loss_pct:
            return True, "止损"
        
        if pnl_pct >= self.config.take_profit_pct:
            return True, "止盈"
        
        window = self.data_windows.get(symbol, [])
        if len(window) >= 3:
            prices = [x['close'] for x in window[-3:]]
            if prices[-1] < prices[0] * 0.97:
                return True, "快速下跌"
        
        return False, ""
    
    def _check_t_plus_1(self, symbol: str, current_date: str) -> bool:
        """检查T+1约束"""
        if symbol not in self.positions:
            return False
        
        entry_date = self.positions[symbol].entry_date
        return current_date > entry_date
    
    def _execute_buy(self, symbol: str, bar: Dict, trade_time: datetime, signal_type: str):
        """执行买入"""
        if len(self.positions) >= self.config.max_positions:
            return False
        
        if bar['close'] >= bar['high'] * 0.99:
            return False
        
        buy_price = bar['close'] * (1 + self.config.slippage_rate)
        
        position_value = self.cash * self.config.position_size
        shares = int(position_value / buy_price / 100) * 100
        
        if shares == 0:
            return False
        
        cost = shares * buy_price * (1 + self.config.commission_rate)
        
        if cost > self.cash:
            return False
        
        self.cash -= cost
        
        position = Position(
            symbol=symbol,
            name="",
            shares=shares,
            entry_price=buy_price,
            entry_time=trade_time,
            entry_date=trade_time.strftime('%Y-%m-%d'),
            cost=cost
        )
        
        self.positions[symbol] = position
        
        logger.debug(f"买入: {symbol} @ {buy_price:.2f} x {shares}股")
        
        return True
    
    def _execute_sell(self, symbol: str, bar: Dict, trade_time: datetime, exit_reason: str):
        """执行卖出"""
        if symbol not in self.positions:
            return False
        
        position = self.positions[symbol]
        
        sell_price = bar['close'] * (1 - self.config.slippage_rate)
        
        revenue = position.shares * sell_price * (1 - self.config.commission_rate - self.config.stamp_duty_rate)
        
        self.cash += revenue
        
        pnl_amount = revenue - position.cost
        pnl_pct = (sell_price - position.entry_price) / position.entry_price
        holding_minutes = (trade_time - position.entry_time).total_seconds() / 60
        
        trade = Trade(
            symbol=symbol,
            name=position.name,
            entry_time=position.entry_time,
            entry_price=position.entry_price,
            exit_time=trade_time,
            exit_price=sell_price,
            shares=position.shares,
            pnl_pct=pnl_pct,
            pnl_amount=pnl_amount,
            holding_minutes=holding_minutes,
            signal_type="",
            exit_reason=exit_reason
        )
        
        self.trades.append(trade)
        
        del self.positions[symbol]
        
        logger.debug(f"卖出: {symbol} @ {sell_price:.2f} | 收益: {pnl_pct*100:.2f}% ({exit_reason})")
        
        return True
    
    def _end_of_day_processing(self, trade_date: datetime, intraday_data: pd.DataFrame):
        """日终处理"""
        trade_date_str = trade_date.strftime('%Y-%m-%d')
        
        equity = self.cash
        for symbol, position in self.positions.items():
            day_data = intraday_data[intraday_data['symbol'] == symbol]
            if not day_data.empty:
                last_price = day_data.iloc[-1]['close']
                equity += position.shares * last_price
        
        self.equity_curve.append({
            'date': trade_date_str,
            'equity': equity,
            'cash': self.cash,
            'positions': len(self.positions)
        })
    
    def _calculate_results(self):
        """计算结果"""
        if not self.trades:
            return
        
        self.stats['total_trades'] = len(self.trades)
        self.stats['win_trades'] = sum(1 for t in self.trades if t.pnl_pct > 0)
        self.stats['loss_trades'] = sum(1 for t in self.trades if t.pnl_pct <= 0)
        self.stats['total_pnl'] = sum(t.pnl_amount for t in self.trades)
        self.stats['total_pnl_pct'] = (self.cash - self.initial_capital) / self.initial_capital
        
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
    
    def _get_results(self) -> Dict:
        """获取结果"""
        return {
            'stats': self.stats,
            'trades': self.trades,
            'equity_curve': self.equity_curve,
            'final_cash': self.cash,
            'total_return': self.stats.get('total_pnl_pct', 0),
        }
    
    def print_results(self):
        """打印结果"""
        print("\n" + "=" * 70)
        print("回测结果")
        print("=" * 70)
        
        print(f"\n【资金统计】")
        print(f"  初始资金: {self.initial_capital:,.0f}")
        print(f"  最终资金: {self.cash:,.0f}")
        print(f"  总收益: {self.stats.get('total_pnl', 0):,.2f}")
        print(f"  总收益率: {self.stats.get('total_pnl_pct', 0)*100:.2f}%")
        
        print(f"\n【交易统计】")
        print(f"  总交易次数: {self.stats.get('total_trades', 0)}")
        print(f"  盈利次数: {self.stats.get('win_trades', 0)}")
        print(f"  亏损次数: {self.stats.get('loss_trades', 0)}")
        print(f"  胜率: {self.stats.get('win_rate', 0)*100:.1f}%")
        
        print(f"\n【收益分析】")
        print(f"  平均盈利: {self.stats.get('avg_win', 0)*100:.2f}%")
        print(f"  平均亏损: {self.stats.get('avg_loss', 0)*100:.2f}%")
        print(f"  盈亏比: {self.stats.get('profit_loss_ratio', 0):.2f}")
        
        print(f"\n【持仓时间】")
        print(f"  平均持仓: {self.stats.get('avg_holding_minutes', 0):.0f}分钟")
        
        if self.trades:
            print(f"\n【交易明细】")
            print("-" * 70)
            for t in self.trades[:20]:
                entry_time = t.entry_time.strftime('%m-%d %H:%M') if t.entry_time else ''
                exit_time = t.exit_time.strftime('%m-%d %H:%M') if t.exit_time else ''
                print(f"  {t.symbol} | 入{entry_time} {t.entry_price:.2f} | 出{exit_time} {t.exit_price:.2f} | {t.pnl_pct*100:+.2f}% ({t.exit_reason})")
            
            if len(self.trades) > 20:
                print(f"  ... 共 {len(self.trades)} 条记录")
        
        print("=" * 70)
    
    def save_results(self, output_file: str = "backtest_results.csv"):
        """保存结果"""
        if not self.trades:
            logger.warning("无交易记录，不保存结果")
            return
        
        trades_data = []
        for t in self.trades:
            trades_data.append({
                'symbol': t.symbol,
                'entry_time': t.entry_time,
                'entry_price': t.entry_price,
                'exit_time': t.exit_time,
                'exit_price': t.exit_price,
                'shares': t.shares,
                'pnl_pct': t.pnl_pct * 100,
                'pnl_amount': t.pnl_amount,
                'holding_minutes': t.holding_minutes,
                'exit_reason': t.exit_reason,
            })
        
        df = pd.DataFrame(trades_data)
        df.to_csv(output_file, index=False, encoding='utf-8-sig')
        
        logger.info(f"结果已保存: {output_file}")
