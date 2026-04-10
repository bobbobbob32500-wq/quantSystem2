# true_breakout_trend_axis_failure_report

- window: 20251230 ~ 20260330
- quadrant counts: selected_A=143, selected_C=334, missed_A=1283, rejected_C=2269

## Why trend axis failed near-term
- Trend-related high-beta factors are lifting both A and C; selected_C receives equal or stronger lift on several short/medium momentum proxies.
- The axis has weak A-vs-C separation at the selected frontier, so it behaves like hotness ranking, not true-start discrimination.
- missed_A cluster includes many moderate-trend but structurally valid A events that are not extreme on momentum shells.

## Most misleading trend atoms (selected_A vs selected_C)
               feature  selected_A_minus_selected_C  selected_C_minus_rejected_C  factor_type_judgement    suggested_action
      f_strength_ret60                    -0.144514                     0.404759 pseudo_strength_factor downgrade_or_remove
f_trend_close_ma60_gap                    -0.080897                     0.249663 pseudo_strength_factor downgrade_or_remove
 f_strength_vs_index20                    -0.072873                     0.266805 pseudo_strength_factor downgrade_or_remove

## Most useful trend atoms (A recovery)

## Repair directions (trend-axis only, no new version)
1) Keep one core trend atom (rs20 quantile) and demote duplicated momentum shells (ret20/ret60/ma60-gap style) to auxiliary with capped contribution. [solve C leakage]
2) Add trend-quality preference over trend-amplitude in trend axis composition (favor stable relative-strength rank over bursty short-return proxies). [solve C leakage]
3) Add A-recovery tie-break inside trend axis for moderate but stable trend names to avoid missing A that are not momentum-extreme. [solve A misses]
