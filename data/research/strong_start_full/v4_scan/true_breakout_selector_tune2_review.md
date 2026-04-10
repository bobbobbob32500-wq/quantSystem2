# true_breakout_selector_tune2_review

Tune2 edits (exactly 3):
- rank_pct_max: 0.30 -> 0.10
- add hard filter: f_chip_winner_rate >= 0.80
- weights: strength 0.40 / industry 0.25 / chip 0.30 / platform 0.05

## Candidate purity
- baseline candidate_a_share: 0.2232
- tune2 candidate_a_share: 0.2708

## Top2/3/5 win_t2
- top2: baseline 0.5000 -> tune2 0.4788
- top3: baseline 0.4633 -> tune2 0.4605
- top5: baseline 0.4424 -> tune2 0.4310

## Top3 vs Top4~5 (win_t2 gap)
- baseline: 0.0523
- tune2: 0.0742

## Best group by win_t2 under tune2: top1 (0.5000)
## Note
- selector-only comparison; no trading execution optimization, no parameter search.