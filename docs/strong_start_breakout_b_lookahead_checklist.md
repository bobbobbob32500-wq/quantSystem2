# strong_start breakout-B lookahead checklist

Version: `breakout_b_lookahead_checklist_v1`

## Minimal anti-lookahead checklist
1. T-day signal stage uses T-day-visible fields only.
2. Execution judgment uses only T+1 boundary-observable fields.
3. Exit stage uses only post-entry observable fields in holding timeline.
4. Never mix future labels (`MFE/MAE/entry_possible/fwd returns`) into any decision stage.
5. Never define entry after observing exit outcome.
6. Stage data isolation must be explicit (`signal -> execution -> entry -> exit`).
7. If stage data missing, mark rejection/incomplete explicitly; no silent fallback.
8. `backtest_trade_record` must remain decision/audit-only in this phase (no performance fields).

