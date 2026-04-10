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
- rows with valid buy signal: 58
- blocked by limit-up guard: 0
- blocked by gap beyond max chase: 6414
- blocked by invalid entry/cost data: 0
- executed trades: 58
- intraday cache files parsed: 373

## Cost Assumption
- buy slippage: 10.0 bps
- sell slippage: 10.0 bps
- buy commission: 3.0 bps
- sell commission: 3.0 bps
- stamp duty (sell): 10.0 bps

## Performance
### ret_close0
- n: 58
- win_rate: 20.69%
- mean: -0.80%
- median: -0.58%
- profit_factor: 0.11

### ret_t1
- n: 58
- win_rate: 44.83%
- mean: 0.04%
- median: -0.21%
- profit_factor: 1.04

### ret_t2
- n: 58
- win_rate: 55.17%
- mean: 0.63%
- median: 0.34%
- profit_factor: 1.56

### ret_t3
- n: 58
- win_rate: 51.72%
- mean: 1.24%
- median: 0.08%
- profit_factor: 2.08

## Portfolio (Net T+1)
- equal-weight: total=-1.04%, mdd=-26.16%, sharpe=0.13
- A/B position-weight: total=1.84%, mdd=-12.30%, sharpe=0.58
## Grade Breakdown (T+1)
- Grade A: n=3, win=100.00%, mean=2.87%, pf=NA
- Grade B: n=55, win=41.82%, mean=-0.11%, pf=0.90
