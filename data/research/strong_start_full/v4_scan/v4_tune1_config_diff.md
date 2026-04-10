# v4_tune1_config_diff

## Scope
- Baseline: `config/strong_start_research_v4_config.yaml`
- Tune1: `config/strong_start_research_v4_config_tune1.yaml`
- Change policy: small, directional, config-only adjustments (no framework rewrite).

## Changed Items

### 1) `hard_filters.industry_rank_pctchg_weak_gate.thresholds`
- loose: `0.75 -> 0.72`
- neutral: `0.80 -> 0.77`
- strict: `0.85 -> 0.82`
- Reason: reduce filter-layer over-kill on near-front strong candidates.
- Expected funnel impact: increase `after_filter` counts across all profiles.

### 2) `trigger.groups.quality.rules[k_body_to_atr].thresholds`
- loose: `0.72 -> 0.64`
- neutral: `0.85 -> 0.75`
- strict: `1.00 -> 0.88`
- Reason: this was the #1 trigger fail source; slight relaxation to reduce quality over-tightness.
- Expected funnel impact: increase `trigger_pass` and `signal_ready`, especially neutral/strict.

### 3) `trigger.groups.breakout.rules[breakout_volume_ratio20].thresholds.strict`
- strict: `1.80 -> 1.70`
- Reason: strict profile breakout confirmation was excessively tight.
- Expected funnel impact: strict profile should recover some trigger passes without loosening loose/neutral.

## Intentionally Unchanged
- Four-layer structure (filter/scoring/trigger/downgraded).
- `f_ind_rank_pctchg` dual-role wiring (weak filter + scoring + trigger assist).
- scoring axis weights and min group/rule trigger framework.
- any sample definition, label, or data window.

