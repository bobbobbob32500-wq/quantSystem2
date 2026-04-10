# true_breakout_selector_v1_acceptance_checklist

Baseline: `true_breakout_selector_v1_freeze1`

| # | Check | Status | Evidence | Note |
|---|---|---|---|---|
| 1 | Research objective converged to selector-only | PASS | `docs/true_breakout_research_objective_reset.md` | No trading execution objective in current phase |
| 2 | A/C event sample scope fixed | PASS | `scripts/run_true_breakout_selector_validation.py` + `.../true_breakout_selector_validation_set.parquet` | A/C only, no B/N |
| 3 | Selector vs entry feature boundary fixed | PASS | `docs/selector_vs_entry_feature_boundary.csv` | Entry-like features removed from selector core |
| 4 | Selector historical validation completed | PASS | `.../true_breakout_selector_validation_review.md` | Small-range validation completed |
| 5 | Candidate pool A enrichment > full-sample A share | PASS | `.../true_breakout_selector_coverage_summary.csv` | A share lift is positive |
| 6 | Top bucket enrichment monotonic | PASS | `.../true_breakout_selector_ranking_summary.csv` | Top10 > Top20 > Top30 (A share) |
| 7 | Rule health acceptable | PASS | `.../true_breakout_selector_rule_health_summary.csv` | Balanced pool, continuous scoring |
| 8 | tune1 tested but not adopted | PASS | `.../true_breakout_selector_tune1_compare.csv` + `.../true_breakout_selector_tune1_review.md` | Baseline retained |
| 9 | Not misused as trading strategy | PASS | `docs/true_breakout_selector_v1_output_contract.md` | Trading/performance fields explicitly forbidden |
| 10 | No buy/sell/performance conclusions in frozen baseline | PASS | `docs/true_breakout_selector_v1_frozen_spec.md` | Selector-only frozen boundary |

Freeze blocker:
- None.

