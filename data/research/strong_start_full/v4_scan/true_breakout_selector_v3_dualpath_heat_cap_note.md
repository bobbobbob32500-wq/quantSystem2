# true_breakout_selector_v3_dualpath_heat_cap_note

Path A anti-heat resonance cap (T-day visible only):
- Inputs: trend_core_rank = rank(f_strength_rs20_xsec_q), industry_rank = rank(f_ind_peer_strong_count).
- Trigger: trend_core_rank >= 0.90 AND industry_rank >= 0.90.
- Action: score_a := min(score_a, 0.85) - 0.08.
- Intent: block trend×industry co-resonance from over-promoting `industry_heat_C` / `trend_chase_C`.
- Scope: Path A only; no change to Path B.