# Strong Start Sample Analysis

## Sample Counts

- A: 38
- B: 25
- C: 190

## Top Features (A vs C)

| Feature | Sep | Direction | Median A | Median C | Role | Suggested Min | Suggested Max |
| --- | ---: | --- | ---: | ---: | --- | ---: | ---: |
| candidate_condition_count | 0.698 | higher_better | 6.0000 | 5.0000 | score | 5.0000 | N/A |
| vol_ratio20 | 0.649 | higher_better | 2.4884 | 1.7728 | score | 1.7530 | N/A |
| winner_rate | 0.648 | higher_better | 0.9904 | 0.9426 | score | 0.9554 | N/A |
| rs60_xsec_q | 0.645 | higher_better | 0.8798 | 0.8109 | score | 0.8349 | N/A |
| ret60 | 0.637 | higher_better | 0.2624 | 0.1605 | score | 0.1779 | N/A |
| close_pos | 0.629 | higher_better | 0.8730 | 0.8111 | score | 0.8287 | N/A |
| vol_ratio60 | 0.623 | higher_better | 2.7483 | 2.2417 | score | 1.8797 | N/A |
| body_to_atr | 0.613 | higher_better | 1.1652 | 0.9518 | score | 0.7963 | N/A |
| rs20_xsec_q | 0.612 | higher_better | 0.9480 | 0.9201 | score | 0.9157 | N/A |
| pct_chg | 0.611 | higher_better | 6.6200 | 4.7950 | score | 4.8150 | N/A |
| stock_rank_pctchg_in_industry | 0.604 | higher_better | 0.9629 | 0.9477 | score | 0.9290 | N/A |
| upper_shadow_ratio | 0.602 | lower_better | 0.1270 | 0.1762 | score | N/A | 0.1713 |
| industry_ret5 | 0.602 | lower_better | -0.7245 | -0.4607 | score | N/A | 0.1651 |
| ret20 | 0.601 | higher_better | 0.1328 | 0.0928 | score | 0.0794 | N/A |
| chip_stability_std | 0.600 | higher_better | 0.0051 | 0.0035 | weak | N/A | N/A |

## Notes

- Event-level sample analysis only.
- All feature values are based on T-day visible information.
- Industry strength is aggregated from stock_daily + stock_basic.industry.