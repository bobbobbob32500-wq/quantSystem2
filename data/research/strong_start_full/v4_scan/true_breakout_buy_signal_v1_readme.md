# True Breakout Buy Signal V1

Scope: pre-market selector output to intraday buy-signal detection.

## Frozen inputs
- Main system: v3.2_candidate
- Enhancement tag: v3.1_relaxed
- priority_tag unchanged

## V1 signal types
1. pullback_confirm
2. breakout_confirm
3. range_break_confirm

Mutual exclusivity: same timestamp conflict uses priority pullback > breakout > range.

## Outputs
- true_breakout_buy_signal_v1.csv
- true_breakout_buy_signal_v1_summary.csv

## Boundaries
- no selector changes
- no sell logic
- no full backtest