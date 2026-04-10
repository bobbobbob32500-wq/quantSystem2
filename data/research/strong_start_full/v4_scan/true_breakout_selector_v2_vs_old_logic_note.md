# true_breakout_selector_v2_vs_old_logic_note

- old tendency: mixed in trigger-like K-line signals too early
- v2 change: strict separation of selector factors vs entry-like research features
- old tendency: weaker handling of redundancy
- v2 change: explicit representative-vs-redundant pruning via correlation audit
- old tendency: broad factor inclusion without monthly sign stability checks
- v2 change: stability gate (monthly direction consistency) before entering hard/scoring layers