# -*- coding: utf-8 -*-
"""Build strong_start v3 research params from sample-mining outputs."""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
from typing import Dict, List

import pandas as pd
import yaml


def _clip(value: float, low: float, high: float) -> float:
    return max(low, min(high, float(value)))


def _load_threshold_map(path: Path) -> Dict[str, dict]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    items = data.get("threshold_candidates", []) or []
    out: Dict[str, dict] = {}
    for it in items:
        key = str(it.get("feature", "")).strip()
        if key:
            out[key] = dict(it)
    return out


def _event_type_stats(df: pd.DataFrame) -> List[dict]:
    base = df[df["label_abc"].isin(["A", "B", "C"])].copy()
    if base.empty:
        return []
    tab = (
        base.groupby(["event_type_candidate", "label_abc"])["ts_code"]
        .count()
        .unstack(fill_value=0)
        .reset_index()
    )
    for c in ["A", "B", "C"]:
        if c not in tab.columns:
            tab[c] = 0
    tab["total"] = tab["A"] + tab["B"] + tab["C"]
    tab["A_rate"] = tab["A"] / tab["total"].replace(0, pd.NA)
    tab["AB_rate"] = (tab["A"] + tab["B"]) / tab["total"].replace(0, pd.NA)
    tab = tab.sort_values(["AB_rate", "A_rate"], ascending=False)
    rows: List[dict] = []
    for _, r in tab.iterrows():
        rows.append(
            {
                "event_type_candidate": str(r["event_type_candidate"]),
                "A": int(r["A"]),
                "B": int(r["B"]),
                "C": int(r["C"]),
                "total": int(r["total"]),
                "A_rate": float(r["A_rate"]) if pd.notna(r["A_rate"]) else None,
                "AB_rate": float(r["AB_rate"]) if pd.notna(r["AB_rate"]) else None,
            }
        )
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Build v3 research params from mined sample outputs.")
    parser.add_argument(
        "--thresholds-path",
        default="data/research/strong_start_full/candidate_thresholds.yaml",
    )
    parser.add_argument(
        "--labeled-events-path",
        default="data/research/strong_start_full/labeled_events.parquet",
    )
    parser.add_argument(
        "--output-path",
        default="data/research/strong_start_full/strong_start_v3_research_params.yaml",
    )
    args = parser.parse_args()

    thresholds_path = Path(args.thresholds_path)
    labeled_path = Path(args.labeled_events_path)
    output_path = Path(args.output_path)
    if not thresholds_path.exists():
        raise FileNotFoundError(f"thresholds not found: {thresholds_path}")
    if not labeled_path.exists():
        raise FileNotFoundError(f"labeled events not found: {labeled_path}")

    th = _load_threshold_map(thresholds_path)
    labeled = pd.read_parquet(labeled_path)
    type_stats = _event_type_stats(labeled)

    rs20_min = _clip(float(th.get("rs20_xsec_q", {}).get("suggested_min") or 0.65), 0.55, 0.90)
    rs60_min = _clip(float(th.get("rs60_xsec_q", {}).get("suggested_min") or 0.50), 0.40, 0.85)
    winner_min = _clip(float(th.get("winner_rate", {}).get("suggested_min") or 0.70), 0.55, 0.95)
    vol_ratio20_min = _clip(float(th.get("vol_ratio20", {}).get("suggested_min") or 1.6), 1.2, 2.5)
    close_pos_min = _clip(float(th.get("close_pos", {}).get("suggested_min") or 0.75), 0.45, 0.95)
    cond_count_min = int(_clip(float(th.get("candidate_condition_count", {}).get("suggested_min") or 4), 3, 6))
    pct_chg_min = float(th.get("pct_chg", {}).get("suggested_min") or 2.5)

    # Derived strategy-facing defaults:
    # - keep both breakout/pullback enabled
    # - avoid over-tight chip thresholds (score-favor over hard-kill)
    params = {
        "preset_name": "tradeable_v3_research",
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "sample_window": {
            "labels_total": int(len(labeled)),
            "label_counts": {
                "A": int((labeled["label_abc"] == "A").sum()),
                "B": int((labeled["label_abc"] == "B").sum()),
                "C": int((labeled["label_abc"] == "C").sum()),
                "N": int((labeled["label_abc"] == "N").sum()),
            },
        },
        "event_type_stats": type_stats,
        "research_filters": {
            "candidate_condition_count_min": cond_count_min,
            "candidate_pct_chg_min": round(pct_chg_min, 4),
            "candidate_vol_ratio20_min": round(vol_ratio20_min, 4),
            "allowed_event_types": [
                r["event_type_candidate"]
                for r in type_stats
                if (r.get("AB_rate") or 0.0) >= 0.20
            ],
        },
        "strategy_params": {
            "min_amt_ma20": 5e4,
            "rs_quantile_min": round(rs20_min, 4),
            "rs_quantile_soft_ref_60": round(rs60_min, 4),
            "platform_max_range": 0.24,
            "vol_contraction_ratio": 1.10,
            "low_vol_days_required": 2,
            "atr_squeeze_quantile_max": 0.85,
            "breakout_volume_ratio": round(max(1.2, vol_ratio20_min * 0.72), 4),
            "breakout_close_pos_min": round(max(0.50, close_pos_min * 0.78), 4),
            "pullback_volume_shrink_ratio": 0.95,
            "chip_concentration_max": 0.24,
            "chip_stability_std_max": 0.05,
            "chip_low_position_max": 0.88,
            "winner_rate_min": round(winner_min, 4),
            "winner_rate_max": 0.985,
            "chip_peak_count_max": 8,
            "chip_peak_secondary_ratio_max": 1.0,
            "chip_peak_dominance_min": 0.0,
            "chip_single_peak_score_min": 0.10,
            "min_signal_score": 42.0,
            "top_k": 12,
            "allow_breakout_setup": True,
            "allow_pullback_setup": True,
            "chip_factor_profile_key": "tradeable_v3_research",
        },
        "notes": [
            "Parameters are derived from sample-mining distributions and should be validated with train/valid/holdout runs.",
            "Breakout and pullback are both enabled by design because breakout-like events show stronger AB rates than trend-high events.",
            "Chip constraints are intentionally relaxed for v3_research to avoid v2-style over-filtering.",
        ],
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        yaml.safe_dump(params, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    print("=" * 70)
    print("v3 research params built")
    print("=" * 70)
    print(f"thresholds={thresholds_path}")
    print(f"labels={labeled_path}")
    print(f"output={output_path}")


if __name__ == "__main__":
    main()

