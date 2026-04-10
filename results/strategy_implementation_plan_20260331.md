# 强势回调缩量二次启动策略 - 实现规划

## 策略概览

**策略名称**：强势回调缩量的二次启动模型  
**交易周期**：3-5天短线  
**选股时间**：盘前9:00-9:25  
**目标标的数**：10-15只  
**持仓规则**：单票≤20%，总仓≤80%

---

## 17个选股条件映射

### 第一层：硬过滤（风险排除）

```python
# 条件1：板块过滤 - 仅沪深主板
def filter_mainboard(df):
    """保留沪深主板A股"""
    sh_codes = df['ts_code'].str.startswith(('600', '601', '603', '605'))
    sz_codes = df['ts_code'].str.startswith(('000', '001', '002'))
    exclude = df['ts_code'].str.startswith(('300', '688'))
    return df[(sh_codes | sz_codes) & ~exclude]

# 条件2：交易状态过滤
def filter_trading_status(df):
    """排除停牌/暂停交易"""
    return df[(df['is_suspended'] == 0) & (df['volume'] > 0)]

# 条件3：风险标识过滤
def filter_risk_labels(df):
    """排除ST/*ST/退市整理"""
    risk_keywords = ['ST', '*ST', '退']
    mask = ~df['name'].str.contains('|'.join(risk_keywords), na=False)
    return df[mask]

# 条件4：次新过滤 - 上市≥60交易日
def filter_new_stock(df, current_date):
    """排除上市<60交易日的股票"""
    trading_days_since_ipo = (current_date - df['ipo_date']).dt.days / 1.4  # 近似
    return df[trading_days_since_ipo >= 60]
```

### 第二层：强势确认（信号来源）

```python
# 条件5：近期涨停 - 10日内1-2次
def identify_limit_up(df):
    """识别涨停日"""
    df['is_limit_up'] = (df['close'] >= df['close'].shift(1) * 1.098) & \
                        (df['high'] == df['close'])
    return df

def filter_recent_limit_up(df, lookback=10):
    """10日内1-2次涨停"""
    df['limit_up_count_10d'] = df['is_limit_up'].rolling(lookback).sum()
    return df[df['limit_up_count_10d'].isin([1, 2])]

# 条件6：涨停日换手[5%,20%]
def filter_limit_up_turnover(df):
    """涨停日换手率过滤"""
    df['turnover_rate'] = df['volume'] / df['float_shares']
    limit_up_days = df[df['is_limit_up']]
    return limit_up_days[(limit_up_days['turnover_rate'] >= 0.05) & 
                         (limit_up_days['turnover_rate'] <= 0.20)]

# 条件7：涨停次日不崩 - 回撤≥-3%
def filter_limit_up_next_day(df):
    """涨停次日回撤≥-3%"""
    df['return_next_day'] = df['close'].shift(-1) / df['close'] - 1
    limit_up_days = df[df['is_limit_up']]
    return limit_up_days[limit_up_days['return_next_day'] >= -0.03]
```

### 第三层：回调缩量（低风险入场）

```python
# 条件8：回调时间窗口 - 距涨停2-5天
def filter_drawdown_window(df):
    """距最近涨停2-5天"""
    df['days_since_limit_up'] = (df.index - df[df['is_limit_up']].index[-1]).days
    return df[(df['days_since_limit_up'] >= 2) & (df['days_since_limit_up'] <= 5)]

# 条件9：回调幅度2%-8%
def filter_drawdown_magnitude(df):
    """回撤幅度2%-8%"""
    peak_close = df['close'].rolling(window=20).max()
    drawdown = 1 - df['close'] / peak_close
    return df[(drawdown >= 0.02) & (drawdown <= 0.08)]

# 条件10：缩量回调
def filter_volume_shrink(df):
    """VOL≤0.80×SMA(VOL,5) 且 SMA(VOL,5)≥SMA(VOL,20)"""
    df['sma_vol_5'] = df['volume'].rolling(5).mean()
    df['sma_vol_20'] = df['volume'].rolling(20).mean()
    return df[(df['volume'] <= 0.80 * df['sma_vol_5']) & 
              (df['sma_vol_5'] >= df['sma_vol_20'])]

# 条件11：趋势支撑
def filter_trend_support(df):
    """MA5>MA10, Close≥MA10, Close贴近MA5"""
    df['ma5'] = df['close'].rolling(5).mean()
    df['ma10'] = df['close'].rolling(10).mean()
    
    ma5_above_ma10 = df['ma5'] > df['ma10']
    close_above_ma10 = df['close'] >= df['ma10']
    close_near_ma5 = abs(df['close'] / df['ma5'] - 1) <= 0.02
    
    return df[ma5_above_ma10 & close_above_ma10 & close_near_ma5]

# 条件12：避免追高 - 昨日非涨停收盘
def filter_not_limit_up_yesterday(df):
    """昨日非涨停收盘"""
    yesterday_limit_up = df['is_limit_up'].shift(1)
    return df[~yesterday_limit_up]
```

### 第四层：盘前过滤（追高防线）

