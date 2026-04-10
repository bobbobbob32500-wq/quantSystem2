# Strong Start Sample Analysis

## Sample Counts

- A: 1487
- B: 1146
- C: 11936

## Top Features (A vs C)

| Feature | Sep | Direction | Median A | Median C | Role | Suggested Min | Suggested Max |
| --- | ---: | --- | ---: | ---: | --- | ---: | ---: |
| pct_chg | 0.649 | higher_better | 4.5551 | 2.6800 | score | 2.5067 | N/A |
| atr_ratio | 0.641 | higher_better | 0.0355 | 0.0286 | score | 0.0272 | N/A |
| rs20_xsec_q | 0.627 | higher_better | 0.8246 | 0.7348 | score | 0.6918 | N/A |
| candidate_condition_count | 0.621 | higher_better | 5.0000 | 4.0000 | score | 4.0000 | N/A |
| stock_rank_pctchg_in_industry | 0.621 | higher_better | 0.9444 | 0.8750 | score | 0.8303 | N/A |
| chip_stability_std | 0.621 | higher_better | 0.0038 | 0.0025 | score | 0.0021 | N/A |
| ret20 | 0.617 | higher_better | 0.0965 | 0.0635 | score | 0.0496 | N/A |
| rs60_xsec_q | 0.609 | higher_better | 0.7670 | 0.6430 | score | 0.5297 | N/A |
| platform_range_20 | 0.609 | higher_better | 0.1339 | 0.1102 | score | 0.0968 | N/A |
| platform_range_best | 0.609 | higher_better | 0.1339 | 0.1102 | score | 0.0968 | N/A |
| platform_range_30 | 0.607 | higher_better | 0.1735 | 0.1438 | score | 0.1269 | N/A |
| ret60 | 0.606 | higher_better | 0.1548 | 0.0894 | score | 0.0462 | N/A |
| winner_rate | 0.605 | higher_better | 0.9264 | 0.8516 | score | 0.7727 | N/A |
| amount | 0.589 | higher_better | 430470.3660 | 313112.9355 | weak | N/A | N/A |
| stock_rank_amount_in_industry | 0.587 | higher_better | 0.7917 | 0.7143 | weak | N/A | N/A |

## Notes

- Event-level sample analysis only.
- All feature values are based on T-day visible information.
- Industry strength is aggregated from stock_daily + stock_basic.industry.