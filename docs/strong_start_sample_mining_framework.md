# Strong Start Sample-Mining Framework

This framework separates research from trading execution.

## Goal

1. Mine event-day samples from the full main-board universe.
2. Label events by tradable forward outcome (A/B/C).
3. Compare A vs C feature distributions.
4. Derive threshold hints for a later trading strategy.

## Scripts

1. `scripts/build_start_event_candidates.py`
2. `scripts/label_start_events.py`
3. `scripts/extract_start_event_features.py`
4. `scripts/analyze_start_samples.py`

Outputs are written to `data/research/strong_start` by default.

## Quick Start

```powershell
python scripts/build_start_event_candidates.py --start-date 20250403 --end-date 20260403
python scripts/label_start_events.py
python scripts/extract_start_event_features.py
python scripts/analyze_start_samples.py
```

## Industry Strength Source

Current sample-mining workflow builds industry strength from local:

- `stock_basic.industry`
- `stock_daily`

This avoids dependency on empty `block_data` and keeps historical research deterministic.

If you want board-level historical data in `block_data`, use:

```powershell
python scripts/download_industry_history_akshare.py --start-date 20240101 --end-date 20260403
```

Or use Tushare-first with automatic local fallback:

```powershell
python scripts/download_industry_history_tushare.py --start-date 20240101 --end-date 20260403 --mode auto --mainboard-only
```

## Notes

- This is event-level research, not final trading logic.
- Features are based on T-day visible information only.
- Threshold hints from analysis are candidates, not final live parameters.
