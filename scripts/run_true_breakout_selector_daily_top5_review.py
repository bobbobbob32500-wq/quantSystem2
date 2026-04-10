from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import sqlite3


ROOT = Path(r"D:\HuaweiAI\quantSystem2")
SNAPSHOT = ROOT / "data/research/strong_start_full/event_feature_snapshot_batch4.parquet"
DB_PATH = ROOT / "data/database/quant_system.db"
OUT_DIR = ROOT / "data/research/strong_start_full/v4_scan"

OUT_MAIN = OUT_DIR / "true_breakout_selector_daily_top5_review.parquet"
OUT_SUMMARY = OUT_DIR / "true_breakout_selector_daily_top5_summary.json"
OUT_COMPARE = OUT_DIR / "true_breakout_selector_top5_vs_6_10.csv"
OUT_STABILITY = OUT_DIR / "true_breakout_selector_top5_stability.csv"
OUT_LABEL = OUT_DIR / "true_breakout_selector_top5_by_label.csv"
OUT_REVIEW = OUT_DIR / "true_breakout_selector_top5_review.md"


def _rank01(s: pd.Series, higher: bool = True) -> pd.Series:
    x = pd.to_numeric(s, errors="coerce")
    if not higher:
        x = -x
    return x.rank(method="average", pct=True)


def _build_selector(df: pd.DataFrame) -> pd.DataFrame:
    x = df.copy()
    x["pass_hard_filters"] = (
        (x["f_trend_close_ma20_gap"] >= 0.02)
        & (x["f_strength_rs20_xsec_q"] >= 0.70)
        & (x["f_ind_rank_pctchg"] >= 0.80)
    )
    x["score_strength_axis"] = (
        _rank01(x["f_strength_ret20"], True)
        + _rank01(x["f_strength_ret60"], True)
        + _rank01(x["f_trend_ma20_ma60_gap"], True)
    ) / 3.0
    x["score_industry_axis"] = (
        _rank01(x["f_ind_strength_3d"], True)
        + _rank01(x["f_ind_strength_5d"], True)
        + _rank01(x["f_ind_rank_pctchg"], True)
    ) / 3.0
    x["score_chip_axis"] = (
        _rank01(x["f_chip_concentration"], True)
        + _rank01(x["f_chip_winner_rate"], True)
        + _rank01(x["f_chip_stability_std10"], True)
    ) / 3.0
    x["score_platform_axis"] = (
        _rank01(x["f_platform_range_best"], True)
        + _rank01(x["f_platform_compress_ratio"], True)
    ) / 2.0
    x["score_total"] = (
        0.40 * x["score_strength_axis"]
        + 0.35 * x["score_industry_axis"]
        + 0.20 * x["score_chip_axis"]
        + 0.05 * x["score_platform_axis"]
    )
    x["rank_pct"] = np.nan
    for d, g in x[x["pass_hard_filters"]].groupby("trade_date"):
        x.loc[g.index, "rank_pct"] = g["score_total"].rank(method="first", ascending=False, pct=True)
    return x


def _load_daily_forward() -> pd.DataFrame:
    conn = sqlite3.connect(DB_PATH)
    try:
        daily = pd.read_sql_query("select ts_code, trade_date, open, close from stock_daily", conn)
    finally:
        conn.close()
    daily["trade_date"] = daily["trade_date"].astype(str)
    for c in ["open", "close"]:
        daily[c] = pd.to_numeric(daily[c], errors="coerce")
    daily = daily.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)
    daily["buy_date"] = daily.groupby("ts_code")["trade_date"].shift(-1)
    daily["buy_open_t1"] = daily.groupby("ts_code")["open"].shift(-1)
    daily["close_t1"] = daily.groupby("ts_code")["close"].shift(-1)
    daily["close_t2"] = daily.groupby("ts_code")["close"].shift(-2)
    daily["close_t3"] = daily.groupby("ts_code")["close"].shift(-3)
    return daily[["ts_code", "trade_date", "buy_date", "buy_open_t1", "close_t1", "close_t2", "close_t3"]]


def _h_stats(df: pd.DataFrame, col: str) -> dict:
    s = pd.to_numeric(df[col], errors="coerce").dropna()
    if len(s) == 0:
        return {"n": 0, "avg": None, "median": None, "win_rate": None}
    return {
        "n": int(len(s)),
        "avg": float(s.mean()),
        "median": float(s.median()),
        "win_rate": float((s > 0).mean()),
    }


