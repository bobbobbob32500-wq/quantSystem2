# v4 Structure Scan Review (Multiday, No Backtest)

- Window: `20260206` to `20260327`
- Trading days scanned: `30`
- Scope: structure-only diagnostics (filters/scoring/trigger/explainability)

## Profile Gradient Snapshot
- loose: universe=1529, after_filter=617 (40.35%), trigger_pass=502 (32.83%), ready=499 (32.64%)
- neutral: universe=1529, after_filter=498 (32.57%), trigger_pass=371 (24.26%), ready=370 (24.20%)
- strict: universe=1529, after_filter=355 (23.22%), trigger_pass=223 (14.58%), ready=223 (14.58%)

## Top Filter Reasons (per profile)
- loose:
  - hard:trend_close_ma20_gap:fail: 697
  - hard:strength_rs20_xsec_q:fail: 588
  - hard:industry_rank_pctchg_weak_gate:fail: 338
- neutral:
  - hard:trend_close_ma20_gap:fail: 811
  - hard:strength_rs20_xsec_q:fail: 686
  - hard:industry_rank_pctchg_weak_gate:fail: 436
  - universe:price_too_high: 11
- strict:
  - hard:trend_close_ma20_gap:fail: 920
  - hard:strength_rs20_xsec_q:fail: 792
  - hard:industry_rank_pctchg_weak_gate:fail: 527
  - universe:amount_ma20_too_low: 217
  - universe:price_too_low: 112

## Top Trigger Fails (per profile)
- loose:
  - quality:k_body_to_atr: 592
  - breakout:breakout_volume_ratio20: 242
  - quality:k_upper_shadow_ratio: 202
  - momentum:k_pct_chg: 108
  - momentum:up_down_vol_ratio20: 93
- neutral:
  - quality:k_body_to_atr: 477
  - breakout:breakout_volume_ratio20: 233
  - quality:k_upper_shadow_ratio: 194
  - momentum:up_down_vol_ratio20: 136
  - quality:industry_rank_trigger_assist: 87
- strict:
  - quality:k_body_to_atr: 344
  - breakout:breakout_volume_ratio20: 199
  - momentum:up_down_vol_ratio20: 177
  - quality:k_upper_shadow_ratio: 166
  - quality:industry_rank_trigger_assist: 96

## Score Distribution (median)
- loose:
  - score_total: median=0.0000, p75=79.3699, p90=93.0089
  - score_axis_strength: median=0.0000, p75=77.9274, p90=100.0000
  - score_axis_industry: median=0.0000, p75=60.0000, p90=100.0000
  - score_axis_chip: median=0.0000, p75=95.1058, p90=100.0000
- neutral:
  - score_total: median=0.0000, p75=75.7746, p90=90.2177
  - score_axis_strength: median=0.0000, p75=75.0000, p90=100.0000
  - score_axis_industry: median=0.0000, p75=60.0000, p90=100.0000
  - score_axis_chip: median=0.0000, p75=87.0364, p90=96.6216
- strict:
  - score_total: median=0.0000, p75=0.0000, p90=86.0378
  - score_axis_strength: median=0.0000, p75=0.0000, p90=100.0000
  - score_axis_industry: median=0.0000, p75=0.0000, p90=90.6171
  - score_axis_chip: median=0.0000, p75=0.0000, p90=78.3162

## Explainability Sample Review
- filter_reject_but_strong_looking: 8 samples
- high_score_trigger_fail: 8 samples
- score_threshold_gray_zone: 8 samples
- signal_ready_true: 8 samples

## Notes
- This report does not include any return, win-rate, or drawdown metrics.
- Purpose is only structural sanity and interpretability review.