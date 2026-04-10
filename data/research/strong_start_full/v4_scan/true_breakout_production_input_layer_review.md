# Production Input Layer Rebuild (Dual Objective)

This round rebuilds input layer with quality+frequency constraints, selector structure unchanged.

## Headline
- F3 Tier-1 stays fixed: n=7, days=7, A_high=71.43%, C=28.57%, win_t2=85.71%
- outer PathA pool: n=10, days=10, A_high=20.00%, C=30.00%, win_t2=30.00%
- best union candidate: F3_plus_T2_S4_pri0_breadth
  - n=12, days=12, signal_day_ratio=10.43%, avg_days_per_signal=9.58
  - A_high=58.33%, C=16.67%, A_low=8.33%, Ahigh/C=3.50
  - win_t2=66.67%, mean_t2=4.90%
  - dual_objective_pass(all)=True

## Decision framing
- Keep F3 as Tier-1 high-purity pool.
- Tier-2 candidate recommendation: T2_S4_pri0_breadth
- Buy-point development remains paused in this round; this is input-layer decision only.