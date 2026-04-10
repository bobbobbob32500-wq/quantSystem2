# True Breakout Buy Signal Prod V1 Review

Production input is frozen and reused directly:
- Tier-1: F3
- Tier-2: T2_S4_pri0_breadth

## What changed vs baseline
- Baseline: current default unified buy signal logic (v1.1).
- Prod_v1: tier-aware buy signal routing with minimal conservative gate for T2_S4.

## Headline metrics
- input samples: 12 (F3=7, T2_S4=5)
- trigger_rate all: baseline=41.67%, prod_v1=33.33%
- trigger_rate F3: baseline=42.86%, prod_v1=42.86%
- trigger_rate T2_S4: baseline=40.00%, prod_v1=20.00%
- win_t2 all(triggered): baseline=60.00%, prod_v1=75.00%
- win_t2 F3(triggered): baseline=100.00%, prod_v1=100.00%
- win_t2 T2_S4(triggered): baseline=0.00%, prod_v1=0.00%

## Boundaries kept
- selector unchanged (v3.2/v3.1/priority_tag unchanged)
- no sell logic, no full backtest, no parameter search

## Run
- python scripts/run_true_breakout_buy_signal_prod_v1.py