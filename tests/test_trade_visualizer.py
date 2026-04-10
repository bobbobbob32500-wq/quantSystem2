# -*- coding: utf-8 -*-
"""
交易可视化功能测试，使用项目内真实分时数据。
"""

import sys
import os
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.modules.backtest.trade_visualizer import (
    TradeVisualizer,
    TradePoint,
    generate_multi_stock_report,
)
from src.modules.backtest.event_backtest_engine import EventDrivenBacktest, BacktestConfig
from tests.real_data_helpers import get_history_recommendation_db, get_intraday_sample


def _build_trade_points(symbol: str, intraday_data, name: str = ""):
    """基于真实分时数据构建测试买卖点。"""
    assert not intraday_data.empty, "分时数据为空"
    ordered = intraday_data.sort_values("trade_time").reset_index(drop=True)
    size = len(ordered)
    buy_1 = ordered.iloc[min(5, size - 4)]
    sell_1 = ordered.iloc[min(max(15, size // 3), size - 3)]
    buy_2 = ordered.iloc[min(max(30, size // 2), size - 2)]
    sell_2 = ordered.iloc[size - 1]

    pnl_pct_1 = (float(sell_1["close"]) / float(buy_1["close"]) - 1) if float(buy_1["close"]) else 0.0
    pnl_pct_2 = (float(sell_2["close"]) / float(buy_2["close"]) - 1) if float(buy_2["close"]) else 0.0

    return [
        TradePoint(
            symbol=symbol,
            name=name or symbol,
            time=buy_1["trade_time"].to_pydatetime(),
            price=float(buy_1["close"]),
            shares=1000,
            trade_type="buy",
            signal_type="真实分时样本买点A",
        ),
        TradePoint(
            symbol=symbol,
            name=name or symbol,
            time=sell_1["trade_time"].to_pydatetime(),
            price=float(sell_1["close"]),
            shares=1000,
            trade_type="sell",
            pnl_pct=pnl_pct_1,
            pnl_amount=pnl_pct_1 * float(buy_1["close"]) * 1000,
            reason="真实样本卖点A",
        ),
        TradePoint(
            symbol=symbol,
            name=name or symbol,
            time=buy_2["trade_time"].to_pydatetime(),
            price=float(buy_2["close"]),
            shares=1000,
            trade_type="buy",
            signal_type="真实分时样本买点B",
        ),
        TradePoint(
            symbol=symbol,
            name=name or symbol,
            time=sell_2["trade_time"].to_pydatetime(),
            price=float(sell_2["close"]),
            shares=1000,
            trade_type="sell",
            pnl_pct=pnl_pct_2,
            pnl_amount=pnl_pct_2 * float(buy_2["close"]) * 1000,
            reason="真实样本卖点B",
        ),
    ]


def test_trade_visualizer():
    """测试交易可视化器。"""
    print("=" * 70)
    print("交易可视化功能测试（真实分时数据）")
    print("=" * 70)

    visualizer = TradeVisualizer(output_dir="reports")
    print(f"\nPlotly可用: {visualizer.has_plotly}")

    symbol, intraday_data = get_intraday_sample(min_rows=120)
    trade_points = _build_trade_points(symbol, intraday_data, name=symbol)

    print(f"\n使用真实分时样本: {symbol}, {len(intraday_data)} 条")
    output_file = visualizer.generate_intraday_chart(
        symbol=symbol,
        intraday_data=intraday_data,
        trade_points=trade_points,
        show_markers=True,
        title=f"{symbol} 真实分时图测试",
    )

    print(f"分时图已生成: {output_file}")
    assert output_file
    assert Path(output_file).exists()


def test_with_real_data():
    """使用真实推荐与真实分时数据测试完整链路。"""
    print("\n" + "=" * 70)
    print("真实数据可视化测试")
    print("=" * 70)

    db = get_history_recommendation_db()
    stats = db.get_statistics()
    print(f"\n数据库统计:")
    print(f"  推荐记录: {stats.get('total_recommendations', 0)}条")
    print(f"  分时数据: {stats.get('total_intraday_records', 0):,}条")

    assert stats.get("total_recommendations", 0) > 0
    assert stats.get("total_intraday_records", 0) > 0

    config = BacktestConfig(
        initial_capital=100000,
        position_size=0.2,
        max_positions=5,
    )

    print("\n运行回测...")
    backtest = EventDrivenBacktest(db=db, config=config)

    recommendations = db.get_recommendations()
    dates = [r["recommendation_date"] for r in recommendations if r.get("recommendation_date")]
    assert dates, "真实推荐记录为空"

    dates.sort()
    start_date = dates[0]
    end_date = dates[-1]
    results = backtest.run(start_date, end_date, show_progress=False)

    print(f"\n回测完成: {len(backtest.trades)} 笔交易")
    assert isinstance(results, dict)
    assert backtest.trades

    traded_symbols = list(dict.fromkeys(t.symbol for t in backtest.trades))
    print(f"涉及股票: {traded_symbols[:5]}")

    intraday_data_dict = {}
    for symbol in traded_symbols:
        df = db.get_intraday_data(symbol)
        if not df.empty:
            intraday_data_dict[symbol] = df
        if len(intraday_data_dict) >= 3:
            break

    assert intraday_data_dict, "回测涉及股票未找到对应真实分时数据"

    report_file = generate_multi_stock_report(
        symbols=list(intraday_data_dict.keys()),
        intraday_data_dict=intraday_data_dict,
        trades=backtest.trades,
        output_dir="reports",
    )

    print(f"\n多股票报告已生成: {report_file}")
    assert report_file
    assert Path(report_file).exists()


if __name__ == "__main__":
    print("\n" + "=" * 70)
    print("交易可视化功能测试")
    print("=" * 70)

    test_trade_visualizer()
    test_with_real_data()

    print("\n" + "=" * 70)
    print("所有测试完成！")
    print("=" * 70)
