# strong_start_research_v4_release_notes

## Release Identity
- Release name: `strong_start_research_v4_freeze1`
- Base strategy: `strong_start_research_v4`
- Default profile baseline: `neutral` (tune1 absorbed)
- Release date: `2026-04-08`

## What Is Included
- Independent strategy module and frozen config
- Four-layer structure with explainability outputs
- Multiday structural scan + tune1 before/after compare package
- Validation scripts and minimal structural tests
- Acceptance checklist and output contract

## Tune1 Changes Absorbed into Freeze
1. `industry_rank` weak hard gate eased
2. `quality:k_body_to_atr` trigger threshold eased
3. strict `breakout_volume_ratio20` threshold eased

## Known Boundaries (Accepted as-is in freeze1)
- strict remains relatively tighter than neutral
- `quality:k_body_to_atr` still contributes most trigger fails
- `f_ind_rank_pctchg` trigger assist may be weakened in next version

## Completed vs Not Completed
Completed:
- sample mining and event-level research chain
- feature snapshot construction
- A/C difference analysis
- parameter reverse-engineering
- strategy structure reconstruction
- implementation, structure validation, tune1 micro-adjustment, and re-review

Not completed (intentionally out of scope):
- any trading backtest
- any return/win-rate/drawdown study
- any parameter search / auto tuning
- any live-trading validation

## Post-Freeze Governance Boundary
- No more edits to freeze1 thresholds/weights/layer assignments.
- Any further improvement must create a **new version**:
  - for example: `strong_start_research_v4_freeze2` or `strong_start_research_v5`
  - with explicit diff, re-validation, and new acceptance checklist.

## Correct Next Phase (If Continue)
- Enter: “research-to-trading validation design”
- Do not jump directly to profitability claim.

