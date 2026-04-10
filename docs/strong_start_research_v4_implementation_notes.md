# strong_start_research_v4 Implementation Notes

## Scope
- This implementation is for research-structure execution only.
- It does **not** include backtest, PnL, optimization, or live trading output.
- Legacy `strong_start` logic is preserved and not overwritten.

## New Components
- `src/modules/strong_start_research_v4.py`
  - Research strategy runner with four explicit layers:
    1. base filters
    2. continuous scoring
    3. trigger confirmation
    4. downgraded observation
  - Produces structured explainability payload (`explain_json`).
- `config/strong_start_research_v4_config.yaml`
  - Independent config with `loose/neutral/strict` profiles.
  - Layer-separated feature placement and thresholds.
  - Includes sanity constraints:
    - `f_chip_stability_std10` is not hard filter.
    - `f_k_pct_chg` is trigger feature.
    - `f_ind_rank_pctchg` is scoring main feature (and allowed cross-layer assist).
- `scripts/run_strong_start_research_v4_signal_scan.py`
  - Structure-only scan runner over feature snapshot data.
  - Outputs per-layer counts and diagnostics, no return metrics.
- `scripts/validate_strong_start_research_v4_structure.py`
  - Structural validator for layer boundaries, config sanity, output schema, future-field guard.
- `tests/test_strong_start_research_v4_structure.py`
  - Minimal unit checks for isolation, layering, required outputs, config errors, and forward-field block.

## Explainable Output Contract
Each event row includes:
- filter decision and reject reasons
- axis-level scores and item contributions
- trigger group pass/fail details
- downgraded-feature observations
- final tags:
  - `is_candidate_after_filters`
  - `score_total`
  - `trigger_status`
  - `signal_ready`
  - `explain_json`

## Structural Validation Commands
Run from repository root:

```powershell
python scripts/validate_strong_start_research_v4_structure.py
python -m pytest tests/test_strong_start_research_v4_structure.py -q
python scripts/run_strong_start_research_v4_signal_scan.py --start-date 20260327 --end-date 20260327 --profile neutral
```

## Non-goals in This Phase
- No backtest engines are called.
- No performance metrics (win rate/return/drawdown) are computed.
- No parameter search is performed.
- No live candidate publishing is performed.

