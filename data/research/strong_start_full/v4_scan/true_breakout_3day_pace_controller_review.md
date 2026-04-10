# 3-Day Pace Controller Review

Frozen selector structure is unchanged.

## Tier definition
- F3 (high-purity): priority=1 & path=A & platform<=0.64 & industry<=0.90 & compress>=0.33
- F2_only (supplement): priority=1 & path=A & industry<=0.90 & not(F3 platform+compress condition)

## Controller logic
- F3 first (daily top1 by rank_global_after_merge then score_total)
- If no F3 on a day and no trade in recent 3 trading days, allow F2_only fallback
- F2_only must pass stricter gate:
  rank<= 2, score_total>= 0.68, platform<= 0.68, industry<= 0.86, compress>= 0.33
- max 1 stock/day

## Headline
- trading days: 115
- selected days: 9 (blank ratio 92.17%)
- avg days per selected: 12.78
- selected tier share: F3=7/9, F2_only=2/9

## Outputs
- true_breakout_tiered_input_pool.csv
- true_breakout_3day_pace_controller_daily.csv
- true_breakout_3day_pace_controller_summary.csv
- true_breakout_3day_pace_controller_quality_review.csv