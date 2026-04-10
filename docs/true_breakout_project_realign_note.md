# true_breakout project realign note

Version: `realign_v1`
Date: 2026-04-09

## Mainline reset (effective now)
Current mainline:
- Extract true-breakout patterns from historical data
- Build selector-first strategy standards
- Entry/exit research postponed

## A) Retained assets (selector research)
- Event-day research methodology (event-level, no stock-level leakage)
- `event_feature_snapshot_batch1~4` feature snapshots
- A/C differential analysis outputs (feature discrimination)
- Feature ranking and redundancy audit outputs
- Parameter reverse-engineering conclusions (filter vs score layering)
- Research v4 feature-layer structure (as selector design reference)

## B) Frozen assets (trading branch, archived)
- breakout-B execution assumption branch
- execution validation loop artifacts
- breakout-B minimal backtest spec/impl/review branch
- all execution-mouthpiece documents and scripts under breakout-B branch

Statement:
- These trading-branch assets are archived and **not advanced further** in current phase.

## Restart point
- Return to selector research pipeline:
  1. define true/false breakout at event level
  2. selector feature layering
  3. selector-only validation design (no execution/backtest optimization)

