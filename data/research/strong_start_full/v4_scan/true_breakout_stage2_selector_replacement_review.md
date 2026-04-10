# Stage2 Selector Replacement Validation

- Baseline: `R2_base_daily_top1`
- Candidate: `R2_ind55_rs20q30`

## Replacement Criteria
1. A_high recall must improve.
2. A_high/C must not materially worsen (delta >= -0.05).
3. T+2 win must not materially worsen (delta >= -0.02).
4. Main/confirm windows must not flip direction (no sharp purity+win reverse).

## Decision
- `crit1_recall_up`: False
- `crit2_purity_not_worse`: True
- `crit3_win_not_worse`: True
- `crit4_no_window_flip`: True
- `final_replace_decision`: False

## Full-year Key Delta
- A_high_recall_delta: -1.0317%
- A_high/C delta: 0.2333
- T+2 win delta: 3.43%
- T+2 mean delta: 0.53%