# true_breakout_selector_v3_fast_coarse_tuning_review

## Stage A (quota + heat-cap, fixed cutoff A/B=15%)
- Best: quota 1:2, heat-cap `high`
- A-share: 0.4465 (baseline 0.3539)
- Sample n: 159

## Stage B (cutoff refine on Stage-A winner)
- Best cutoff: PathA 10%, PathB 20%
- A-share: 0.4410
- Sample n: 161
- Path contribution A/B: 57/114

## Quick confirm (adjacent non-overlap window)
- Window: 20250929 ~ 20251229
- A-share: 0.4074
- Sample n: 162

## Final candidate
- quota: 1:2
- heat-cap: high
- cutoff A/B: 10% / 20%