```python
# 条件13：高开过滤 - Open_t/Close_{t-1} ∈ [-1%,+2%]
def filter_open_price(df, open_price_today):
    """集合竞价高开过滤"""
    yesterday_close = df['close'].iloc[-1]
    open_ratio = open_price_today / yesterday_close - 1
    
    if -0.01 <= open_ratio <= 0.02:
        return True  # 通过过滤
    else:
        return False  # 被过滤
```

### 第五层：流动性与风险（可交易性）

```python
# 条件14-15：成交额[1亿,30亿]
def filter_trading_amount(df):
    """成交额下限1亿、上限30亿"""
    df['amt'] = df['close'] * df['volume']
    df['sma_amt_20'] = df['amt'].rolling(20).mean()
    return df[(df['sma_amt_20'] >= 1e8) & (df['sma_amt_20'] <= 3e9)]

# 条件16：价格下限≥3元
def filter_price_floor(df):
    """排除过低价格"""
    return df[df['close'] >= 3.0]

# 条件17：近20日无跌停
def filter_no_limit_down(df):
    """近20日无跌停"""
    df['is_limit_down'] = (df['close'] <= df['close'].shift(1) * 0.902) & \
                          (df['low'] == df['close'])
    limit_down_count_20d = df['is_limit_down'].rolling(20).sum()
    return df[limit_down_count_20d == 0]
```

---

## 选股流程实现

```python
class SecondStartupSelector:
    """强势回调缩量二次启动选股器"""
    
    def __init__(self, config, db):
        self.config = config
        self.db = db
    
    def run_selection(self, end_date=None):
        """盘前选股主流程"""
        
        # 第一步：生成基础股票池（9:00-9:05）
        basic_pool = self._generate_basic_pool(end_date)
        print(f"基础股票池: {len(basic_pool)} 只")
        
        # 第二步：强势确认筛选（9:05-9:15）
        strong_pool = self._filter_strong_confirmation(basic_pool)
        print(f"强势候选池: {len(strong_pool)} 只")
        
        # 第三步：回调缩量与支撑确认（9:15-9:20）
        structure_pool = self._filter_structure_confirmation(strong_pool)
        print(f"结构候选池: {len(structure_pool)} 只")
        
        # 第四步：集合竞价高开过滤（9:20-9:25）
        # 需要9:25后的开盘价数据
        final_pool = self._filter_open_price(structure_pool)
        print(f"最终候选池: {len(final_pool)} 只")
        
        # 第五步：控制数量到10-15只（9:25-9:28）
        selected = self._rank_and_limit(final_pool)
        print(f"最终选股结果: {len(selected)} 只")
        
        return selected
    
    def _generate_basic_pool(self, end_date):
        """第一步：基础股票池"""
        df = self.db.query_daily_data(end_date)
        df = filter_mainboard(df)
        df = filter_trading_status(df)
        df = filter_risk_labels(df)
        df = filter_new_stock(df, end_date)
        return df
    
    def _filter_strong_confirmation(self, df):
        """第二步：强势确认"""
        df = identify_limit_up(df)
        df = filter_recent_limit_up(df)
        df = filter_limit_up_turnover(df)
        df = filter_limit_up_next_day(df)
        return df
    
    def _filter_structure_confirmation(self, df):
        """第三步：回调缩量与支撑"""
        df = filter_drawdown_window(df)
        df = filter_drawdown_magnitude(df)
        df = filter_volume_shrink(df)
        df = filter_trend_support(df)
        df = filter_not_limit_up_yesterday(df)
        return df
    
    def _filter_open_price(self, df, open_price_today):
        """第四步：集合竞价高开过滤"""
        # 需要9:25后的开盘价
        return df[df.apply(lambda row: filter_open_price(row, open_price_today), axis=1)]
    
    def _rank_and_limit(self, df):
        """第五步：排序限制"""
        # 按近20日相对强度排序
        df['rs20'] = df['close'] / df['close'].shift(20) - 1
        df = df.sort_values('rs20', ascending=False)
        return df.head(15)
```

---

## 数据结构设计

```python
# 选股结果数据结构
class SecondStartupSignal:
    """二次启动信号"""
    
    def __init__(self):
        self.ts_code = None           # 股票代码
        self.name = None              # 股票名称
        self.signal_date = None       # 信号日期
        self.signal_type = 'second_startup'
        
        # 强势确认指标
        self.limit_up_date = None     # 最近涨停日
        self.limit_up_count_10d = 0   # 10日涨停次数
        self.limit_up_turnover = 0.0  # 涨停日换手率
        
        # 回调缩量指标
        self.days_since_limit_up = 0  # 距涨停天数
        self.drawdown_pct = 0.0       # 回撤幅度
        self.volume_ratio = 0.0       # 成交量比
        
        # 趋势支撑指标
        self.ma5 = 0.0
        self.ma10 = 0.0
        self.close = 0.0
        self.distance_to_ma5 = 0.0    # 距MA5距离
        
        # 流动性指标
        self.sma_amt_20 = 0.0         # 20日均成交额
        self.turnover_rate = 0.0      # 换手率
        
        # 排序指标
        self.rs20 = 0.0               # 20日相对强度
        self.rank = 0                 # 排序排名
        
        # 预期收益（回测用）
        self.expected_return_3d = 0.0
        self.expected_return_5d = 0.0
```

