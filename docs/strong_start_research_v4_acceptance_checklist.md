# strong_start_research_v4_acceptance_checklist

Baseline: `strong_start_research_v4_freeze1`  
Decision: freeze acceptance

| # | Item | Status | Evidence | Notes |
|---|---|---|---|---|
| 1 | Independent strategy module exists | PASS | `src/modules/strong_start_research_v4.py` | Independent from legacy |
| 2 | Independent config exists | PASS | `config/strong_start_research_v4_config_frozen.yaml` | Frozen config created |
| 3 | Legacy `strong_start` not overwritten | PASS | `src/modules/strong_start_strategy.py` and git diff check | Coexistence preserved |
| 4 | Four-layer structure implemented | PASS | `src/modules/strong_start_research_v4.py` | filter/scoring/trigger/downgraded |
| 5 | Explainability output complete | PASS | required fields present in scan parquet | `explain_json` + layer details |
| 6 | Structure scan script runnable | PASS | `scripts/run_strong_start_research_v4_signal_scan.py` + `v4_scan` outputs | No backtest metrics |
| 7 | Structure validator runnable | PASS | `data/research/strong_start_full/v4_scan/strong_start_research_v4_structure_validation_frozen.log` | Passed with frozen config |
| 8 | Minimal tests pass | PASS | `data/research/strong_start_full/v4_scan/strong_start_research_v4_pytest_frozen.log` | 5 passed |
| 9 | Forward-looking fields blocked | PASS | validator + tests (`future field guard`) | enforced in strategy |
| 10 | Multiday structural review completed | PASS | `v4_scan_multiday_*.parquet`, `v4_structure_scan_review_report.md` | 30-day window |
| 11 | Tune1 adjustment + re-review completed | PASS | `v4_tune1_*` compare files, `v4_tune1_structure_adjustment_report.md` | same window compared |
| 12 | No performance-claim boundary explicit | PASS | `docs/strong_start_research_v4_output_contract.md`, release notes | structure-only boundary locked |

## Blocking Items
- None.

## Freeze Gate Result
- `ACCEPTED` as research freeze baseline `strong_start_research_v4_freeze1`.