def _group_perf(df: pd.DataFrame, group_name: str, mask: pd.Series) -> dict:
    d = df[mask].copy()
    return {
        "group": group_name,
        "n": int(len(d)),
        "t1_avg": float(d["ret_close_t1"].mean()) if len(d) else np.nan,
        "t1_med": float(d["ret_close_t1"].median()) if len(d) else np.nan,
        "t1_win": float((d["ret_close_t1"] > 0).mean()) if len(d) else np.nan,
        "t2_avg": float(d["ret_close_t2"].mean()) if len(d) else np.nan,
        "t2_med": float(d["ret_close_t2"].median()) if len(d) else np.nan,
        "t2_win": float((d["ret_close_t2"] > 0).mean()) if len(d) else np.nan,
        "t3_avg": float(d["ret_close_t3"].mean()) if len(d) else np.nan,
        "t3_med": float(d["ret_close_t3"].median()) if len(d) else np.nan,
        "t3_win": float((d["ret_close_t3"] > 0).mean()) if len(d) else np.nan,
    }


def main() -> None:
    raw = pd.read_parquet(SNAPSHOT)
    raw = raw[raw["label_abc"].isin(["A", "C"])].copy()
    raw["trade_date"] = raw["trade_date"].astype(str)
    s = _build_selector(raw)

    # recent 6 months for mid-window review
    max_t = pd.to_datetime(s["trade_date"].max(), format="%Y%m%d")
    start_t = max_t - pd.Timedelta(days=183)
    s = s[
        (pd.to_datetime(s["trade_date"], format="%Y%m%d") >= start_t)
        & (pd.to_datetime(s["trade_date"], format="%Y%m%d") <= max_t)
    ].copy()

    # rank only hard-filter-pass events per day
    s["daily_rank"] = np.nan
    pass_df = s[s["pass_hard_filters"]].copy()
    for d, g in pass_df.groupby("trade_date"):
        rk = g["score_total"].rank(method="first", ascending=False)
        s.loc[g.index, "daily_rank"] = rk

    s["daily_group"] = "other"
    s.loc[s["daily_rank"] <= 5, "daily_group"] = "top5"
    s.loc[(s["daily_rank"] >= 6) & (s["daily_rank"] <= 10), "daily_group"] = "rank6_10"

    fwd = _load_daily_forward()
    m = s.merge(fwd, on=["ts_code", "trade_date"], how="left")
    m = m.dropna(subset=["buy_open_t1", "close_t1", "close_t2", "close_t3"]).copy()

    m["ret_close_t1"] = m["close_t1"] / m["buy_open_t1"] - 1
    m["ret_close_t2"] = m["close_t2"] / m["buy_open_t1"] - 1
    m["ret_close_t3"] = m["close_t3"] / m["buy_open_t1"] - 1
    m["win_t1"] = m["ret_close_t1"] > 0
    m["win_t2"] = m["ret_close_t2"] > 0
    m["win_t3"] = m["ret_close_t3"] > 0
    m["month"] = pd.to_datetime(m["trade_date"], format="%Y%m%d").dt.to_period("M").astype(str)

    out_cols = [
        "trade_date",
        "ts_code",
        "score_total",
        "daily_rank",
        "daily_group",
        "rank_pct",
        "buy_date",
        "buy_open_t1",
        "close_t1",
        "close_t2",
        "close_t3",
        "ret_close_t1",
        "ret_close_t2",
        "ret_close_t3",
        "win_t1",
        "win_t2",
        "win_t3",
        "label_abc",
    ]
    m[out_cols].to_parquet(OUT_MAIN, index=False)

    top5 = m[m["daily_group"] == "top5"].copy()
    g610 = m[m["daily_group"] == "rank6_10"].copy()

    overall_top5 = {
        "t1": _h_stats(top5, "ret_close_t1"),
        "t2": _h_stats(top5, "ret_close_t2"),
        "t3": _h_stats(top5, "ret_close_t3"),
    }
    summary = {
        "window": {
            "start": str(m["trade_date"].min()) if len(m) else None,
            "end": str(m["trade_date"].max()) if len(m) else None,
            "months": sorted(m["month"].dropna().unique().tolist()),
            "sample_count_all_groups": int(len(m)),
            "sample_count_top5": int(len(top5)),
            "sample_count_rank6_10": int(len(g610)),
        },
        "top5_overall": overall_top5,
    }
    OUT_SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    compare = pd.DataFrame(
        [
            _group_perf(m, "top5", m["daily_group"] == "top5"),
            _group_perf(m, "rank6_10", m["daily_group"] == "rank6_10"),
        ]
    )
    compare.to_csv(OUT_COMPARE, index=False, encoding="utf-8-sig")

    # stability checks (daily top5)
    daily_top5 = (
        top5.groupby("trade_date")
        .agg(
            top5_avg_t1=("ret_close_t1", "mean"),
            top5_win_t1=("win_t1", "mean"),
        )
        .reset_index()
    )
    daily_610 = (
        g610.groupby("trade_date")
        .agg(rank6_10_avg_t1=("ret_close_t1", "mean"))
        .reset_index()
    )
    st = daily_top5.merge(daily_610, on="trade_date", how="left")
    pos_days = int((st["top5_avg_t1"] > 0).sum())
    win50_days = int((st["top5_win_t1"] > 0.5).sum())
    better_days = int((st["top5_avg_t1"] > st["rank6_10_avg_t1"]).sum())
    st["top5_better_than_6_10"] = st["top5_avg_t1"] > st["rank6_10_avg_t1"]

    month_top5 = (
        top5.groupby("month")
        .agg(
            n=("ts_code", "count"),
            avg_ret_t1=("ret_close_t1", "mean"),
            win_t1=("win_t1", "mean"),
        )
        .reset_index()
    )
    stability = st.copy()
    stability.to_csv(OUT_STABILITY, index=False, encoding="utf-8-sig")

    # by label for top5 / rank6_10
    label_rows = []
    for grp in ["top5", "rank6_10"]:
        d = m[m["daily_group"] == grp]
        for lab, sub in d.groupby("label_abc"):
            label_rows.append(
                {
                    "group": grp,
                    "label_abc": lab,
                    "n": int(len(sub)),
                    "avg_ret_t1": float(sub["ret_close_t1"].mean()) if len(sub) else np.nan,
                    "med_ret_t1": float(sub["ret_close_t1"].median()) if len(sub) else np.nan,
                    "win_t1": float((sub["ret_close_t1"] > 0).mean()) if len(sub) else np.nan,
                    "avg_ret_t2": float(sub["ret_close_t2"].mean()) if len(sub) else np.nan,
                    "med_ret_t2": float(sub["ret_close_t2"].median()) if len(sub) else np.nan,
                    "win_t2": float((sub["ret_close_t2"] > 0).mean()) if len(sub) else np.nan,
                    "avg_ret_t3": float(sub["ret_close_t3"].mean()) if len(sub) else np.nan,
                    "med_ret_t3": float(sub["ret_close_t3"].median()) if len(sub) else np.nan,
                    "win_t3": float((sub["ret_close_t3"] > 0).mean()) if len(sub) else np.nan,
                }
            )
    by_label = pd.DataFrame(label_rows)
    by_label.to_csv(OUT_LABEL, index=False, encoding="utf-8-sig")

    review = [
        "# true_breakout_selector_top5_review",
        "",
        f"- window: {summary['window']['start']} ~ {summary['window']['end']}",
        f"- months: {', '.join(summary['window']['months'])}",
        f"- top5 samples: {summary['window']['sample_count_top5']}, rank6_10 samples: {summary['window']['sample_count_rank6_10']}",
        "",
        "## Top5 overall",
        f"- T+1: {overall_top5['t1']}",
        f"- T+2: {overall_top5['t2']}",
        f"- T+3: {overall_top5['t3']}",
        "",
        "## Top5 vs rank6_10",
        compare.to_string(index=False),
        "",
        "## Stability",
        f"- days(top5 avg t1 > 0): {pos_days}",
        f"- days(top5 win t1 > 50%): {win50_days}",
        f"- days(top5 avg t1 > rank6_10 avg t1): {better_days}",
        "",
        "## Monthly Top5 (T+1)",
        month_top5.to_string(index=False),
        "",
        "## By label",
        by_label.to_string(index=False),
    ]
    OUT_REVIEW.write_text("\n".join(review), encoding="utf-8")

    print("Generated:")
    print(" -", OUT_MAIN)
    print(" -", OUT_SUMMARY)
    print(" -", OUT_COMPARE)
    print(" -", OUT_STABILITY)
    print(" -", OUT_LABEL)
    print(" -", OUT_REVIEW)


if __name__ == "__main__":
    main()

