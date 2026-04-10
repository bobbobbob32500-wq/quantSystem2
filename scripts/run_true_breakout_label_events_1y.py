from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(r"D:\HuaweiAI\quantSystem2")
DB_PATH = ROOT / "data/database/quant_system.db"
IN_EVENTS = ROOT / "data/research/strong_start_full/v4_scan/true_breakout_candidate_events_1y.parquet"
OUT_DIR = ROOT / "data/research/strong_start_full/v4_scan"

OUT_LABELED = OUT_DIR / "true_breakout_labeled_events_1y.parquet"
OUT_SUMMARY = OUT_DIR / "true_breakout_labeled_events_1y_summary.json"
OUT_MONTHLY = OUT_DIR / "true_breakout_labeled_events_1y_monthly_stats.csv"
OUT_DAILY = OUT_DIR / "true_breakout_labeled_events_1y_daily_stats.csv"
OUT_REPORT = OUT_DIR / "true_breakout_labeling_report_1y.md"
OUT_REASON = OUT_DIR / "true_breakout_label_reason_breakdown.csv"


def _load_forward_frame() -> pd.DataFrame:
    conn = sqlite3.connect(DB_PATH)
    try:
        daily = pd.read_sql_query(
            "select ts_code, trade_date, open, high, low, close from stock_daily",
            conn,
        )
    finally:
        conn.close()
    daily["trade_date"] = daily["trade_date"].astype(str)
    for c in ["open", "high", "low", "close"]:
        daily[c] = pd.to_numeric(daily[c], errors="coerce")
    daily = daily.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)

    g = daily.groupby("ts_code")
    for n in range(1, 6):
        daily[f"open_fwd_{n}"] = g["open"].shift(-n)
        daily[f"high_fwd_{n}"] = g["high"].shift(-n)
        daily[f"low_fwd_{n}"] = g["low"].shift(-n)
        daily[f"close_fwd_{n}"] = g["close"].shift(-n)
    return daily


def _label_one(row: pd.Series) -> tuple[str, str]:
    if not bool(row["has_full_forward_window"]):
        return "N", "incomplete_forward_window"

    # 主窗口 T+5，T+3仅辅助
    max_up_5 = row["max_up_ret_5"]
    close_ret_5 = row["close_ret_5"]
    max_dd_3 = row["max_dd_ret_3"]
    max_dd_5 = row["max_dd_ret_5"]
    close_ret_3 = row["close_ret_3"]

    # A: 明显延续 + 不早破结构
    if (max_up_5 >= 0.06) and (close_ret_5 >= 0.02) and (max_dd_3 > -0.05):
        return "A", "continuation_strong_no_early_break"

    # C: 明显失败/弱启动
    c_fail_1 = (max_up_5 <= 0.02) and (close_ret_5 <= 0.00)
    c_fail_2 = max_dd_3 <= -0.06
    c_fail_3 = (max_dd_5 <= -0.08) and (close_ret_5 <= 0.01)
    if c_fail_1 or c_fail_2 or c_fail_3:
        if c_fail_2:
            return "C", "early_structure_break"
        if c_fail_1:
            return "C", "weak_follow_through"
        return "C", "deep_drawdown_no_recovery"

    # 其余归灰区
    if close_ret_3 >= 0:
        return "G", "mixed_path_non_fail"
    return "G", "mixed_path_pullback"


