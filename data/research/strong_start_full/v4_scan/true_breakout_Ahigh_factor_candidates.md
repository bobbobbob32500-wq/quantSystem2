# true_breakout_Ahigh_factor_candidates

## Target shift
- old objective: raise A share
- new objective: raise A_high share while suppressing selected_C and demoting selected_G

## Layer 1: A_high hard-filter candidates
- (none strict enough; keep minimal hard-filter)

## Layer 2: A_high continuous-score candidates
- f_ind_peer_strong_count
- score_trend_axis_single
- f_platform_compress_ratio
- score_total
- f_strength_rs20_xsec_q
- score_chip_axis_single

## Layer 3: demoted / observe
- f_chip_winner_rate
- score_industry_axis_single
- score_platform_axis_single

## Notes on required factors
- `f_ind_peer_strong_count`: keep, but avoid heat-overweight (better as controlled score).
- `f_platform_compress_ratio`: keep and strengthen as structure-quality anchor.
- `score_trend_axis_single`: keep as core trend-quality expression.
- `f_chip_winner_rate`: demote from core because it can lift C/G pseudo-strong cases in this window.
- `score_industry_axis_single`: demote or cap; current direction over-admits heat C.
- `score_platform_axis_single`: decompose/repair before re-promoting; current aggregate sign is unstable.