# -*- coding: utf-8 -*-
"""
技术指标分析使用示例
演示如何使用技术指标模块进行股票分析
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta

from src.modules.technical_indicators import (
    TechnicalIndicators,
    IndicatorAnalyzer,
    calculate_indicators_for_stock
)
from src.modules.indicator_visualization import (
    IndicatorVisualizer,
    create_indicator_report
)
from src.core.logger import get_logger

logger = get_logger("example")


def generate_sample_data(days: int = 100) -> pd.DataFrame:
    """
    生成示例股票数据
    
    Args:
        days: 天数
    
    Returns:
        包含OHLCV数据的DataFrame
    """
    dates = pd.date_range(end=datetime.now(), periods=days, freq='D')
    
    # 生成模拟价格数据
    np.random.seed(42)
    base_price = 50
    returns = np.random.normal(0, 0.02, days)
    prices = base_price * np.exp(np.cumsum(returns))
    
    # 生成OHLCV数据
    df = pd.DataFrame({
        'trade_date': dates,
        'open': prices * (1 + np.random.uniform(-0.02, 0.02, days)),
        'high': prices * (1 + np.random.uniform(0, 0.03, days)),
        'low': prices * (1 + np.random.uniform(-0.03, 0, days)),
        'close': prices,
        'volume': np.random.randint(1000000, 10000000, days)
    })
    
    return df


def example_basic_indicators():
    """基础指标计算示例"""
    print("\n" + "="*60)
    print("示例1: 基础技术指标计算")
    print("="*60)
    
    # 生成示例数据
    df = generate_sample_data(100)
    print(f"\n生成了 {len(df)} 天的示例数据")
    print(f"日期范围: {df['trade_date'].min()} 至 {df['trade_date'].max()}")
    
    # 计算单个指标
    print("\n--- 计算单个指标 ---")
    
    # MA
    ma20 = TechnicalIndicators.MA(df['close'], 20)
    print(f"MA20 最新值: {ma20.iloc[-1]:.2f}")
    
    # RSI
    rsi = TechnicalIndicators.RSI(df['close'], 14)
    print(f"RSI 最新值: {rsi.iloc[-1]:.2f}")
    
    # MACD
    macd = TechnicalIndicators.MACD(df['close'])
    print(f"MACD 最新值: {macd['macd'].iloc[-1]:.4f}")
    print(f"MACD Signal 最新值: {macd['signal'].iloc[-1]:.4f}")
    
    # KDJ
    kdj = TechnicalIndicators.KDJ(df['high'], df['low'], df['close'])
    print(f"K值 最新值: {kdj['K'].iloc[-1]:.2f}")
    print(f"D值 最新值: {kdj['D'].iloc[-1]:.2f}")
    print(f"J值 最新值: {kdj['J'].iloc[-1]:.2f}")


def example_analyzer():
    """指标分析器示例"""
    print("\n" + "="*60)
    print("示例2: 使用指标分析器")
    print("="*60)
    
    # 生成示例数据
    df = generate_sample_data(100)
    
    # 创建分析器
    analyzer = IndicatorAnalyzer(df)
    
    # 计算所有指标
    print("\n--- 计算所有技术指标 ---")
    df_with_indicators = analyzer.calculate_all_indicators()
    
    print(f"\n计算后的列数: {len(df_with_indicators.columns)}")
    print(f"新增指标列: {[col for col in df_with_indicators.columns if col not in ['open', 'high', 'low', 'close', 'volume', 'trade_date']]}")
    
    # 获取交易信号
    print("\n--- 生成交易信号 ---")
    signals = analyzer.get_signals()
    
    for signal_name, signal_series in signals.items():
        signal_count = signal_series.sum()
        print(f"{signal_name}: {signal_count} 次")
    
    # 获取指标摘要
    print("\n--- 指标统计摘要 ---")
    summary = analyzer.get_indicator_summary()
    
    for indicator, stats in summary.items():
        print(f"\n{indicator}:")
        for key, value in stats.items():
            if value is not None:
                print(f"  {key}: {value:.2f}" if isinstance(value, (int, float)) else f"  {key}: {value}")


def example_custom_indicators():
    """自定义指标计算示例"""
    print("\n" + "="*60)
    print("示例3: 自定义指标计算")
    print("="*60)
    
    # 生成示例数据
    df = generate_sample_data(100)
    
    # 只计算指定的指标
    print("\n--- 计算指定指标 ---")
    indicators_to_calculate = ['MA5', 'MA20', 'RSI', 'MACD', 'KDJ']
    
    df_custom = calculate_indicators_for_stock(df, indicators_to_calculate)
    
    print(f"\n计算的指标: {indicators_to_calculate}")
    print(f"结果列: {list(df_custom.columns)}")
    
    # 显示最新数据
    print("\n最新一天的指标值:")
    latest = df_custom.iloc[-1]
    for col in df_custom.columns:
        if col not in ['open', 'high', 'low', 'close', 'volume', 'trade_date']:
            value = latest[col]
            if pd.notna(value):
                print(f"  {col}: {value:.2f}" if isinstance(value, (int, float)) else f"  {col}: {value}")


def example_visualization():
    """可视化示例"""
    print("\n" + "="*60)
    print("示例4: 技术指标可视化")
    print("="*60)
    
    # 生成示例数据
    df = generate_sample_data(100)
    
    # 计算所有指标
    analyzer = IndicatorAnalyzer(df)
    df_with_indicators = analyzer.calculate_all_indicators()
    
    # 创建可视化器
    visualizer = IndicatorVisualizer(df_with_indicators)
    
    print("\n--- 可视化图表 ---")
    print("1. 价格与移动平均线")
    print("2. MACD指标")
    print("3. KDJ指标")
    print("4. RSI指标")
    print("5. 布林带")
    print("6. 综合分析图")
    
    # 注意: 实际运行时会显示图表
    # 这里仅作演示,不实际显示
    print("\n提示: 调用相应的方法可以显示图表")
    print("例如: visualizer.plot_price_and_ma()")
    print("     visualizer.plot_macd()")
    print("     visualizer.plot_all_indicators()")


def example_real_stock_analysis():
    """真实股票分析示例"""
    print("\n" + "="*60)
    print("示例5: 真实股票数据分析")
    print("="*60)
    
    # 这里演示如何使用真实数据
    print("\n使用真实数据的步骤:")
    print("1. 从数据源获取股票OHLCV数据")
    print("2. 创建IndicatorAnalyzer实例")
    print("3. 调用calculate_all_indicators()计算指标")
    print("4. 使用get_signals()获取交易信号")
    print("5. 使用IndicatorVisualizer进行可视化")
    
    print("\n示例代码:")
    print("""
