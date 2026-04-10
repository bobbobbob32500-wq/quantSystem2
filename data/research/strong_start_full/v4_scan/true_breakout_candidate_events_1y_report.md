# true_breakout_candidate_events_1y_report

- time range: 20250408 ~ 20260408
- universe: main-board + list_days>=180 + amount>=1e8 + non-ST
- candidate logic: 4-class loose scan; in-pool when >=2 classes and close>MA20
- dedup: same-stock cooldown 12 bars, with secondary restart release

## pool profile
- candidate events: 18491
- covered stocks: 2730
- daily mean events: 82.92
- daily median events: 73.00
- daily p90 events: 138.60

## repeat risk
- stocks with >1 event: 2472
- event interval median days: 21.0

## judgement
- candidate pool is intentionally wide for next-step labeling and true/false startup split.
- next stage can proceed: true/false startup labeling.