# strong_start breakout-B risk spec

Version: `breakout_b_risk_spec_v1`

## 1) Single-name risk constraint
- Define fixed per-trade risk budget parameter:
  - `risk_per_trade_budget`
- Constraint purpose:
  - prevent oversized exposure before any performance validation.

## 2) Daily candidate cap
- Define fixed cap:
  - `max_new_entries_per_day`
- Selection under cap:
  - sort by `score_total` descending
  - tie-breaker: stronger trigger explain consistency.

## 3) Industry concentration cap
- Define fixed cap:
  - `max_entries_per_industry_per_day`
- Use current `industry` grouping from research outputs.

## 4) Candidate priority (minimal)
- Tier 1: `execution_state=ready` with strongest score bucket.
- Tier 2: remaining ready candidates.
- Tier 3: `risk` retained as watch-only, no entry.

## 5) Explicit exclusions
- No pullback channel.
- No portfolio optimization.
- No execution performance assumptions.

