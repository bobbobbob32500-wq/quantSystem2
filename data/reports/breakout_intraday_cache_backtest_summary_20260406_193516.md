# Breakout Intraday Cache Backtest Summary

## Data Pipeline
- watchlist csv: D:\HuaweiAI\quantSystem2\data\reports\breakout_watchlist_history_latest.csv
- intraday cache dir: D:\HuaweiAI\quantSystem2\data\intraday_cache
- daily db: D:\HuaweiAI\quantSystem2\data\database\quant_system.db

## Coverage
- watchlist rows: 614
- rows with next trade date (T+1): 614
- rows with matched cache file: 613
- rows with entry-day minute bars: 613
- rows with valid buy signal: 133
- executed trades: 133
- intraday cache files parsed: 373

## Performance
### ret_close0
- n: 133
- win_rate: 75.94%
- mean: 2.39%
- median: 1.67%
- profit_factor: 9.98

### ret_t1
- n: 133
- win_rate: 75.94%
- mean: 3.01%
- median: 2.39%
- profit_factor: 8.12

### ret_t2
- n: 133
- win_rate: 75.94%
- mean: 3.32%
- median: 2.82%
- profit_factor: 6.51

### ret_t3
- n: 133
- win_rate: 75.94%
- mean: 3.58%
- median: 3.05%
- profit_factor: 6.29

## Grade Breakdown (T+1)
- Grade A: n=1, win=100.00%, mean=12.98%, pf=NA
- Grade B: n=132, win=75.76%, mean=2.93%, pf=7.89
