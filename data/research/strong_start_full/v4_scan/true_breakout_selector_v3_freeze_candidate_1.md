# true_breakout_selector_v3_freeze_candidate_1

## 1) Version Identity
- Name: `true_breakout_selector_v3_freeze_candidate_1`
- Positioning: selector main-structure candidate baseline
- Not included: entry timing, exit logic, execution rules, full trading backtest

## 2) Why freeze "main structure" now
- Path A and Path B internal ranking are both effective.
- `M1_quota_merge` is the best output mechanism among tested merge methods.
- Candidate pool A-share is above full-sample baseline in the near window:
  - baseline A-share: `35.39%`
  - `M1_quota_merge` A-share: `41.63%`
- Conclusion: structure has crossed the minimum viability bar; parameter layer is next.

## 3) Why this is not final strategy yet
- Current freeze is architecture-level only (what to score, how to merge), not parameter finalization.
- No buy/sell/execution chain is included.
- No full-history robustness backtest is included.

## 4) Why next stage is parameter phase (not entry phase)
- The unresolved uncertainty is parameter sensitivity inside an already valid structure.
- Entry research before selector parameter stabilization would mix responsibilities and create false attribution.

## 5) Frozen Structure
### A. Universe
- Main-board only.
- Minimum listing days.
- Minimum liquidity threshold.
- `ST/*ST` excluded.

### B. Path A: high-momentum frontline
- Target A subtype: `high_momentum_frontline_A`
- Core factors:
  - `f_strength_rs20_xsec_q`
  - `f_ind_peer_strong_count`
- Auxiliary factors:
  - `f_chip_winner_rate`
- Downgraded (not core ranking):
  - `f_strength_ret60`
  - `f_strength_vs_index20`
  - `f_trend_close_ma60_gap`
- Anti-heat resonance cap (frozen):
  - If trend core and industry rank are both extreme on T-day, apply score cap/penalty to avoid pseudo-strong C amplification.

### C. Path B: steady-structure
- Target A subtype:
  - `steady_structure_A`
  - `chip_support_A`
  - part of `mixed_A`
- Core factors:
  - `f_platform_compress_ratio`
  - `f_platform_range30`
  - `f_chip_winner_rate`
  - `f_chip_low_position120`
- Trend as floor/aux only:
  - `f_strength_rs20_xsec_q`
  - `f_trend_close_ma20_gap`
- Downgraded:
  - entry-like K/volume trigger features remain outside selector core.

### D. Output mechanism (frozen)
- Mechanism: `M1_quota_merge`
- Reason:
  - better A-share than S3/S4/S5 in tested near window
  - preserves both path expression (avoids Path B silence)
  - suppresses key pseudo-C modes better than naive merge
- Quota logic (structure-level):
  - daily total is capped
  - Path A and Path B each have bounded slots
  - neither path can consume all daily slots

## 6) Explicit non-goals in this freeze
- No entry timing.
- No exit design.
- No execution assumptions.
- No return optimization.
