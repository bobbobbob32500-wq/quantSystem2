# strong_start Old-to-New Mapping (Implementation View)

## Mapping Principle
- Keep legacy `strong_start_strategy.py` intact.
- Route research-v4 logic into independent module/config/scripts.
- Move from threshold-chain design to four-layer design.

## Old Logic -> New Layer

| Old intent | New placement | Implementation action |
|---|---|---|
| Basic universe/risk exclusion | Filter layer | Keep as hard filters in `universe` section |
| Strongness precondition | Filter + scoring | Keep weak prefilter + stronger scoring contribution |
| Board/industry front-rank signal | Scoring + trigger assist | `f_ind_rank_pctchg` in scoring main axis; weak gate + quality assist allowed |
| Chip strict veto | Scoring / observation | `f_chip_winner_rate` as range scoring; `f_chip_stability_std10` kept as scoring-observation only |
| Day-of-start confirmation | Trigger layer | `f_k_pct_chg`, `f_k_body_to_atr`, volume confirmation separated from filters |
| Static platform/weak peak structure | Downgraded observation | Record only; not core decision path |

## High-risk Legacy Behaviors Avoided
- No direct overwrite of legacy strategy entrypoints.
- No dense hard-threshold chaining in early layer.
- No mixing trigger conditions into prefilter by default.

## Files Carrying This Mapping
- Strategy: `src/modules/strong_start_research_v4.py`
- Config: `config/strong_start_research_v4_config.yaml`
- Structure scan: `scripts/run_strong_start_research_v4_signal_scan.py`
- Structure validation: `scripts/validate_strong_start_research_v4_structure.py`

