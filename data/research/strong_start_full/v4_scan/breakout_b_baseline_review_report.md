# breakout-B baseline review report

## Window and scale
- window: 20260309 ~ 20260327 (15 days)
- signals/execution/entries/exits/abandon: 124/124/23/23/101

## Minimal metrics (single baseline only)
- total_trades: 23
- win_rate: 0.2174
- avg_trade_return: -0.0029
- median_trade_return: -0.0200
- profit_factor: 0.8079
- max_drawdown: -0.1912
- avg_holding_days: 1.70
- exit_distribution: {'structural_stop': 17, 'time_stop': 5, 'max_hold_or_momentum_decay': 1}

## Attribution
- loser_common: {'exit_reason_top': {'structural_stop': 17, 'max_hold_or_momentum_decay': 1}, 'score_total_median': 90.20866100941647, 'quality_pass_rate': 0.8333333333333334}
- winner_common: {'exit_reason_top': {'time_stop': 5}, 'score_total_median': 88.90171161825725, 'quality_pass_rate': 0.6}
- dominant issue side: exit_definition_dominant_issue
- structural_stop implication: stop-trigger concentration indicates fragile continuation after entry

## Top 3 suspicious points
- structural_stop exits dominate the distribution
- sample size is small and from a short contiguous regime
- entry logic is strict-ready only; risk/reject all excluded so entry diversity is low

## Next single action
- A: continue baseline review with one larger window (no parameter tuning).