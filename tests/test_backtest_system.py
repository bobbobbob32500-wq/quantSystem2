# -*- coding: utf-8 -*-
"""
回测系统测试，使用项目内真实日线数据。
"""

import sys
import os
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.modules.backtest import BacktestEngine, BacktestConfig
from src.core.logger import get_logger
from tests.real_data_helpers import load_daily_data_dict

logger = get_logger("test_backtest")


def test_basic_backtest():
    """测试基础回测功能。"""
    print("\n" + "=" * 70)
    print("测试1: 基础回测功能（真实日线数据）")
    print("=" * 70)

    data_dict = load_daily_data_dict(
        symbols=["000001.SZ", "000002.SZ", "000004.SZ"],
        bars=90,
    )
    assert len(data_dict) == 3, "真实日线测试样本不足"

    for symbol, df in data_dict.items():
        print(f"  {symbol}: {len(df)} 个交易日")

    config = BacktestConfig(
        initial_capital=100000,
        max_positions=3,
        position_size=0.3,
        buy_signal_threshold=30,
        sell_signal_threshold=40,
        stop_loss_pct=-0.05,
        take_profit_pct=0.10,
    )

    engine = BacktestEngine(config)
    results = engine.run(data_dict, show_progress=False)
    engine.print_results()

    assert isinstance(results, dict)
    assert "trade_history" in results
    assert results.get("total_trades", 0) >= 1


def test_t1_rule():
    """测试 T+1 规则。"""
    print("\n" + "=" * 70)
    print("测试2: T+1规则（真实日线数据）")
    print("=" * 70)

    data_dict = load_daily_data_dict(symbols=["000001.SZ"], bars=90)
    assert "000001" in data_dict

    config = BacktestConfig(
        initial_capital=100000,
        max_positions=1,
        position_size=0.5,
        enable_t1_rule=True,
        buy_signal_threshold=30,
    )

    engine = BacktestEngine(config)
    results = engine.run(data_dict, show_progress=False)

    trade_history = results.get("trade_history", [])
    print(f"\n交易记录数: {len(trade_history)}")
    assert trade_history, "真实样本未触发任何交易，无法验证 T+1"

    last_buy_date = {}
    sell_count = 0
    for trade in trade_history:
        print(f"  {trade['date']} {trade['action']} {trade['symbol']} @ {trade['price']:.2f}")
        symbol = trade["symbol"]
        if trade["action"] == "buy":
            last_buy_date[symbol] = trade["date"]
        elif trade["action"] == "sell":
            sell_count += 1
            assert symbol in last_buy_date, f"{symbol} 出现卖出但未找到对应买入"
            assert trade["date"] > last_buy_date[symbol], (
                f"T+1 规则验证失败: {symbol} 在 {trade['date']} 当天买入并卖出"
            )

    assert sell_count >= 1, "真实样本未出现卖出记录，无法验证 T+1"


def test_risk_control():
    """测试风控功能。"""
    print("\n" + "=" * 70)
    print("测试3: 风控功能（真实日线数据）")
    print("=" * 70)

    data_dict = load_daily_data_dict(symbols=["000002.SZ"], bars=90)
    assert "000002" in data_dict

    config = BacktestConfig(
        initial_capital=100000,
        max_positions=1,
        position_size=0.5,
        stop_loss_pct=-0.03,
        take_profit_pct=0.10,
        buy_signal_threshold=30,
    )

    engine = BacktestEngine(config)
    results = engine.run(data_dict, show_progress=False)

    trade_history = results.get("trade_history", [])
    risk_trades = [
        trade for trade in trade_history
        if str(trade.get("signal_type", "")).find("止损") >= 0
    ]

    print(f"\n风控触发交易数: {len(risk_trades)}")
    for trade in risk_trades:
        print(
            f"  {trade['date']} {trade['signal_type']} {trade['symbol']} @ "
            f"{trade['price']:.2f}"
        )

    assert isinstance(results, dict)
    assert risk_trades, "真实样本未触发止损类风控卖出"


def test_multi_stock():
    """测试多股票回测。"""
    print("\n" + "=" * 70)
    print("测试4: 多股票回测（真实日线数据）")
    print("=" * 70)

    symbols = ["000001.SZ", "000002.SZ", "000004.SZ", "600000.SH", "600036.SH"]
    data_dict = load_daily_data_dict(symbols=symbols, bars=100)
    assert len(data_dict) >= 4, "多股票真实样本不足"

    print(f"\n准备 {len(data_dict)} 只股票数据")

    config = BacktestConfig(
        initial_capital=100000,
        max_positions=3,
        position_size=0.3,
        buy_signal_threshold=30,
        sell_signal_threshold=40,
    )

    engine = BacktestEngine(config)
    results = engine.run(data_dict, show_progress=False)
    engine.print_results()

    trade_history = results.get("trade_history", [])
    stock_trades = {}
    for trade in trade_history:
        symbol = trade["symbol"]
        stock_trades.setdefault(symbol, {"buy": 0, "sell": 0})
        stock_trades[symbol][trade["action"]] += 1

    print("\n各股票交易统计:")
    for symbol, counts in stock_trades.items():
        print(f"  {symbol}: 买入{counts['buy']}次, 卖出{counts['sell']}次")

    assert isinstance(results, dict)
    assert results.get("total_trades", 0) >= 1
    assert len(stock_trades) >= 2


def test_performance():
    """测试性能。"""
    print("\n" + "=" * 70)
    print("测试5: 性能测试（真实日线数据）")
    print("=" * 70)

    symbols = [
        "000001.SZ", "000002.SZ", "000004.SZ", "000006.SZ", "000007.SZ",
        "000008.SZ", "000009.SZ", "000010.SZ", "600000.SH", "600036.SH",
    ]
    data_dict = load_daily_data_dict(symbols=symbols, bars=100)
    assert len(data_dict) >= 8, "性能测试真实样本不足"

    total_rows = sum(len(df) for df in data_dict.values())
    print(f"\n准备 {len(data_dict)} 只股票，共 {total_rows} 条日线记录")

    config = BacktestConfig(
        initial_capital=100000,
        max_positions=5,
        position_size=0.2,
    )

    start_time = time.time()
    engine = BacktestEngine(config)
    results = engine.run(data_dict, show_progress=False)
    elapsed_time = time.time() - start_time

    print(f"\n回测耗时: {elapsed_time:.2f}秒")
    print(f"处理速度: {total_rows / max(elapsed_time, 1e-6):.0f} bars/秒")
    print(f"总收益率: {results.get('total_return', 0) * 100:.2f}%")
    print(f"夏普比率: {results.get('sharpe_ratio', 0):.3f}")
    print(f"最大回撤: {results.get('max_drawdown', 0) * 100:.2f}%")
    print(f"交易次数: {results.get('total_trades', 0)}次")

    assert isinstance(results, dict)
    assert elapsed_time > 0


def main():
    """主测试函数。"""
    print("\n" + "=" * 70)
    print("回测系统测试")
    print("=" * 70)

    test_basic_backtest()
    test_t1_rule()
    test_risk_control()
    test_multi_stock()
    test_performance()

    print("\n" + "=" * 70)
    print("所有测试完成")
    print("=" * 70)


if __name__ == "__main__":
    main()
