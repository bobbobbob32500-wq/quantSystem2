# Outer Path A Tier-2 Rebuild Review

This round only rebuilds Tier-2 source from outer Path A (outside F3 strict pool).

## Frozen premise
- F3 is kept unchanged as high-purity Tier-1
- No selector structure changes
- No buy-point/sell-point/full backtest

## Search space
- outer_pathA_pool = path_source='A' and not(F3)
- outer_pathA_pool size: 10, days: 10

## Candidate tiers
- S1_precision: priority_tag=0 + score/platform/industry/compress strict gate
- S2_balanced: score/platform/industry/compress moderate gate
- S3_frequency: score/platform/industry + non-missing compression gate

## All-window quick compare
- F3: n=7, days=7, A_high=71.43%, C=28.57%, win_t2=85.71%
- outer_pathA_pool: n=10, days=10, A_high=20.00%, C=30.00%, win_t2=30.00%
- S1: n=2, days=2, A_high=100.00%, C=0.00%, win_t2=100.00%
- S2: n=3, days=3, A_high=66.67%, C=0.00%, win_t2=100.00%
- S3: n=7, days=7, A_high=28.57%, C=42.86%, win_t2=42.86%

## Recommendation
- Best Tier-2 candidate this round: S1_precision
- Reason: best trade-off between quality and usable frequency under current tiny outer Path A sample.

## Boundary
- This is candidate-layer judgment only; no new controller/buy-point run in this round.