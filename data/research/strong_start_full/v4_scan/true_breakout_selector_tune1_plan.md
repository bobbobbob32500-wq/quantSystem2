# true_breakout_selector_tune1 plan

## Proposed micro-tuning points (max 3)
1. Candidate threshold: Top30% -> Top25%
- Why: improve candidate purity while staying near current healthy range.
- Expected: higher A share in candidate pool, slightly lower A coverage.
- Side effect: candidate pool may shrink too much in weak regimes.

2. Platform axis downweight: 0.05 -> 0.02
- Why: platform axis is weakest; keep as auxiliary.
- Expected: reduce weak-axis noise in score_total.
- Side effect: may lose small amount of structure context.

3. Chip axis slight upweight: 0.20 -> 0.23
- Why: chip axis is sensitive and useful in prior validation.
- Expected: better A/C separation at top buckets.
- Side effect: if overdone, could increase regime sensitivity.
