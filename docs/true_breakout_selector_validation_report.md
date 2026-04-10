# true_breakout_selector validation design report

Version: `selector_validation_report_v1`

## Summary
This phase validates only whether `true_breakout_selector_v1_draft` can stably select events that look more like true breakouts (A) than false breakouts (C), without any trading-performance interpretation.

## What we validate
- selector coverage quality
- selector ranking enrichment quality
- axis usefulness and redundancy
- rule health (tight/loose balance)

## What we do NOT validate
- entry timing
- exit logic
- execution assumptions
- backtest returns

## Direct answers to 6 validation questions
1. Most important target  
- maximize **A enrichment under controllable C inclusion**, not maximize candidate count.

2. Bigger risk  
- currently more dangerous to include too many C (purity collapse) than to miss a small part of A.

3. First metric priority  
- start with **coverage + purity**, then confirm **ranking enrichment**.

4. First axis to verify  
- **industry leadership axis** first (historically strongest selector discriminator in this project context).

5. Platform/structure auxiliary axis  
- yes, should be validated as weak auxiliary first, not as a main driver.

6. Continue/no-continue criterion  
- continue if: A coverage acceptable, candidate A share > full-sample A share, and top buckets show monotonic A enrichment.

## Next phase gate
If the above selector-validity conditions are met, move to:
- `真实突破选股策略小范围历史验证` (selector-only, still no trading branch)

