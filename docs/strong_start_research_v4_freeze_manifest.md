# strong_start_research_v4_freeze_manifest

## Freeze Identity
- Freeze baseline name: `strong_start_research_v4_freeze1`
- Strategy name: `strong_start_research_v4`
- Default research baseline profile: `neutral` (from tune1-absorbed config)
- Freeze date: `2026-04-08`

## Freeze Package Scope
- This freeze package is a **research-structure baseline**.
- It is valid for structural scan, explainability, and configuration governance.
- It is **not** a performance-validated trading strategy release.

## Core Frozen Files
1. Strategy module  
`src/modules/strong_start_research_v4.py`
2. Frozen config  
`config/strong_start_research_v4_config_frozen.yaml`
3. Structure scan runner  
`scripts/run_strong_start_research_v4_signal_scan.py`
4. Multiday structure review runner  
`scripts/review_strong_start_research_v4_multiday.py`
5. Structure validator  
`scripts/validate_strong_start_research_v4_structure.py`
6. Minimal structure tests  
`tests/test_strong_start_research_v4_structure.py`

## Frozen Documentation Set
1. Frozen strategy spec  
`docs/strong_start_research_v4_frozen_spec.md`
2. Output contract  
`docs/strong_start_research_v4_output_contract.md`
3. Acceptance checklist  
`docs/strong_start_research_v4_acceptance_checklist.md`
4. Release notes / boundary  
`docs/strong_start_research_v4_release_notes.md`
5. Tune1 config diff note  
`data/research/strong_start_full/v4_scan/v4_tune1_config_diff.md`

## Key Structural Review Evidence (Frozen Reference)
- Baseline multiday scan (pre-tune compare baseline):
  - `data/research/strong_start_full/v4_scan/v4_scan_multiday_loose.parquet`
  - `data/research/strong_start_full/v4_scan/v4_scan_multiday_neutral.parquet`
  - `data/research/strong_start_full/v4_scan/v4_scan_multiday_strict.parquet`
- Tune1 multiday scan:
  - `data/research/strong_start_full/v4_scan/v4_tune1_scan_multiday_loose.parquet`
  - `data/research/strong_start_full/v4_scan/v4_tune1_scan_multiday_neutral.parquet`
  - `data/research/strong_start_full/v4_scan/v4_tune1_scan_multiday_strict.parquet`
- Compare outputs:
  - `data/research/strong_start_full/v4_scan/v4_tune1_funnel_compare.csv`
  - `data/research/strong_start_full/v4_scan/v4_tune1_filter_reason_compare.csv`
  - `data/research/strong_start_full/v4_scan/v4_tune1_trigger_fail_compare.csv`
  - `data/research/strong_start_full/v4_scan/v4_tune1_score_distribution_compare.csv`
  - `data/research/strong_start_full/v4_scan/v4_tune1_explain_diff_review.csv`
  - `data/research/strong_start_full/v4_scan/v4_tune1_structure_adjustment_report.md`

## Governance Rule After Freeze
- No edits to `strong_start_research_v4_config_frozen.yaml` thresholds/weights/layer mapping.
- Any further structural change must create a **new version** (for example `freeze2` or `v5`), with explicit diff and re-validation.

