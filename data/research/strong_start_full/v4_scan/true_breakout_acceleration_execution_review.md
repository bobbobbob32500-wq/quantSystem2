# True Breakout Acceleration Execution (A/B/C)

## Stage A - Mainline fixed
- mainline_current fixed to: C2A + ECH2_S2
- full_year A_high_recall_rate=6.51%, A_high/C=0.2993, win_t2=49.87%

## Stage B - Quality gate + production constraints
- selected gate scenario: G1_industry_cap
- full_year A_high_recall_rate=6.35%, A_high/C=0.3077, A_low+C=43.50%, avg_days_per_signal=1.00

## Stage C - Buy signal baseline vs prod_v2
- all win_t2: baseline=47.50% -> prod_v2=47.50% (delta=+0.00%)
- all trigger_rate: baseline=17.94% -> prod_v2=17.94%

## Decision gates
- Keep recall-first order: yes
- Frequency floor target (>= one signal every 2-3 trading days): tracked in stageB constraints
- Buypoint stage should start only after two consecutive selector rounds pass quality+frequency constraints