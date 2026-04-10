# true_breakout_selector_ahigh_refine_draft

## New selector objective
- maximize A_high share (not generic A share)
- suppress selected_C
- demote selected_G by default

## Keep
- dual-path structure unchanged (this draft only refines objective and layer priority)
- trend-quality + platform-compress as core discriminators

## Demote / cap
- industry aggregate heat score: keep as auxiliary with cap
- winner-rate standalone boost: demote from core
- unstable platform aggregate score: decompose/repair before core use

## selected_C firewall (lightweight)
- heat-resonance cap
- platform integrity guard
- mixed-C dampener to observe pool

## selected_G handling
- default observe pool, not core candidate

## Next validation focus
- evaluate A_high share uplift
- track selected_C suppression
- ensure selected_G stays mostly outside core output