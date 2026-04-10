# F3.2 Frequency Boost Review

Goal: improve signal frequency while keeping strong-stock profile.

## Logic (frozen selector unchanged)
- strict base: priority_tag=1 & path_source=A & F3 thresholds
- supplement only on strict-empty days:
  - rank_global_after_merge<=2
  - score_total>=0.68
  - score_platform_axis_single<=0.68
  - score_industry_axis_single<=0.86
  - f_platform_compress_ratio>=0.33
- one stock per signal day (daily top1 by score_total)

## Headline
- trading days (main+confirm): 115
- target (>=1 stock per 3 days): >= 39 days
- F3 strict days: 7 | F3.2 days: 39 | added: 32
- F3 strict n: 7 | F3.2 n: 39

## Outputs
- pool: true_breakout_f3_2_pool.csv
- summary: true_breakout_f3_2_summary.csv