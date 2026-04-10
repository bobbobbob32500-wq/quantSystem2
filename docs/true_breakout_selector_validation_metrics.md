# true_breakout_selector validation metrics

Version: `selector_validation_metrics_v1`

## Allowed metrics (selector validity only)
1. Coverage
- A coverage rate: retained A / total A
- C coverage rate: retained C / total C
- candidate pool size and candidate ratio

2. Purity / enrichment
- A share in candidate pool
- A share in Top 10% / Top 20% / Top 30%
- enrichment lift = (Top bucket A share) / (full-sample A share)

3. Ranking discrimination
- A vs C `score_total` distribution gap
- A vs C axis-score distribution gaps:
  - strength axis
  - industry-leadership axis
  - chip-quality axis

4. Rule health
- hard-filter elimination ratio
- score layer continuity (bucket density)
- downgraded-feature exclusion impact on A coverage / A enrichment

## Explicitly forbidden metrics in this phase
- return / pnl / win-rate / drawdown / sharpe / PF
- any trading execution metric

