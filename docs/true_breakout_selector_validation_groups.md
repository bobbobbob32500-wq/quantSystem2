# true_breakout_selector validation groups

Version: `selector_validation_groups_v1`

## Group A: full-sample validation
Goal:
- overall coverage + purity baseline

Outputs:
- A/C retained counts and rates
- candidate pool A share

## Group B: top-bucket validation
Goal:
- test whether ranking pushes A upward

Buckets:
- Top 10%
- Top 20%
- Top 30%

Outputs:
- A share per bucket
- enrichment lift per bucket

## Group C: axis-ablation validation (design-only)
Goal:
- verify axis necessity without trading performance evaluation

Ablation plans:
- remove industry axis
- remove chip axis
- remove auxiliary platform axis

Outputs:
- change in A coverage
- change in top-bucket A enrichment
- rule-health drift

