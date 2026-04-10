# Stage2 Mainline Quality Tag Layer

## Rule
- Baseline selection remains `mainline_top1` (no replacement).
- `quality_tag = (score_industry_axis_single <= q55) AND (f_strength_rs20_xsec_q >= q30)`.
- q55(industry)=0.586940, q30(rs20)=0.827033

## Full-year quick check
- mainline_top1: n=223, A_high/C=0.3333, win_t2=50.22%, mean_t2=0.62%
- quality_tag=1: n=82, A_high/C=0.5667, win_t2=53.66%, mean_t2=1.15%
- quality_tag=0: n=141, A_high/C=0.2167, win_t2=48.23%, mean_t2=0.31%

## Decision
- Keep baseline mainline unchanged; use quality_tag as enhancement layer for next-stage gating.