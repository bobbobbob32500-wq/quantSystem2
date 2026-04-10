from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

import run_true_breakout_schemeB_validation as schemeb


ROOT = Path(r"D:\HuaweiAI\quantSystem2")
BASE = ROOT / "data/research/strong_start_full/v4_scan"

OUT_MVP = BASE / "true_breakout_strategy_mvp.csv"
OUT_SUMMARY = BASE / "true_breakout_strategy_mvp_summary.csv"
OUT_README = BASE / "true_breakout_strategy_mvp_readme.md"


def summarize_mvp(core: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict] = []
    groups = [
        ("core_pool", core),
        ("priority_tag_1", core[core["priority_tag"] == 1]),
        ("priority_tag_0", core[core["priority_tag"] == 0]),
    ]

    for name, g in groups:
        if g.empty:
            continue
        n = len(g)
        row = {
            "group": name,
            "sample_n": int(n),
            "A_high_pct": float(g["label_A_high"].mean()) if "label_A_high" in g.columns else None,
            "A_mid_pct": float(g["label_A_mid"].mean()) if "label_A_mid" in g.columns else None,
            "A_low_pct": float(g["label_A_low"].mean()) if "label_A_low" in g.columns else None,
            "C_pct": float(g["label_C"].mean()) if "label_C" in g.columns else None,
            "G_pct": float(g["label_G"].mean()) if "label_G" in g.columns else None,
            "mean_ret_t1": float(g["ret_t1_close"].mean()) if "ret_t1_close" in g.columns else None,
            "mean_ret_t2": float(g["ret_t2_close"].mean()) if "ret_t2_close" in g.columns else None,
            "mean_ret_t3": float(g["ret_t3_close"].mean()) if "ret_t3_close" in g.columns else None,
            "median_ret_t1": float(g["ret_t1_close"].median()) if "ret_t1_close" in g.columns else None,
            "median_ret_t2": float(g["ret_t2_close"].median()) if "ret_t2_close" in g.columns else None,
            "median_ret_t3": float(g["ret_t3_close"].median()) if "ret_t3_close" in g.columns else None,
            "win_t1": float((g["ret_t1_close"] > 0).mean()) if "ret_t1_close" in g.columns else None,
            "win_t2": float((g["ret_t2_close"] > 0).mean()) if "ret_t2_close" in g.columns else None,
            "win_t3": float((g["ret_t3_close"] > 0).mean()) if "ret_t3_close" in g.columns else None,
        }
        rows.append(row)
    return pd.DataFrame(rows)