---

## 回测框架设计

```python
class SecondStartupBacktest:
    """二次启动策略回测框架"""
    
    def __init__(self, config, db):
        self.config = config
        self.db = db
        self.selector = SecondStartupSelector(config, db)
    
    def run_signal_level_backtest(self, start_date, end_date):
        """信号层回测 - 评估选股信号的前瞻收益"""
        
        results = []
        
        for date in self._get_trading_dates(start_date, end_date):
            # 盘前选股
            signals = self.selector.run_selection(date)
            
            for signal in signals:
                # 计算前瞻收益
                r3 = self._get_forward_return(signal.ts_code, date, 3)
                r5 = self._get_forward_return(signal.ts_code, date, 5)
                
                results.append({
                    'date': date,
                    'ts_code': signal.ts_code,
                    'open_price': self._get_open_price(signal.ts_code, date),
                    'return_3d': r3,
                    'return_5d': r5,
                    'win_3d': 1 if r3 > 0 else 0,
                    'win_5d': 1 if r5 > 0 else 0,
                })
        
        # 统计指标
        df = pd.DataFrame(results)
        stats = {
            'total_signals': len(df),
            'win_rate_3d': df['win_3d'].mean(),
            'win_rate_5d': df['win_5d'].mean(),
            'avg_return_3d': df['return_3d'].mean(),
            'avg_return_5d': df['return_5d'].mean(),
            'median_return_3d': df['return_3d'].median(),
            'median_return_5d': df['return_5d'].median(),
            'percentile_5_3d': df['return_3d'].quantile(0.05),
            'percentile_5_5d': df['return_5d'].quantile(0.05),
        }
        
        return stats, df
    
    def run_portfolio_level_backtest(self, start_date, end_date, hold_days=5):
        """组合层回测 - 验证小资金仓位约束下的表现"""
        
        portfolio = Portfolio(max_position=0.20, max_total=0.80)
        trades = []
        
        for date in self._get_trading_dates(start_date, end_date):
            # 盘前选股
            signals = self.selector.run_selection(date)
            
            # 选择前5只建仓
            for signal in signals[:5]:
                entry_price = self._get_open_price(signal.ts_code, date)
                portfolio.add_position(signal.ts_code, entry_price, 0.16)  # 等权
            
            # 检查持仓是否到期
            for position in portfolio.positions:
                if (date - position.entry_date).days >= hold_days:
                    exit_price = self._get_close_price(position.ts_code, date)
                    pnl = (exit_price - position.entry_price) / position.entry_price
                    trades.append({
                        'ts_code': position.ts_code,
                        'entry_date': position.entry_date,
                        'exit_date': date,
                        'entry_price': position.entry_price,
                        'exit_price': exit_price,
                        'pnl_pct': pnl,
                    })
                    portfolio.remove_position(position.ts_code)
        
        # 统计指标
        df = pd.DataFrame(trades)
        stats = {
            'total_trades': len(df),
            'win_rate': (df['pnl_pct'] > 0).mean(),
            'avg_pnl': df['pnl_pct'].mean(),
            'profit_factor': df[df['pnl_pct']>0]['pnl_pct'].sum() / abs(df[df['pnl_pct']<0]['pnl_pct'].sum()),
            'max_drawdown': self._calculate_max_drawdown(df),
        }
        
        return stats, df
```

---

## 集成到系统的方案

```python
# 在 StockSelector 中添加新策略
class StockSelector:
    
    def __init__(self, config, db):
        # ... 现有代码 ...
        self.second_startup_selector = SecondStartupSelector(config, db)
    
    def run_selection(self, strategy='legacy', end_date=None):
        """支持多策略选股"""
        
        if strategy == 'legacy':
            return self._run_legacy_selection(end_date)
        elif strategy == 'second_startup':
            return self._run_second_startup_selection(end_date)
        else:
            raise ValueError(f"Unknown strategy: {strategy}")
    
    def _run_second_startup_selection(self, end_date):
        """运行二次启动策略"""
        return self.second_startup_selector.run_selection(end_date)
```

---

## 实现时间表

| 阶段 | 任务 | 工作量 | 时间 |
|------|------|--------|------|
| 1 | 数据准备（集合竞价开盘价） | 2天 | 第1-2天 |
| 2 | 条件实现（17个条件） | 5天 | 第3-7天 |
| 3 | 选股流程实现 | 3天 | 第8-10天 |
| 4 | 回测框架实现 | 4天 | 第11-14天 |
| 5 | 回测验证与参数调优 | 5天 | 第15-19天 |
| 6 | 系统集成与测试 | 3天 | 第20-22天 |

**总耗时**：约3-4周

---

**文档生成时间**：2026-03-31 12:15:00  
**下一步**：确认实现方案并开始编码
