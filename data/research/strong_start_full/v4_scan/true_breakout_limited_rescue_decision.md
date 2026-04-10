# Limited Rescue Decision (2 rounds)

- round1_winner: `R1_ind55_rs30`
- round2_winner: `R2_base_R1_ind55_rs30`

## Full-year winner metrics
- selected_n=82, avg_days_per_signal=2.72
- A_high_recall_rate=1.35%, A_high/C=0.5667, A_low+C=43.90%
- T+2 mean=1.15%, median=0.39%, win=53.66%

## Window check
- main_window win_t2=61.11%
- confirm_window win_t2=59.26%

## Hard checks
- freq(2~3.2d): True
- quality floor: True
- win_t2 >= 55%: False
- window non-reverse: True

## Final: FAIL
- Decision rule: two-round rescue fails => cut this line and do not move to buy-point.