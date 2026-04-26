# Wide Breakout V2/V5 Final Version

Finalized: 2026-04-26

Final profile: V2 high-score weak-confirm guard + V5 A/B trailing exit (`A=4.5%/T4`, `B=4.0%/T3`).

## Scope

Wide breakout is treated as the same strategy family as standard breakout:

- standard breakout: stricter selection, normal strict entry
- wide breakout: looser selection, stricter entry

Therefore the upgrade follows the same path as standard breakout:

1. keep the original wide entry preset `wide_pool_strict_entry_v2`
2. add V2 high-score weak-confirm protection
3. add V5 trailing exit / fixed-stop configuration
4. keep market-ret5 median guard as an off-by-default defensive switch

## Baseline Evidence

The 126-trading-day same-window report shows that wide breakout is already strong. The older report had 125 trades; a fresh export on the current database produced 205 trades, still with a strong positive profile.

Source:

`data/reports/breakout_vs_wide_breakout_20250922_20260403_20260415_131009.json`

| Horizon | Trades | Win | Mean | PF |
| --- | ---: | ---: | ---: | ---: |
| T+1 | 125 | 67.20% | 1.83% | 3.44 |
| T+2 | 125 | 69.60% | 2.38% | 3.56 |
| T+3 | 125 | 63.20% | 2.86% | 3.45 |
| T+4 | 125 | 61.60% | 2.93% | 3.06 |
| T+5 | 125 | 64.80% | 3.35% | 3.20 |

Fresh current-database export:

Source:

`data/reports/wide_breakout_backtest_trades_20260426_214900.csv`

| Horizon | Trades | Win | Mean | PF |
| --- | ---: | ---: | ---: | ---: |
| T+1 | 205 | 62.93% | 1.23% | 2.29 |
| T+2 | 205 | 66.34% | 1.60% | 2.35 |
| T+3 | 205 | 60.49% | 2.09% | 2.48 |

The short recent window `20260213` to `20260403` is a stress slice, not the main baseline. It is useful for risk diagnostics, but it should not override the mainline parameters by itself.

V2 entry guard:

- on the fresh 126-day sample, the high-score weak-confirm rule filtered out 10 of 205 trades
- sample loss: 4.88%
- fixed-horizon metrics improved after V2 filtering:

| Horizon | Raw Win | Raw Mean | Raw PF | V2 Win | V2 Mean | V2 PF |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| T+1 | 62.93% | 1.23% | 2.29 | 63.59% | 1.28% | 2.38 |
| T+3 | 60.49% | 2.09% | 2.48 | 62.05% | 2.21% | 2.65 |
| T+5 | 59.51% | 2.70% | 2.69 | 60.00% | 2.83% | 2.76 |

Conclusion: V2 is worth keeping for wide breakout because it improves quality with limited sample loss.

Recent stress-slice fixed-horizon net results:

| Exit | Trades | Win | Mean | PF | MaxDD |
| --- | ---: | ---: | ---: | ---: | ---: |
| T+1 | 15 | 46.67% | -0.07% | 0.96 | -10.88% |
| T+2 | 15 | 40.00% | -0.90% | 0.65 | -6.72% |
| T+3 | 15 | 33.33% | -2.26% | 0.38 | -15.51% |

Best tested stress-slice V5 profile:

| Profile | Trades | Win | Mean | PF | MaxDD | Avg Hold |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `trail3.5%_2.0%_stop5.5%_t3` | 15 | 60.00% | 0.77% | 1.86 | -4.87% | 2.20 |

## Adopted Gray-Release Config

Config path: `stock_selection.wide_breakout`

- entry preset remains fixed at `wide_pool_strict_entry_v2`
- high-score weak-confirm guard: enabled
- market-ret5 median guard: retained but disabled
- exit:
  - base/B max hold: 3 days
  - A max hold: 4 days
  - base/B trail arm: 4.0%
  - A trail arm: 4.5%
  - trailing gap: 2.5%
  - fixed stop: -4.5%
  - weakness MA/previous-low rules: disabled

Fresh 126-day A/B policy:

| Policy | Trades | Win | Mean | PF | Total | MaxDD |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `A=trail5.0%_2.5%_stop4.5%_t4;B=trail4.0%_2.5%_stop4.5%_t3` | 195 | 68.21% | 1.76% | 2.92 | 168.26% | -13.43% |
| `A=trail4.5%_2.5%_stop4.5%_t4;B=trail4.0%_2.5%_stop4.5%_t3` | 195 | 69.23% | 1.70% | 2.90 | 154.66% | -13.90% |

Walk-forward stability:

| Policy | Split | Trades | Win | Mean | PF | Total | MaxDD |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `A=5.0;B=4.0` | train | 159 | 68.55% | 1.86% | 3.11 | 116.47% | -11.63% |
| `A=5.0;B=4.0` | oos | 36 | 66.67% | 1.33% | 2.21 | 23.92% | -13.43% |
| `A=5.0;B=4.0` | recent | 27 | 55.56% | 0.35% | 1.24 | 1.26% | -13.43% |
| `A=4.5;B=4.0` | train | 159 | 69.18% | 1.74% | 2.99 | 102.22% | -13.90% |
| `A=4.5;B=4.0` | oos | 36 | 69.44% | 1.51% | 2.56 | 25.93% | -12.02% |
| `A=4.5;B=4.0` | recent | 27 | 59.26% | 0.58% | 1.45 | 2.91% | -12.02% |

Conclusion: `A=5.0;B=4.0` has slightly higher full-window total return, but `A=4.5;B=4.0` is more stable out of sample and in the recent stress slice. The gray-release mainline therefore uses `A=4.5;B=4.0`.

## Next Validation

Keep this as the wide breakout V2/V5 gray-release profile unless a broader walk-forward window shows deterioration. The short weak-market slice can remain a stress-test reference, not the main parameter driver.
