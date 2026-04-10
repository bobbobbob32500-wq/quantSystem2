# true_breakout research objective reset

Version: `objective_reset_v1`

## 1) What is a true-breakout stock (selector definition)
At event-day level, a true breakout event is a breakout that:
- comes from a valid pre-breakout structure (trend + platform + participation)
- is supported by stronger discriminative features vs false-breakout group
- remains statistically closer to A-class event profile than C-class profile

## 2) What is a false-breakout stock (selector definition)
At event-day level, a false breakout event is one that:
- shows breakout-like price action but matches C-class feature profile
- lacks stable support in key selector axes (strength, industry leadership, chip quality)
- is structurally noisy or over-dependent on trigger-only signals

## 3) Research object
Definitive object:
- **Event-day (`ts_code`, `trade_date`)**, not stock-level static labels

## 4) Questions this phase must answer
- Which events are most likely true-breakout candidates?
- Which pre-breakout structural features are robust for selection?
- Which features should be hard filters vs scoring inputs in selector?

## 5) Questions explicitly out of scope now
- exact entry timing
- execution assumptions
- exit/stop/holding optimization
- trading system PnL optimization

