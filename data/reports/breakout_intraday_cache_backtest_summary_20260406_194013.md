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
- rows with valid buy signal: 20
- blocked by limit-up guard: 0
- blocked by no-fill bar range: 10486
- blocked by invalid entry/cost data: 0
- executed trades: 20
- intraday cache files parsed: 373

## Cost Assumption
- buy slippage: 10.0 bps
- sell slippage: 10.0 bps
- buy commission: 3.0 bps
- sell commission: 3.0 bps
- stamp duty (sell): 10.0 bps

## Performance
### ret_close0
- n: 20
- win_rate: 30.00%
- mean: -0.23%
- median: -0.14%
- profit_factor: 0.45

### ret_t1
- n: 20
- win_rate: 50.00%
- mean: 0.36%
- median: -0.02%
- profit_factor: 1.29

### ret_t2
- n: 20
- win_rate: 60.00%
- mean: 1.11%
- median: 1.29%
- profit_factor: 2.08

### ret_t3
- n: 20
- win_rate: 70.00%
- mean: 2.16%
- median: 2.07%
- profit_factor: 3.38

## Portfolio (Net T+1)
- equal-weight: total=5.70%, mdd=-10.34%, sharpe=1.37
- A/B position-weight: total=2.79%, mdd=-5.47%, sharpe=1.17
## Grade Breakdown (T+1)
- Grade A: n=4, win=25.00%, mean=-0.18%, pf=0.76
- Grade B: n=16, win=56.25%, mean=0.49%, pf=1.37
