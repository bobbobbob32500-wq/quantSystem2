# Tagged Buy Signal Prod V1 Review

## Routing
- `quality_tag=1`: keep baseline v1.1 detection behavior.
- `quality_tag=0`: apply conservative gate (rank/overheat/confirmation safety).

## Full-year quick check
- all win_t2: baseline=47.50%, tagged_prod=51.52%
- quality_tag=1 win_t2: baseline=66.67%, tagged_prod=66.67%
- quality_tag=0 win_t2: baseline=39.29%, tagged_prod=42.86%

## Trigger rate
- all: baseline=17.94%, tagged_prod=14.80%
- quality_tag=1: baseline=14.63%, tagged_prod=14.63%
- quality_tag=0: baseline=19.86%, tagged_prod=14.89%