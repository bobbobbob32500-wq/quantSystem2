# priority_tag C-pollution source audit

## Conclusion summary
- Main C source: Path A
- Stable pollution clues found: NO
- Ready for minimal tag-purification research: NO
- Ready for entry research: NOT_READY (C contamination inside priority_tag=1 is still high and cross-window separation is not stable enough.)

## A_high vs C difference location
### all
- priority_tag=1 & Path A n: 12
- A_high n: 5, C n: 5
- score_platform_axis_single: median_gap(H-C)=-0.0347
- score_total: median_gap(H-C)=-0.0055
- score_industry_axis_single: median_gap(H-C)=0.0030
### main
- priority_tag=1 & Path A n: 6
- A_high n: 3, C n: 2
- score_industry_axis_single: median_gap(H-C)=-0.0791
- score_platform_axis_single: median_gap(H-C)=0.0215
- score_total: median_gap(H-C)=0.0162
### confirm
- priority_tag=1 & Path A n: 6
- A_high n: 2, C n: 3
- score_platform_axis_single: median_gap(H-C)=-0.1104
- score_industry_axis_single: median_gap(H-C)=-0.0423
- score_total: median_gap(H-C)=-0.0242

## explain / reason audit
### all
- priority_reason | A_high top: in_v32_core_and_hit_v31_relaxed(100.00%)
- priority_reason | C top: in_v32_core_and_hit_v31_relaxed(100.00%)
- selector_explain | A_high top: schemeB:v32_core;path=A;priority_tag=1(100.00%)
- selector_explain | C top: schemeB:v32_core;path=A;priority_tag=1(100.00%)
### main
- priority_reason | A_high top: in_v32_core_and_hit_v31_relaxed(100.00%)
- priority_reason | C top: in_v32_core_and_hit_v31_relaxed(100.00%)
- selector_explain | A_high top: schemeB:v32_core;path=A;priority_tag=1(100.00%)
- selector_explain | C top: schemeB:v32_core;path=A;priority_tag=1(100.00%)
### confirm
- priority_reason | A_high top: in_v32_core_and_hit_v31_relaxed(100.00%)
- priority_reason | C top: in_v32_core_and_hit_v31_relaxed(100.00%)
- selector_explain | A_high top: schemeB:v32_core;path=A;priority_tag=1(100.00%)
- selector_explain | C top: schemeB:v32_core;path=A;priority_tag=1(100.00%)

## Ranking / heat-layer audit
- Main driver category: platform_industry
- Pollution pattern: structure_not_separated
- rank_global_after_merge median_gap(H-C): main=0.0, confirm=0.0

## Main-pool stability
- Result: MAIN_POOL_STABLE
- is_core_candidate is still determined by pass_v3_2_candidate; priority_tag remains a layering label only.

## Direct answers to 7 questions
1. Is C pollution mainly from Path A? YES
2. Is A_high vs C visibly separable inside Path A? NO
3. Main separation driver: platform_industry
4. C pollution is closer to: structure_not_separated
5. Stable pollution clues found? NO
6. Enough clues for minimal tag-purification research? NO
7. Ready for entry research (Scheme B)? NOT_READY (C contamination inside priority_tag=1 is still high and cross-window separation is not stable enough.)

## Next-step recommendation
- Ready for minimal tag-purification research: NO
- Ready for entry research (Scheme B): NOT_READY