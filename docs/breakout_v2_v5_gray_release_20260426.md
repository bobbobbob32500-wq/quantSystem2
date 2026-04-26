# Breakout V2+V5 Gray Release Plan

## Scope

This release promotes the local breakout strategy mainline to:

- V2 entry quality guard enabled.
- V3 market-ret5 weak-regime guard retained but disabled by default.
- V5 A/B grade-aware trailing exit enabled.

The goal is to keep the V2 sample size while improving exit quality.

## Current Mainline

Config path: `stock_selection.breakout`

```yaml
params_preset: win_rate_priority
high_score_weak_confirm_guard:
  enabled: true
  score_min: 80.0
  volume_min: 1.35
market_ret5_median_guard:
  enabled: false
  stop: -0.01
exit_guard:
  max_hold_days: 3
  trailing_enabled: true
  trail_arm_pct: 0.04
  trailing_stop_pct: 0.025
  fixed_stop_loss_pct: -0.045
  use_weakness_rules: false
  grade_overrides:
    A:
      max_hold_days: 4
      trail_arm_pct: 0.045
      trailing_stop_pct: 0.025
      fixed_stop_loss_pct: -0.045
      use_weakness_rules: false
    B:
      max_hold_days: 3
      trail_arm_pct: 0.04
      trailing_stop_pct: 0.025
      fixed_stop_loss_pct: -0.045
      use_weakness_rules: false
```

## Validation Summary

Source reports:

- `reports/strategy_optimization/breakout_guard_full_compare_latest.md`
- `reports/strategy_optimization/breakout_market_guard_full_compare_latest.md`
- `reports/strategy_optimization/breakout_v5_exit_diagnosis_latest.md`

Main comparison:

| Version | Trades | Win | Mean | PF | Total | MaxDD |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| V1 baseline T+1 | 108 | 64.81% | 1.27% | 2.61 | 72.02% | -8.01% |
| V2 T+1 | 103 | 65.05% | 1.33% | 2.77 | 79.40% | -8.01% |
| V3 T+1 | 82 | 67.07% | 1.43% | 2.86 | 82.73% | -4.24% |
| V2 + unified T3 trailing | 103 | 69.90% | 1.92% | 3.40 | 159.21% | -7.16% |
| V2 + A/B grade exit | 103 | 67.96% | 2.00% | 3.48 | 167.76% | -7.17% |

Stability for A/B grade exit:

| Split | Trades | Win | Mean | PF | Total | MaxDD |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Train | 79 | 67.09% | 1.95% | 3.33 | 98.22% | -7.17% |
| OOS | 24 | 70.83% | 2.17% | 4.10 | 35.08% | -3.87% |

## Runtime Chain

The release adds/uses the following runtime fields:

- `BreakoutStrategy.resolve_exit_plan(signal_grade)`
- `BreakoutStrategy.export_exit_plan()`
- `candidate_pool.json[].exit_plan`
- Intraday confirmation display resolves exit plan by `BreakoutSignal.signal_grade`.

Important note:

- Watchlist items are pre-confirmation and do not have `signal_grade`.
- The candidate cache stores both A/B exit plans.
- Once confirmation produces `signal_grade`, downstream execution should select `exit_plan.by_grade[signal_grade]`.

## Rollback Switches

Fast rollback to V2 T+1-style behavior:

```yaml
stock_selection:
  breakout:
    high_score_weak_confirm_guard:
      enabled: true
    market_ret5_median_guard:
      enabled: false
    exit_guard:
      max_hold_days: 1
      trailing_enabled: false
      fixed_stop_loss_pct: null
      use_weakness_rules: true
      grade_overrides: {}
```

Defensive weak-market mode:

```yaml
stock_selection:
  breakout:
    market_ret5_median_guard:
      enabled: true
      stop: -0.01
```

## Pre-Deploy Checklist

- Run unit/integration tests:
  - `.\\.venv\\Scripts\\python.exe -m pytest tests\\test_breakout_system_integration.py tests\\test_strong_start_strategy.py -q`
- Refresh candidate pool:
  - build strategy from config
  - run latest breakout watchlist
  - sync `exit_plan` to `data/cache/candidate_pool.json`
- Verify candidate cache contains:
  - `exit_plan.base`
  - `exit_plan.by_grade.A`
  - `exit_plan.by_grade.B`
- Verify intraday confirmation path passes or records `signal_grade`.

## Changed Files

- `src/modules/breakout_strategy.py`
- `src/modules/breakout_selector_menu.py`
- `src/modules/breakout_intraday_monitor.py`
- `src/services/dashboard_task_runner.py`
- `src/config/config.yaml`
- `tests/test_breakout_system_integration.py`
- `tools/diagnose_breakout_exit_v5.py`
