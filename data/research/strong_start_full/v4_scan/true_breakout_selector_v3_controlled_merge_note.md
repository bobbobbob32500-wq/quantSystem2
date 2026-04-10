# true_breakout_selector_v3_controlled_merge_note

Selected controlled merge scheme: Scheme C (path-internal front-segment union).
- Path A keep: rank_a <= 0.15
- Path B keep: rank_b <= 0.15
- Merge: selected = A_front OR B_front
Reason: simple, interpretable, reduces naive full-union C amplification without introducing complex model.