# 从数据库或API获取数据
from src.dao.stock_dao import StockDAO

dao = StockDAO()
df = dao.get_daily_data('600519.SH', start_date='20240101', end_date='20241231')

# 计算指标
analyzer = IndicatorAnalyzer(df)
df_with_indicators = analyzer.calculate_all_indicators()

# 获取信号
signals = analyzer.get_signals()

# 可视化
visualizer = IndicatorVisualizer(df_with_indicators)
visualizer.plot_all_indicators()
    """)


def example_indicator_signals():
    """指标信号分析示例"""
    print("\n" + "="*60)
    print("示例6: 指标信号分析")
    print("="*60)
    
    # 生成示例数据
    df = generate_sample_data(100)
    
    # 计算指标
    analyzer = IndicatorAnalyzer(df)
    df_with_indicators = analyzer.calculate_all_indicators()
    signals = analyzer.get_signals()
    
    print("\n--- 信号统计 ---")
    
    # MACD信号
    macd_golden = signals['macd_golden_cross'].sum()
    macd_death = signals['macd_death_cross'].sum()
    print(f"\nMACD金叉: {macd_golden} 次")
    print(f"MACD死叉: {macd_death} 次")
    
    # KDJ信号
    kdj_golden = signals['kdj_golden_cross'].sum()
    kdj_death = signals['kdj_death_cross'].sum()
    print(f"\nKDJ金叉: {kdj_golden} 次")
    print(f"KDJ死叉: {kdj_death} 次")
    
    # RSI信号
    rsi_oversold = signals['rsi_oversold'].sum()
    rsi_overbought = signals['rsi_overbought'].sum()
    print(f"\nRSI超卖: {rsi_oversold} 次")
    print(f"RSI超买: {rsi_overbought} 次")
    
    # 布林带信号
    boll_up = signals['boll_breakout_up'].sum()
    boll_down = signals['boll_breakout_down'].sum()
    print(f"\n布林带上轨突破: {boll_up} 次")
    print(f"布林带下轨突破: {boll_down} 次")
    
    # 综合信号分析
    print("\n--- 综合信号分析 ---")
    
    # 找出所有买入信号
    buy_signals = (
        signals['macd_golden_cross'] |
        signals['kdj_golden_cross'] |
        signals['rsi_oversold']
    )
    
    # 找出所有卖出信号
    sell_signals = (
        signals['macd_death_cross'] |
        signals['kdj_death_cross'] |
        signals['rsi_overbought']
    )
    
    print(f"\n综合买入信号: {buy_signals.sum()} 次")
    print(f"综合卖出信号: {sell_signals.sum()} 次")


def main():
    """运行所有示例"""
    print("\n" + "="*60)
    print("技术指标分析模块使用示例")
    print("="*60)
    
    try:
        # 运行各个示例
        example_basic_indicators()
        example_analyzer()
        example_custom_indicators()
        example_visualization()
        example_real_stock_analysis()
        example_indicator_signals()
        
        print("\n" + "="*60)
        print("所有示例运行完成!")
        print("="*60)
        
    except Exception as e:
        logger.error(f"示例运行失败: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