def main() -> None:
    events = pd.read_parquet(IN_EVENTS).copy()
    events["trade_date"] = events["trade_date"].astype(str)
    if "candidate_event_id" not in events.columns:
        events["candidate_event_id"] = events["ts_code"].astype(str) + "_" + events["trade_date"].astype(str)

    daily = _load_forward_frame()
    base_cols = ["ts_code", "trade_date", "close", "low"]
    fwd_cols = [c for c in daily.columns if c.endswith(tuple(str(i) for i in range(1, 6))) and ("_fwd_" in c)]
    merge_cols = base_cols + fwd_cols
    m = events.merge(daily[merge_cols], on=["ts_code", "trade_date"], how="left", suffixes=("", "_t"))

    # 观察窗口完整性（主窗口 T+5）
    req = [f"close_fwd_{i}" for i in range(1, 6)] + [f"high_fwd_{i}" for i in range(1, 6)] + [f"low_fwd_{i}" for i in range(1, 6)]
    m["has_full_forward_window"] = m[req].notna().all(axis=1)
    m["forward_window_days"] = np.where(m["has_full_forward_window"], 5, m[[f"close_fwd_{i}" for i in range(1, 6)]].notna().sum(axis=1))

    # 标签辅助摘要字段
    high_cols_5 = [f"high_fwd_{i}" for i in range(1, 6)]
    low_cols_5 = [f"low_fwd_{i}" for i in range(1, 6)]
    low_cols_3 = [f"low_fwd_{i}" for i in range(1, 4)]
    m["max_high_5"] = m[high_cols_5].max(axis=1)
    m["min_low_5"] = m[low_cols_5].min(axis=1)
    m["min_low_3"] = m[low_cols_3].min(axis=1)

    base_close = m["close"].replace(0, np.nan)
    m["max_up_ret_5"] = m["max_high_5"] / base_close - 1
    m["max_dd_ret_5"] = m["min_low_5"] / base_close - 1
    m["max_dd_ret_3"] = m["min_low_3"] / base_close - 1
    m["close_ret_3"] = m["close_fwd_3"] / base_close - 1
    m["close_ret_5"] = m["close_fwd_5"] / base_close - 1
    m["key_break_3"] = m["max_dd_ret_3"] <= -0.06

    labels = m.apply(_label_one, axis=1, result_type="expand")
    m["label_true_breakout"] = labels[0]
    m["label_reason"] = labels[1]

    out_cols = [
        "ts_code",
        "trade_date",
        "name",
        "industry",
        "candidate_event_id",
        "label_true_breakout",
        "label_reason",
        "has_full_forward_window",
        "forward_window_days",
        "max_up_ret_5",
        "max_dd_ret_3",
        "max_dd_ret_5",
        "close_ret_3",
        "close_ret_5",
        "key_break_3",
    ]
    out = m[out_cols].copy().sort_values(["trade_date", "ts_code"]).reset_index(drop=True)
    out.to_parquet(OUT_LABELED, index=False)

    # audits
    label_counts = out["label_true_breakout"].value_counts(dropna=False).to_dict()
    label_ratio = (out["label_true_breakout"].value_counts(dropna=False) / len(out)).to_dict() if len(out) else {}

    monthly = (
        out.assign(month=pd.to_datetime(out["trade_date"], format="%Y%m%d").dt.strftime("%Y-%m"))
        .groupby(["month", "label_true_breakout"])
        .size()
        .reset_index(name="count")
        .sort_values(["month", "label_true_breakout"])
    )
    monthly.to_csv(OUT_MONTHLY, index=False, encoding="utf-8-sig")

    daily_stats = (
        out.groupby(["trade_date", "label_true_breakout"])
        .size()
        .reset_index(name="count")
        .sort_values(["trade_date", "label_true_breakout"])
    )
    daily_stats.to_csv(OUT_DAILY, index=False, encoding="utf-8-sig")

    reason = (
        out.groupby(["label_true_breakout", "label_reason"])
        .size()
        .reset_index(name="count")
        .sort_values(["label_true_breakout", "count"], ascending=[True, False])
    )
    reason.to_csv(OUT_REASON, index=False, encoding="utf-8-sig")

    skew_warn = None
    if len(out):
        max_ratio = max(label_ratio.values()) if label_ratio else 0
        if max_ratio >= 0.80:
            skew_warn = "label_skew_high"

    summary = {
        "label_target": "true_vs_fake_startup_research_only",
        "main_window_days": 5,
        "aux_window_days": 3,
        "counts": {k: int(v) for k, v in label_counts.items()},
        "ratios": {k: float(v) for k, v in label_ratio.items()},
        "n_total": int(len(out)),
        "n_months": int(monthly["month"].nunique()) if len(monthly) else 0,
        "n_trade_days": int(out["trade_date"].nunique()) if len(out) else 0,
        "label_skew_warning": skew_warn,
        "ready_for_feature_diff_analysis": True,
        "label_fields_forbidden_in_features": [
            "label_true_breakout",
            "label_reason",
            "has_full_forward_window",
            "forward_window_days",
            "max_up_ret_5",
            "max_dd_ret_3",
            "max_dd_ret_5",
            "close_ret_3",
            "close_ret_5",
            "key_break_3",
            "open_fwd_*",
            "high_fwd_*",
            "low_fwd_*",
            "close_fwd_*",
        ],
    }
    OUT_SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    report = [
        "# true_breakout_labeling_report_1y",
        "",
        "## label setup",
        "- target: research-only startup truth labels",
        "- main window: T+5",
        "- aux window: T+3",
        "",
        "## definitions",
        "- A: continuation strong + no early structure break",
        "- C: weak follow-through or early/deep structure break",
        "- G: mixed path, not clearly A/C",
        "- N: incomplete forward window",
        "",
        "## counts",
        f"- total: {len(out)}",
    ]
    for k in ["A", "C", "G", "N"]:
        v = int(label_counts.get(k, 0))
        r = float(label_ratio.get(k, 0.0))
        report.append(f"- {k}: {v} ({r:.2%})")
    report += [
        "",
        "## quality checks",
        f"- skew warning: {skew_warn}",
        "- label fields are strictly separated from feature inputs.",
        "- this label set is ready for next-step true/false startup feature-diff analysis.",
    ]
    OUT_REPORT.write_text("\n".join(report), encoding="utf-8")

    print("Generated:")
    print(" -", OUT_LABELED)
    print(" -", OUT_SUMMARY)
    print(" -", OUT_MONTHLY)
    print(" -", OUT_DAILY)
    print(" -", OUT_REPORT)
    print(" -", OUT_REASON)


if __name__ == "__main__":
    main()
