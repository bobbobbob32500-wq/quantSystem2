from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


ROOT = Path(r"D:\HuaweiAI\quantSystem2")
BASE = ROOT / "data/research/strong_start_full/v4_scan"

IN_COMPARE = BASE / "true_breakout_stage2_selector_round2_compare.csv"
IN_SUMMARY = BASE / "true_breakout_stage2_selector_round2_summary.json"

OUT_VALIDATION = BASE / "true_breakout_stage2_selector_replacement_validation.csv"
OUT_REVIEW = BASE / "true_breakout_stage2_selector_replacement_review.md"
OUT_SUMMARY = BASE / "true_breakout_stage2_selector_replacement_summary.json"

BASELINE = "R2_base_daily_top1"


def _scope_delta(df: pd.DataFrame, candidate: str, scope: str) -> dict:
    b = df[(df["scenario"] == BASELINE) & (df["scope"] == scope)].iloc[0]
    c = df[(df["scenario"] == candidate) & (df["scope"] == scope)].iloc[0]
    return {
        "scope": scope,
        "baseline": BASELINE,
        "candidate": candidate,
        "selected_n_baseline": int(b["selected_n"]),
        "selected_n_candidate": int(c["selected_n"]),
        "avg_days_per_signal_baseline": float(b["avg_days_per_signal"]),
        "avg_days_per_signal_candidate": float(c["avg_days_per_signal"]),
        "A_high_recall_rate_baseline": float(b["A_high_recall_rate"]),
        "A_high_recall_rate_candidate": float(c["A_high_recall_rate"]),
        "A_high_recall_delta": float(c["A_high_recall_rate"] - b["A_high_recall_rate"]),
        "A_high_over_C_baseline": float(b["A_high_over_C"]),
        "A_high_over_C_candidate": float(c["A_high_over_C"]),
        "A_high_over_C_delta": float(c["A_high_over_C"] - b["A_high_over_C"]),
        "win_t2_baseline": float(b["win_t2"]),
        "win_t2_candidate": float(c["win_t2"]),
        "win_t2_delta": float(c["win_t2"] - b["win_t2"]),
        "mean_ret_t2_baseline": float(b["mean_ret_t2"]),
        "mean_ret_t2_candidate": float(c["mean_ret_t2"]),
        "mean_ret_t2_delta": float(c["mean_ret_t2"] - b["mean_ret_t2"]),
    }


def main() -> None:
    if not IN_COMPARE.exists():
        raise FileNotFoundError(f"Missing compare file: {IN_COMPARE}")
    if not IN_SUMMARY.exists():
        raise FileNotFoundError(f"Missing summary file: {IN_SUMMARY}")

    compare = pd.read_csv(IN_COMPARE)
    summary = json.loads(IN_SUMMARY.read_text(encoding="utf-8"))
    candidate = str(summary.get("best_candidate", "")).strip()
    if not candidate:
        raise ValueError("best_candidate missing in round2 summary")
    if candidate == BASELINE:
        raise ValueError("best_candidate equals baseline; no replacement target")

    rows = []
    for scope in ["full_year", "main_window", "confirm_window"]:
        rows.append(_scope_delta(compare, candidate, scope))
    out_df = pd.DataFrame(rows)

    # 4 replacement criteria (minimal and explicit)
    fy = out_df[out_df["scope"] == "full_year"].iloc[0]
    mw = out_df[out_df["scope"] == "main_window"].iloc[0]
    cw = out_df[out_df["scope"] == "confirm_window"].iloc[0]

    crit1_recall_up = fy["A_high_recall_delta"] > 0.0
    crit2_purity_not_worse = fy["A_high_over_C_delta"] >= -0.05
    crit3_win_not_worse = fy["win_t2_delta"] >= -0.02
    # no direction flip: both windows should not show simultaneous purity+win sharp reverse
    crit4_no_window_flip = (
        (mw["A_high_over_C_delta"] >= -0.10 and mw["win_t2_delta"] >= -0.05)
        and (cw["A_high_over_C_delta"] >= -0.10 and cw["win_t2_delta"] >= -0.05)
    )
    final_replace = bool(crit1_recall_up and crit2_purity_not_worse and crit3_win_not_worse and crit4_no_window_flip)

    out_df["crit1_recall_up"] = crit1_recall_up
    out_df["crit2_purity_not_worse"] = crit2_purity_not_worse
    out_df["crit3_win_not_worse"] = crit3_win_not_worse
    out_df["crit4_no_window_flip"] = crit4_no_window_flip
    out_df["final_replace_decision"] = final_replace
    out_df.to_csv(OUT_VALIDATION, index=False, encoding="utf-8-sig")

    lines = [
        "# Stage2 Selector Replacement Validation",
        "",
        f"- Baseline: `{BASELINE}`",
        f"- Candidate: `{candidate}`",
        "",
        "## Replacement Criteria",
        "1. A_high recall must improve.",
        "2. A_high/C must not materially worsen (delta >= -0.05).",
        "3. T+2 win must not materially worsen (delta >= -0.02).",
        "4. Main/confirm windows must not flip direction (no sharp purity+win reverse).",
        "",
        "## Decision",
        f"- `crit1_recall_up`: {crit1_recall_up}",
        f"- `crit2_purity_not_worse`: {crit2_purity_not_worse}",
        f"- `crit3_win_not_worse`: {crit3_win_not_worse}",
        f"- `crit4_no_window_flip`: {crit4_no_window_flip}",
        f"- `final_replace_decision`: {final_replace}",
        "",
        "## Full-year Key Delta",
        f"- A_high_recall_delta: {fy['A_high_recall_delta']:.4%}",
        f"- A_high/C delta: {fy['A_high_over_C_delta']:.4f}",
        f"- T+2 win delta: {fy['win_t2_delta']:.2%}",
        f"- T+2 mean delta: {fy['mean_ret_t2_delta']:.2%}",
    ]
    OUT_REVIEW.write_text("\n".join(lines), encoding="utf-8")

    payload = {
        "baseline": BASELINE,
        "candidate": candidate,
        "criteria": {
            "crit1_recall_up": bool(crit1_recall_up),
            "crit2_purity_not_worse": bool(crit2_purity_not_worse),
            "crit3_win_not_worse": bool(crit3_win_not_worse),
            "crit4_no_window_flip": bool(crit4_no_window_flip),
        },
        "final_replace_decision": bool(final_replace),
        "full_year_delta": {
            "A_high_recall_delta": float(fy["A_high_recall_delta"]),
            "A_high_over_C_delta": float(fy["A_high_over_C_delta"]),
            "win_t2_delta": float(fy["win_t2_delta"]),
            "mean_ret_t2_delta": float(fy["mean_ret_t2_delta"]),
        },
        "files": {
            "validation": str(OUT_VALIDATION),
            "review": str(OUT_REVIEW),
        },
    }
    OUT_SUMMARY.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(str(OUT_VALIDATION))
    print(str(OUT_REVIEW))
    print(str(OUT_SUMMARY))


if __name__ == "__main__":
    main()
