# Stage2 Selector Round2 (Recall-first then quality gate)

## Summary
- Baseline uses mainline_current daily top1 as selected set.
- Recall denominator is full-universe mapping (not selected subset).
- This round only tests lightweight quality gates on top of daily top1.
- Best candidate: R2_ind55_rs20q30

## Best full-year metrics
- selected_n=82, signal_days=82, avg_days_per_signal=2.72
- A_high_recall_rate=1.35%, A_high/C=0.5667, A_low+C=43.90%
- mean_ret_t2=1.15%, median_ret_t2=0.39%, win_t2=53.66%

## Decision
- Keep selector optimization on this stage; buy-point strengthening should remain after selector crosses target line.