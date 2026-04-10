# -*- coding: utf-8 -*-
"""
事件驱动日内回测引擎
从"日级回放"升级为"盘中事件驱动"
"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pandas as pd
import numpy as np
import sqlite3
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from src.core.logger import get_logger

logger = get_logger("event_driven_backtest")


# ============================================================================
# 数据结构
# ============================================================================

class Trade:
    """交易记录"""
    def __init__(self):
        self.symbol = None
        self.entry_time = None
        self.entry_price = None
        self.exit_time = None
        self.exit_price = None
        self.pnl_pct = None
        self.holding_minutes = None
        self.signal_type = None


class Portfolio:
    """投资组合"""
    def __init__(self, initial_capital=100000):
        self.initial_capital = initial_capital
        self.cash = initial_capital
        self.positions = {}  # symbol -> {'shares': x, 'entry_price': y, 'entry_time': t}
        self.trades = []
        self.equity_curve = []
    
    def open_position(self, symbol, price, time, shares=None):
        """开仓"""
        if shares is None:
            # 固定金额买入
            position_value = self.cash * 0.2  # 每只股票20%仓位
            shares = int(position_value / price / 100) * 100  # 整手
        
        if shares == 0:
            return False
        
        cost = shares * price * 1.001  # 滑点
        if cost > self.cash:
            return False
        
        self.cash -= cost
        self.positions[symbol] = {
            'shares': shares,
            'entry_price': price,
            'entry_time': time,
        }
        
        return True
    
    def close_position(self, symbol, price, time):
        """平仓"""
        if symbol not in self.positions:
            return False
        
        pos = self.positions[symbol]
        shares = pos['shares']
        
        revenue = shares * price * 0.999  # 滑点
        self.cash += revenue
        
        # 记录交易
        trade = Trade()
        trade.symbol = symbol
        trade.entry_time = pos['entry_time']
        trade.entry_price = pos['entry_price']
        trade.exit_time = time
        trade.exit_price = price
        trade.pnl_pct = (price - pos['entry_price']) / pos['entry_price'] * 100
        trade.holding_minutes = (time - pos['entry_time']).total_seconds() / 60
        
        self.trades.append(trade)
        del self.positions[symbol]
        
        return True
    
    def get_equity(self, current_prices):
        """计算总权益"""
        equity = self.cash
        for symbol, pos in self.positions.items():
            if symbol in current_prices:
                equity += pos['shares'] * current_prices[symbol]
        return equity


# ============================================================================
# 状态管理
# ============================================================================

def init_state(candidates):
    """初始化状态"""
    state = {}
    for symbol in candidates:
        state[symbol] = {
            "status": "WATCH",  # WATCH / HOLDING / SOLD
            "window": [],
            "buy_time": None,
            "buy_price": None,
        }
    return state


def update_windows(state, bars, window_size=50):
    """更新数据窗口"""
    for symbol, bar in bars.items():
        if symbol not in state:
            continue
        
        window = state[symbol].setdefault("window", [])
        window.append(bar)
        
        if len(window) > window_size:
            window.pop(0)


# ============================================================================
# 买卖信号判断
# ============================================================================

def signal_pullback(window):
    """回踩信号"""
    if len(window) < 20:
        return False
    
    # ✅ 修正：使用t-1时刻的数据（排除当前bar）
    prices = np.array([x['close'] for x in window[:-1]])
    
    if len(prices) < 20:
        return False
    
    ma5 = prices[-5:].mean()
    ma20 = prices[-20:].mean()
    
    # 趋势过滤
    if prices[-1] < ma20:
        return False
    
    # 回踩均线
    cond1 = abs(prices[-1] - ma5) / ma5 < 0.01
    
    # 不创新低
    lows = [x['low'] for x in window[-4:-1]]
    cond2 = min(lows) >= min([x['low'] for x in window[-11:-4]])
    
    return cond1 and cond2


def signal_breakout(window):
    """突破信号"""
    if len(window) < 20:
        return False
    
    # ✅ 修正：使用t-1时刻的数据
    prices = np.array([x['close'] for x in window[:-1]])
    
    if len(prices) < 20:
        return False
    
    # 突破前高
    recent_high = prices[-20:-1].max()
    current = prices[-1]
    
    if current > recent_high * 1.01:  # 突破1%
        return True
    
    return False


def check_buy_signal(symbol, state, t):
    """检查买入信号"""
    window = state[symbol]["window"]
    
    if len(window) < 20:
        return False
    
    # 回踩信号
    if signal_pullback(window):
        return True
    
    # 突破信号
    if signal_breakout(window):
        return True
    
    return False


def check_sell_signal(symbol, state, t, portfolio):
    """检查卖出信号"""
    if symbol not in portfolio.positions:
        return False
    
    window = state[symbol]["window"]
    
    if len(window) < 3:
        return False
    
    # ✅ 修正：使用t-1时刻的数据
    prices = [x['close'] for x in window[:-1]]
    
    if len(prices) < 3:
        return False
    
    entry_price = portfolio.positions[symbol]['entry_price']
    current_price = prices[-1]
    
    ret = (current_price - entry_price) / entry_price
    
    # 止损 -2%
    if ret < -0.02:
        return True
    
    # 止盈 +5%
    if ret > 0.05:
        return True
    
    # 快速下跌
    if len(prices) >= 3 and prices[-1] < prices[-3] * 0.97:
        return True
    
    return False


# ============================================================================
# A股约束
# ============================================================================

def can_buy(bar):
    """是否可以买入"""
    # 涨停不能买
    if 'limit_up' in bar and bar['close'] >= bar['limit_up'] * 0.99:
        return False
    
    return True


def can_sell(symbol, state, current_time):
    """是否可以卖出（T+1）"""
    if state[symbol]["buy_time"] is None:
        return False
    
    buy_date = state[symbol]["buy_time"].date()
    current_date = current_time.date()
    
    # T+1规则
    return current_date > buy_date


# ============================================================================
# 核心回测引擎
# ============================================================================

def run_one_day(trade_date, candidates, intraday_data, portfolio):
    """运行单日回测"""
    # 初始化状态
    state = init_state(candidates)
    
    # 按时间排序
    intraday_data = intraday_data.sort_values('trade_time')
    
    # 逐分钟推进
    for t, group in intraday_data.groupby('trade_time'):
        # 构建当前分钟的所有股票数据
        bars = {}
        for _, row in group.iterrows():
            symbol = row['symbol']
            bars[symbol] = {
                'open': row['open'],
                'high': row['high'],
                'low': row['low'],
                'close': row['close'],
                'volume': row['volume'],
            }
        
        # 更新数据窗口
        update_windows(state, bars)
        
        # === 买入逻辑 ===
        for symbol in candidates:
            if symbol not in bars:
                continue
            
            if state[symbol]["status"] == "WATCH":
                if check_buy_signal(symbol, state, t):
                    if can_buy(bars[symbol]):
                        # ✅ 修正：使用当前bar的开盘价+滑点，而不是收盘价
                        buy_price = bars[symbol]['open'] * 1.001  # 开盘价+滑点
                        
                        # 执行买入
                        if portfolio.open_position(symbol, buy_price, t):
                            state[symbol]["status"] = "HOLDING"
                            state[symbol]["buy_time"] = t
                            state[symbol]["buy_price"] = buy_price
        
        # === 卖出逻辑 ===
        for symbol in list(portfolio.positions.keys()):
            if symbol not in bars:
                continue
            
            # ✅ 修正：确保持仓股票在state中
            if symbol not in state:
                state[symbol] = {
                    "status": "HOLDING",
                    "window": [],
                    "buy_time": portfolio.positions[symbol]['entry_time'],
                    "buy_price": portfolio.positions[symbol]['entry_price'],
                }
            
            if check_sell_signal(symbol, state, t, portfolio):
                if can_sell(symbol, state, t):
                    # ✅ 修正：使用当前bar的开盘价-滑点
                    sell_price = bars[symbol]['open'] * 0.999  # 开盘价-滑点
                    
                    # 执行卖出
                    portfolio.close_position(symbol, sell_price, t)
                    state[symbol]["status"] = "SOLD"
    
    # ✅ 修正：日终处理持仓（遵守T+1规则）
    # 当天买入的不能卖出，持仓带入下一天
    for symbol in list(portfolio.positions.keys()):
        # 检查是否可以卖出（T+1）
        last_time = intraday_data[intraday_data['symbol'] == symbol].iloc[-1]['trade_time']
        
        if can_sell(symbol, state, last_time):
            # 可以卖出的持仓，收盘价平仓
            last_bar = intraday_data[intraday_data['symbol'] == symbol].iloc[-1]
            sell_price = last_bar['close'] * 0.999
            portfolio.close_position(symbol, sell_price, last_time)
            state[symbol]["status"] = "SOLD"
        # else: 不能卖出的持仓，保留到下一天


def get_candidates(recommendations, trade_date):
    """获取候选股票（时间对齐）"""
    # 关键：用前一天的推荐
    rec_date = trade_date - timedelta(days=1)
    rec_date_str = rec_date.strftime('%Y-%m-%d')
    
    candidates = recommendations[
        recommendations['recommendation_date'] == rec_date_str
    ]['symbol'].tolist()
    
    return candidates


def run_event_driven_backtest(recommendations, intraday_data):
    """事件驱动回测主函数"""
    print("\n" + "="*70)
    print("事件驱动日内回测")
    print("="*70)
    
    print("\n回测模型:")
    print("  1. T-1日收盘选股")
    print("  2. T日盘中监控")
    print("  3. 出现买点才买")
    print("  4. 动态卖出")
    
    # 初始化投资组合
    portfolio = Portfolio(initial_capital=100000)
    
    # 获取所有交易日
    all_dates = intraday_data['trade_date'].unique()
    all_dates = pd.to_datetime(all_dates)
    all_dates = sorted(all_dates)
    
    print(f"\n回测日期范围: {all_dates[0]} ~ {all_dates[-1]}")
    print(f"共 {len(all_dates)} 个交易日")
    
    # 按天循环
    for i, trade_date in enumerate(all_dates, 1):
        trade_date = pd.to_datetime(trade_date)
        
        # 获取候选股票
        candidates = get_candidates(recommendations, trade_date)
        
        if not candidates:
            continue
        
        # 获取当日分时数据
        day_data = intraday_data[
            intraday_data['trade_date'] == trade_date
        ].copy()
        
        if day_data.empty:
            continue
        
        print(f"\n[{i}/{len(all_dates)}] {trade_date.strftime('%Y-%m-%d')} | 候选: {len(candidates)}只")
        
        # 运行单日回测
        run_one_day(trade_date, candidates, day_data, portfolio)
    
    return portfolio


# ============================================================================
# 结果分析
# ============================================================================

def analyze_results(portfolio):
    """分析回测结果"""
    print("\n" + "="*70)
    print("回测结果分析")
    print("="*70)
    
    trades = portfolio.trades
    
    if not trades:
        print("\n[WARN] 无交易记录")
        return
    
    # 转换为DataFrame
    trades_df = pd.DataFrame([
        {
            'symbol': t.symbol,
            'entry_time': t.entry_time,
            'entry_price': t.entry_price,
            'exit_time': t.exit_time,
            'exit_price': t.exit_price,
            'pnl_pct': t.pnl_pct,
            'holding_minutes': t.holding_minutes,
        }
        for t in trades
    ])
    
    # 基本统计
    print("\n【基本统计】")
    print("-" * 70)
    print(f"总交易次数: {len(trades)}")
    print(f"盈利次数: {len(trades_df[trades_df['pnl_pct'] > 0])}")
    print(f"亏损次数: {len(trades_df[trades_df['pnl_pct'] < 0])}")
    
    # 收益统计
    print("\n【收益统计】")
    print("-" * 70)
    print(f"平均收益: {trades_df['pnl_pct'].mean():.2f}%")
    print(f"最大收益: {trades_df['pnl_pct'].max():.2f}%")
    print(f"最大亏损: {trades_df['pnl_pct'].min():.2f}%")
    print(f"收益中位数: {trades_df['pnl_pct'].median():.2f}%")
    
    # 胜率
    win_rate = len(trades_df[trades_df['pnl_pct'] > 0]) / len(trades_df) * 100
    print(f"\n胜率: {win_rate:.1f}%")
    
    # 持仓时间
    print("\n【持仓时间】")
    print("-" * 70)
    print(f"平均持仓: {trades_df['holding_minutes'].mean():.0f}分钟")
    print(f"最长持仓: {trades_df['holding_minutes'].max():.0f}分钟")
    print(f"最短持仓: {trades_df['holding_minutes'].min():.0f}分钟")
    
    # 资金统计
    print("\n【资金统计】")
    print("-" * 70)
    print(f"初始资金: {portfolio.initial_capital:,.0f}")
    print(f"最终资金: {portfolio.cash:,.0f}")
    total_return = (portfolio.cash - portfolio.initial_capital) / portfolio.initial_capital * 100
    print(f"总收益率: {total_return:.2f}%")
    
    # 详细交易
    print("\n【详细交易】")
    print("-" * 70)
    for _, row in trades_df.iterrows():
        print(f"{row['symbol']} | 入{row['entry_time'].strftime('%m-%d %H:%M')} {row['entry_price']:.2f} | 出{row['exit_time'].strftime('%m-%d %H:%M')} {row['exit_price']:.2f} | 收益{row['pnl_pct']:+.2f}%")
    
    # 保存结果
    trades_df.to_csv('event_driven_backtest_results.csv', index=False, encoding='utf-8-sig')
    print(f"\n[OK] 结果已保存: event_driven_backtest_results.csv")


# ============================================================================
# 主函数
# ============================================================================

def main():
    """主函数"""
    print("\n" + "="*70)
    print("事件驱动日内回测系统")
    print("="*70)
    
    # 加载数据
    print("\n加载回测数据...")
    conn = sqlite3.connect("data/history_recommendation.db")
    
    recommendations = pd.read_sql("""
        SELECT symbol, name, recommendation_date, recommendation_score
        FROM recommendations
        ORDER BY recommendation_date
    """, conn)
    
    intraday_data = pd.read_sql("""
        SELECT symbol, trade_time, trade_date, open, high, low, close, volume
        FROM intraday_data
        ORDER BY trade_time
    """, conn)
    
    intraday_data['trade_time'] = pd.to_datetime(intraday_data['trade_time'])
    intraday_data['trade_date'] = pd.to_datetime(intraday_data['trade_date'])
    
    conn.close()
    
    print(f"推荐记录: {len(recommendations)}条")
    print(f"分时数据: {len(intraday_data)}条")
    
    # 执行回测
    portfolio = run_event_driven_backtest(recommendations, intraday_data)
    
    # 分析结果
    analyze_results(portfolio)
    
    print("\n" + "="*70)
    print("[OK] 回测完成")
    print("="*70)


if __name__ == "__main__":
    main()
