# Buy Signal V1 structure-fit audit

## Conclusion summary
- V1 bias: Path B
- Priority fit: priority_tag=1 trigger_rate=35.71% vs priority_tag=0 trigger_rate=43.37%
- Primary blockers for priority_tag=1 & Path A captured in block_reason_audit.
- Ready for minimal buy-point iteration: YES

## Trigger structure decomposition
- A_core_all: n=210, trigger=90, rate=42.86%, pull=77, brk=6, rng=7
- B_priority_1: n=14, trigger=5, rate=35.71%, pull=5, brk=0, rng=0
- C_priority_0: n=196, trigger=85, rate=43.37%, pull=72, brk=6, rng=7
- D_path_A: n=17, trigger=5, rate=29.41%, pull=5, brk=0, rng=0
- E_path_B: n=193, trigger=85, rate=44.04%, pull=72, brk=6, rng=7

## Rule blocker audit (key groups)
- priority1_pathA blockers | pullback: pull_support_touch_any, pull_drawdown_ok_any, pull_reclaim_any
- priority1_pathA blockers | breakout: brk_break_any, brk_hold_any, brk_chg_ok_any
- priority1_pathA blockers | range: rng_break_any, rng_width_ok_any, rng_vol_any
- priority0_pathB blockers | pullback: pull_support_touch_any, pull_reclaim_any, pull_drawdown_ok_any
- priority0_pathB blockers | breakout: brk_break_any, brk_hold_any, brk_chg_ok_any
- priority0_pathB blockers | range: rng_break_any, rng_width_ok_any, rng_vol_any

## Path A vs Path B fit
- path=A triggered: n=5, mean_t2=0.0000, median_t2=-0.0194, win_t2=40.00%
- path=A not_triggered: n=12, mean_t2=0.0448, median_t2=0.0383, win_t2=58.33%
- path=B triggered: n=85, mean_t2=0.0100, median_t2=0.0039, win_t2=57.65%
- path=B not_triggered: n=108, mean_t2=0.0055, median_t2=0.0033, win_t2=52.78%

## Priority-tag fit judgement
- priority_tag samples are under-triggered relative to non-priority group.
- Current V1 behaves more like pullback-biased detector than strong-start acceleration detector.

## Candidate directions (no rule change in this round)
1. Relax/reshape breakout hold confirmation for Path A high-acceleration names.
2. Add path-aware trigger gate so Path A is not forced into pullback-dominant pattern.
3. Rework range break window length to avoid suppressing fast expansion names.