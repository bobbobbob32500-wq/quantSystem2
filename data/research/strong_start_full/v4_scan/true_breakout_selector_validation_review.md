# true_breakout_selector validation review

## Frozen validation scope
- object: true_breakout_selector_v1_draft
- sample: A/C event-level only
- excluded: B/N, trading/execution fields, any performance metric

## Coverage & purity
- A total / C total: 1487 / 11541
- A hard-filter pass rate: 0.6147
- C hard-filter pass rate: 0.3932
- candidate A/C: 312/1086
- candidate A share vs full A share: 0.2232 vs 0.1141

## Top-bucket enrichment
- Top10 A share: 0.2443 (lift x2.141)
- Top20 A share: 0.2296 (lift x2.012)
- Top30 A share: 0.2232 (lift x1.955)
- monotonic A enrichment (Top10>=Top20>=Top30): True

## Axis contribution
- strongest axis: score_strength_axis
- weakest axis: score_platform_axis
- candidate pool health: balanced

## Rule health
- hard filter elimination rate: 0.5815
- score continuity: yes
- score replacing filter risk: moderate
- platform axis utility: meaningful
- axis dominance risk: balanced

## Minimal ablation readout
- baseline: candidate_A=0.2232, top20_A=0.2296, candidate_lift=0.1090, top20_lift=0.1155
- ablate_industry_axis: candidate_A=0.2153, top20_A=0.2383, candidate_lift=0.1012, top20_lift=0.1242
- ablate_chip_axis: candidate_A=0.2110, top20_A=0.2176, candidate_lift=0.0969, top20_lift=0.1035
- ablate_platform_axis: candidate_A=0.2190, top20_A=0.2234, candidate_lift=0.1048, top20_lift=0.1093

## Direct answers
1) A enrichment improved: yes
2) Improvement source: score sorting first, hard filter second
3) Most valuable axis: score_strength_axis
4) Weakest axis: score_platform_axis
5) Pool state: balanced
6) Ready for selector micro-tuning: yes