# 技术指标分析模块使用指南

## 概述

本模块提供了完整的技术指标计算、分析和可视化功能,支持常用的技术指标包括:
- 移动平均线 (MA, EMA, SMA, WMA)
- MACD指标
- KDJ随机指标
- RSI相对强弱指标
- 布林带 (BOLL)
- ATR平均真实波幅
- OBV能量潮指标
- WR威廉指标
- CCI顺势指标
- DMI动向指标
- SAR抛物线指标
- BIAS乖离率
- ROC变动率

## 模块结构

```
src/modules/
├── technical_indicators.py      # 技术指标计算模块
└── indicator_visualization.py   # 技术指标可视化模块

examples/
└── technical_indicators_example.py  # 使用示例
```

## 快速开始

### 1. 基础指标计算

```python
from src.modules.technical_indicators import TechnicalIndicators
import pandas as pd

# 假设df是包含OHLCV数据的DataFrame
# 计算MA
ma20 = TechnicalIndicators.MA(df['close'], 20)

# 计算RSI
rsi = TechnicalIndicators.RSI(df['close'], 14)

# 计算MACD
macd = TechnicalIndicators.MACD(df['close'])
print(macd['macd'], macd['signal'], macd['histogram'])

# 计算KDJ
kdj = TechnicalIndicators.KDJ(df['high'], df['low'], df['close'])
print(kdj['K'], kdj['D'], kdj['J'])

# 计算布林带
boll = TechnicalIndicators.BOLL(df['close'], 20, 2.0)
print(boll['upper'], boll['middle'], boll['lower'])
```

### 2. 使用指标分析器

```python
from src.modules.technical_indicators import IndicatorAnalyzer

# 创建分析器
analyzer = IndicatorAnalyzer(df)

# 计算所有常用指标
df_with_indicators = analyzer.calculate_all_indicators()

# 获取交易信号
signals = analyzer.get_signals()

# 获取指标统计摘要
summary = analyzer.get_indicator_summary()
```

### 3. 自定义指标计算

```python
from src.modules.technical_indicators import calculate_indicators_for_stock

# 只计算指定的指标
indicators = ['MA5', 'MA20', 'RSI', 'MACD', 'KDJ']
df_custom = calculate_indicators_for_stock(df, indicators)
```

### 4. 可视化展示

```python
from src.modules.indicator_visualization import IndicatorVisualizer

# 创建可视化器
visualizer = IndicatorVisualizer(df_with_indicators)

# 绘制价格和移动平均线
visualizer.plot_price_and_ma()

# 绘制MACD
visualizer.plot_macd()

# 绘制KDJ
visualizer.plot_kdj()

# 绘制RSI
visualizer.plot_rsi()

# 绘制布林带
visualizer.plot_boll()

# 绘制综合分析图
visualizer.plot_all_indicators()
```

## 详细功能说明

### TechnicalIndicators 类

提供所有技术指标的计算方法:

#### 移动平均线类

- `MA(prices, window)` - 简单移动平均线
- `EMA(prices, span)` - 指数移动平均线
- `SMA(prices, window)` - 平滑移动平均线
- `WMA(prices, window)` - 加权移动平均线

#### 趋势指标

- `MACD(prices, fast=12, slow=26, signal=9)` - MACD指标
- `DMI(high, low, close, period=14)` - DMI动向指标
- `SAR(high, low, af_start=0.02, af_increment=0.02, af_max=0.2)` - SAR抛物线指标

#### 震荡指标

- `RSI(prices, period=14)` - RSI相对强弱指标
- `KDJ(high, low, close, n=9, m1=3, m2=3)` - KDJ随机指标
- `WR(high, low, close, period=14)` - WR威廉指标
- `CCI(high, low, close, period=14)` - CCI顺势指标

#### 波动率指标

- `BOLL(prices, period=20, std_dev=2.0)` - 布林带
- `ATR(high, low, close, period=14)` - ATR平均真实波幅

#### 成交量指标

- `OBV(close, volume)` - OBV能量潮指标
- `VOL_MA(volume, short=5, long=10)` - 成交量均线

#### 其他指标

- `BIAS(prices, period=6)` - BIAS乖离率
- `ROC(prices, period=12)` - ROC变动率

### IndicatorAnalyzer 类

提供综合分析功能:

#### 主要方法

- `calculate_all_indicators()` - 计算所有常用指标
- `get_signals()` - 根据指标生成交易信号
- `get_indicator_summary()` - 获取指标统计摘要

#### 交易信号说明

- `macd_golden_cross` - MACD金叉
- `macd_death_cross` - MACD死叉
- `kdj_golden_cross` - KDJ金叉
- `kdj_death_cross` - KDJ死叉
- `rsi_oversold` - RSI超卖 (< 30)
- `rsi_overbought` - RSI超买 (> 70)
- `boll_breakout_up` - 布林带上轨突破
- `boll_breakout_down` - 布林带下轨突破

