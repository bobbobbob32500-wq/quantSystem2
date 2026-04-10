# True Breakout Buy Signal V1.1 (Minimal Iteration)

V1.1 keeps selector frozen and only applies minimal buy-signal adaptations.

## Minimal changes vs V1
- Path-aware signal priority: Path A prefers breakout/range before pullback.
- Path A breakout confirm lightly relaxed (volume threshold and hold bars).
- Path A range break uses shorter/faster consolidation window.

## Why
- V1 audit showed Path A / priority_tag=1 under-triggered.
- V1 was structurally pullback-heavy and Path B-biased.

## Run
- python scripts/run_true_breakout_buy_signal_v1_1.py

## Outputs
- true_breakout_buy_signal_v1_1.csv
- true_breakout_buy_signal_v1_1_summary.csv
- true_breakout_buy_signal_v1_1_summary.json

## Boundaries
- no selector changes
- no sell logic
- no full backtest