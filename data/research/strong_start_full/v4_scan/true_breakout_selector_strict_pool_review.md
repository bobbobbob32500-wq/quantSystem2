# Strict Pool Review

Focus: identify the selector sub-pool that best matches true strong-start targets before any further intraday work.

## Takeaway
- `priority_tag=1 & path_source=A` is the closest current proxy for a high-purity strong-start pool.
- It materially improves `A_high` concentration and fixed-horizon returns versus the full core pool.
- It is still not clean enough to be called a final pool, but it is the right place to keep optimizing.

## Why this matters
- If the stock pool is still mixed, intraday buy-point tuning cannot rescue the strategy shape.
- The next meaningful selector iteration should focus on this strict sub-pool rather than the whole core pool.

- CSV: `true_breakout_selector_strict_pool_review.csv`
- JSON: `true_breakout_selector_strict_pool_summary.json`