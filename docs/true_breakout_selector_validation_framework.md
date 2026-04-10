# true_breakout_selector validation framework

Version: `selector_validation_framework_v1`
Scope: selector-only validation (no entry/exit/execution/performance)

## Validation object (frozen)
`true_breakout_selector_v1_draft` as a **selector**, validating:
1. universe + hard-filter reasonableness
2. hard-filter tight/loose balance
3. scoring-axis ranking power for true-breakout enrichment
4. downgraded-feature exclusion safety

## 4-layer validation
1. Sample coverage validation  
- A/C retained rate after universe + hard filters
- over-tight / over-loose diagnosis

2. Ranking effectiveness validation  
- whether A events are enriched in higher score buckets
- top-quantile A share lift vs full sample

3. Axis contribution validation  
- strength axis / industry-leadership axis / chip-quality axis
- identify core vs auxiliary axis

4. Rule health validation  
- filter elimination rate
- score distribution continuity (not disguised hard cuts)
- downgraded-feature exclusion impact

