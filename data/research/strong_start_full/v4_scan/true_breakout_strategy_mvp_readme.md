# True Breakout Strategy MVP

## Frozen strategy conclusion
- Main system: `v3.2_candidate`
- Enhancement tag: `v3.1_relaxed`
- `priority_tag = 1 if (pass_v3_2_candidate == 1 and pass_v3_1_relaxed == 1) else 0`
- Current stage does **not** enter buy-point research.

## What this MVP does
- Generates core candidate pool using frozen Scheme B logic.
- Adds `priority_tag` layer within the core pool.
- Exports fixed-horizon lightweight return review (`T+1/T+2/T+3` close vs `T+1` open).

## How to run
- Script: `D:/HuaweiAI/quantSystem2/scripts/run_true_breakout_strategy_mvp.py`
- Command: `python D:/HuaweiAI/quantSystem2/scripts/run_true_breakout_strategy_mvp.py`
- Output dir: `D:/HuaweiAI/quantSystem2/data/research/strong_start_full/v4_scan/`

## Current boundaries
- No buy-point logic
- No sell-point logic
- No full backtest
- No parameter optimization