def write_readme() -> None:
    lines = [
        "# True Breakout Strategy MVP",
        "",
        "## Frozen strategy conclusion",
        "- Main system: `v3.2_candidate`",
        "- Enhancement tag: `v3.1_relaxed`",
        "- `priority_tag = 1 if (pass_v3_2_candidate == 1 and pass_v3_1_relaxed == 1) else 0`",
        "- Current stage does **not** enter buy-point research.",
        "",
        "## What this MVP does",
        "- Generates core candidate pool using frozen Scheme B logic.",
        "- Adds `priority_tag` layer within the core pool.",
        "- Exports fixed-horizon lightweight return review (`T+1/T+2/T+3` close vs `T+1` open).",
        "",
        "## How to run",
        "- Script: `D:/HuaweiAI/quantSystem2/scripts/run_true_breakout_strategy_mvp.py`",
        "- Command: `python D:/HuaweiAI/quantSystem2/scripts/run_true_breakout_strategy_mvp.py`",
        "- Output dir: `D:/HuaweiAI/quantSystem2/data/research/strong_start_full/v4_scan/`",
        "",
        "## Current boundaries",
        "- No buy-point logic",
        "- No sell-point logic",
        "- No full backtest",
        "- No parameter optimization",
    ]
    OUT_README.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    snapshot = pd.read_parquet(schemeb.SNAPSHOT)
    base_selected = schemeb.build_base_selected(snapshot)
    enriched = schemeb.add_returns_and_quality(base_selected)

    v32_mask = schemeb.apply_v32_mask(enriched)
    v31_relaxed_mask = schemeb.apply_v31_relaxed_mask(enriched)

    core = enriched[v32_mask].copy()
    core["is_core_candidate"] = 1
    core["pass_v3_2_candidate"] = 1
    core["pass_v3_1_relaxed"] = v31_relaxed_mask.loc[core.index].astype(int)
    core["priority_tag"] = ((v31_relaxed_mask.loc[core.index]) & (core["is_core_candidate"] == 1)).astype(int)
    core["priority_reason"] = core["priority_tag"].map(
        {1: "in_v32_core_and_hit_v31_relaxed", 0: "in_v32_core_only"}
    )
    core["selector_reject_reason"] = ""
    core["selector_explain"] = (
        "schemeB:v32_core;"
        + "path="
        + core["path_source"].astype(str)
        + ";priority_tag="
        + core["priority_tag"].astype(str)
    )
    core["stock_code"] = core["ts_code"]
    core["stock_name"] = core["name"]
    core["ret_t1_close"] = core["ret_t1"]
    core["ret_t2_close"] = core["ret_t2"]
    core["ret_t3_close"] = core["ret_t3"]
    core["label_A_high"] = ((core["label_true_breakout"] == "A") & (core["a_quality_layer"] == "A_high")).astype(int)
    core["label_A_mid"] = ((core["label_true_breakout"] == "A") & (core["a_quality_layer"] == "A_mid")).astype(int)
    core["label_A_low"] = ((core["label_true_breakout"] == "A") & (core["a_quality_layer"] == "A_low")).astype(int)
    core["label_C"] = (core["label_true_breakout"] == "C").astype(int)
    core["label_G"] = (core["label_true_breakout"] == "G").astype(int)

    out_cols = [
        "trade_date",
        "stock_code",
        "stock_name",
        "pass_v3_2_candidate",
        "pass_v3_1_relaxed",
        "is_core_candidate",
        "priority_tag",
        "priority_reason",
        "path_source",
        "rank_global_after_merge",
        "selector_explain",
        "score_total",
        "ret_t1_close",
        "ret_t2_close",
        "ret_t3_close",
        "label_A_high",
        "label_A_mid",
        "label_A_low",
        "label_C",
        "label_G",
    ]
    for c in out_cols:
        if c not in core.columns:
            core[c] = pd.NA
    mvp = core[out_cols].copy()
    mvp.to_csv(OUT_MVP, index=False, encoding="utf-8-sig")

    summary = summarize_mvp(mvp)
    summary.to_csv(OUT_SUMMARY, index=False, encoding="utf-8-sig")
    write_readme()

    # terminal summary
    core_row = summary[summary["group"] == "core_pool"].iloc[0] if not summary.empty else None
    p1_row = summary[summary["group"] == "priority_tag_1"].iloc[0] if not summary[summary["group"] == "priority_tag_1"].empty else None
    payload = {
        "total_samples": int(len(mvp)),
        "core_pool_samples": int(len(mvp)),
        "priority_tag_1_samples": int((mvp["priority_tag"] == 1).sum()),
        "core_t1_mean_win": {
            "mean": float(core_row["mean_ret_t1"]) if core_row is not None else None,
            "win": float(core_row["win_t1"]) if core_row is not None else None,
        },
        "core_t2_mean_win": {
            "mean": float(core_row["mean_ret_t2"]) if core_row is not None else None,
            "win": float(core_row["win_t2"]) if core_row is not None else None,
        },
        "core_t3_mean_win": {
            "mean": float(core_row["mean_ret_t3"]) if core_row is not None else None,
            "win": float(core_row["win_t3"]) if core_row is not None else None,
        },
        "tag_t1_mean_win": {
            "mean": float(p1_row["mean_ret_t1"]) if p1_row is not None else None,
            "win": float(p1_row["win_t1"]) if p1_row is not None else None,
        },
        "tag_t2_mean_win": {
            "mean": float(p1_row["mean_ret_t2"]) if p1_row is not None else None,
            "win": float(p1_row["win_t2"]) if p1_row is not None else None,
        },
        "tag_t3_mean_win": {
            "mean": float(p1_row["mean_ret_t3"]) if p1_row is not None else None,
            "win": float(p1_row["win_t3"]) if p1_row is not None else None,
        },
        "outputs": {
            "mvp": str(OUT_MVP),
            "summary": str(OUT_SUMMARY),
            "readme": str(OUT_README),
        },
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