### IndicatorVisualizer 类

提供可视化功能:

#### 主要方法

- `plot_price_and_ma()` - 绘制价格和移动平均线
- `plot_macd()` - 绘制MACD指标
- `plot_kdj()` - 绘制KDJ指标
- `plot_rsi()` - 绘制RSI指标
- `plot_boll()` - 绘制布林带
- `plot_all_indicators()` - 绘制综合分析图

## 实际应用示例

### 示例1: 股票技术分析

```python
from src.dao.stock_dao import StockDAO
from src.modules.technical_indicators import IndicatorAnalyzer
from src.modules.indicator_visualization import IndicatorVisualizer

# 获取股票数据
dao = StockDAO()
df = dao.get_daily_data('600519.SH', start_date='20240101', end_date='20241231')

# 计算指标
analyzer = IndicatorAnalyzer(df)
df_with_indicators = analyzer.calculate_all_indicators()

# 分析信号
signals = analyzer.get_signals()

# 查看最近的买入信号
recent_buy = signals['macd_golden_cross'].tail(10)
print("最近10天的MACD金叉信号:")
print(recent_buy[recent_buy])

# 可视化
visualizer = IndicatorVisualizer(df_with_indicators)
visualizer.plot_all_indicators()
```

### 示例2: 筛选股票

```python
from src.modules.technical_indicators import IndicatorAnalyzer

def filter_stocks_by_rsi(stock_list):
    """筛选RSI超卖的股票"""
    selected_stocks = []
    
    for stock_code in stock_list:
        df = get_stock_data(stock_code)
        analyzer = IndicatorAnalyzer(df)
        df_with_indicators = analyzer.calculate_all_indicators()
        
        # 检查RSI是否超卖
        latest_rsi = df_with_indicators['RSI'].iloc[-1]
        if latest_rsi < 30:
            selected_stocks.append({
                'code': stock_code,
                'rsi': latest_rsi
            })
    
    return selected_stocks
```

### 示例3: 生成交易报告

```python
from src.modules.indicator_visualization import create_indicator_report

# 生成完整的技术分析报告
saved_files = create_indicator_report(
    df_with_indicators,
    stock_code='600519',
    save_dir='./reports/indicators'
)

print("生成的报告文件:")
for name, path in saved_files.items():
    print(f"{name}: {path}")
```

## 指标参数说明

### MA (移动平均线)
- 常用周期: 5, 10, 20, 60, 120, 250
- 短期: 5日、10日
- 中期: 20日、60日
- 长期: 120日、250日

### MACD
- 默认参数: (12, 26, 9)
- 快线周期: 12
- 慢线周期: 26
- 信号线周期: 9

### KDJ
- 默认参数: (9, 3, 3)
- RSV周期: 9
- K值平滑周期: 3
- D值平滑周期: 3

### RSI
- 常用周期: 6, 12, 24
- 超买区域: > 70
- 超卖区域: < 30

### 布林带
- 默认参数: (20, 2.0)
- 周期: 20
- 标准差倍数: 2.0

## 注意事项

1. **数据要求**: 必须包含 open, high, low, close, volume 列
2. **数据量**: 建议至少包含100个交易日的数据
3. **缺失值**: 指标计算会自动处理缺失值,前期数据可能为NaN
4. **性能**: 对于大量股票,建议使用批量计算方式

## 扩展开发

### 添加自定义指标

```python
def calculate_custom_indicator(prices: pd.Series, period: int) -> pd.Series:
    """
    自定义指标计算函数
    
    Args:
        prices: 价格序列
        period: 周期
    
    Returns:
        指标序列
    """
    # 实现你的指标计算逻辑
    result = prices.rolling(window=period).mean()  # 示例
    return result
```

### 添加自定义信号

```python
def get_custom_signals(df: pd.DataFrame) -> Dict[str, pd.Series]:
    """生成自定义交易信号"""
    signals = {}
    
    # 示例: MA金叉
    signals['ma_golden_cross'] = (
        (df['MA5'] > df['MA20']) & 
        (df['MA5'].shift(1) <= df['MA20'].shift(1))
    )
    
    return signals
```

## 常见问题

### Q1: 为什么前期指标值为NaN?
A: 技术指标需要一定的历史数据才能计算,例如MA20需要至少20天的数据。

### Q2: 如何选择指标参数?
A: 建议使用默认参数,或根据具体股票特性进行回测优化。

### Q3: 指标信号如何组合使用?
A: 可以结合多个指标信号,例如MACD金叉 + RSI超卖作为买入信号。

### Q4: 如何处理停牌数据?
A: 建议在计算前先清理数据,移除停牌期间的记录。

## 更新日志

- v1.0.0 (2024-04-15)
  - 初始版本
  - 实现基础技术指标计算
  - 实现指标分析器
  - 实现可视化功能
  - 提供完整使用示例

## 联系方式

如有问题或建议,请联系开发团队。
