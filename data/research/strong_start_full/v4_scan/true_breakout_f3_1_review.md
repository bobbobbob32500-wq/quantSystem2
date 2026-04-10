# F3.1 Strict+Relaxed Fallback Review

Goal: increase signal frequency without breaking strong-stock character.

## Frozen logic
- Base pool: strict_pool = priority_tag=1 & path_source=A
- F3 strict: platform<=0.64 & industry<=0.90 & compress>=0.33
- F3.1: strict first; if day has no strict signal, allow one relaxed fallback:
  - platform<=0.66 & industry<=0.90 & compress>=0.30

## Headline
- F3 days: 7 | F3.1 days: 8 | added days: 1
- F3 n: 7 | F3.1 n: 8

## Outputs
- pool: true_breakout_f3_1_pool.csv
- summary: true_breakout_f3_1_summary.csv