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

OUT_MAIN = OUT_DIR / "true_breakout_selector_daily_topn_review.parquet"
OUT_SUMMARY = OUT_DIR / "true_breakout_selector_topn_summary.json"
OUT_COMPARE = OUT_DIR / "true_breakout_selector_top1_2_3_5_compare.csv"
OUT_TOP3_VS_45 = OUT_DIR / "true_breakout_selector_top3_vs_4_5.csv"
OUT_BY_LABEL = OUT_DIR / "true_breakout_selector_topn_by_label.csv"
OUT_STABILITY = OUT_DIR / "true_breakout_selector_top5_stability.csv"
OUT_REVIEW = OUT_DIR / "true_breakout_selector_topn_review.md"


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
    x["daily_rank"] = np.nan
    x["rank_pct"] = np.nan
    for d, g in x[x["pass_hard_filters"]].groupby("trade_date"):
        x.loc[g.index, "daily_rank"] = g["score_total"].rank(method="first", ascending=False)
        x.loc[g.index, "rank_pct"] = g["score_total"].rank(method="first", ascending=False, pct=True)
    return x


def _load_daily_forward() -> pd.DataFrame:
    conn = sqlite3.connect(DB_PATH)
    try:
        daily = pd.read_sql_query("select ts_code, trade_date, open, close from stock_daily", conn)
    finally:
        conn.close()
    daily["trade_date"] = daily["trade_date"].astype(str)
    daily["open"] = pd.to_numeric(daily["open"], errors="coerce")
    daily["close"] = pd.to_numeric(daily["close"], errors="coerce")
    daily = daily.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)
    daily["buy_date"] = daily.groupby("ts_code")["trade_date"].shift(-1)
    daily["buy_open_t1"] = daily.groupby("ts_code")["open"].shift(-1)
    daily["close_t1"] = daily.groupby("ts_code")["close"].shift(-1)
    daily["close_t2"] = daily.groupby("ts_code")["close"].shift(-2)
    return daily[["ts_code", "trade_date", "buy_date", "buy_open_t1", "close_t1", "close_t2"]]


def _perf(df: pd.DataFrame) -> dict:
    if len(df) == 0:
        return {
            "n": 0,
            "avg_ret_t1": None,
            "med_ret_t1": None,
            "win_t1": None,
            "avg_ret_t2": None,
            "med_ret_t2": None,
            "win_t2": None,
        }
    return {
        "n": int(len(df)),
        "avg_ret_t1": float(df["ret_close_t1"].mean()),
        "med_ret_t1": float(df["ret_close_t1"].median()),
        "win_t1": float(df["win_t1"].mean()),
        "avg_ret_t2": float(df["ret_close_t2"].mean()),
        "med_ret_t2": float(df["ret_close_t2"].median()),
        "win_t2": float(df["win_t2"].mean()),
    }


def main() -> None:
    raw = pd.read_parquet(SNAPSHOT)
    raw = raw[raw["label_abc"].isin(["A", "C"])].copy()
    raw["trade_date"] = raw["trade_date"].astype(str)
    s = _build_selector(raw)

    # same mid window as previous: recent ~6 months
    max_t = pd.to_datetime(s["trade_date"].max(), format="%Y%m%d")
    start_t = max_t - pd.Timedelta(days=183)
    s = s[
        (pd.to_datetime(s["trade_date"], format="%Y%m%d") >= start_t)
        & (pd.to_datetime(s["trade_date"], format="%Y%m%d") <= max_t)
    ].copy()

    # only hard-filter pass has valid daily rank
    s = s[s["pass_hard_filters"] & s["daily_rank"].notna()].copy()
    fwd = _load_daily_forward()
    s = s.merge(fwd, on=["ts_code", "trade_date"], how="left")
    s = s.dropna(subset=["buy_open_t1", "close_t1", "close_t2"]).copy()

    s["ret_close_t1"] = s["close_t1"] / s["buy_open_t1"] - 1
    s["ret_close_t2"] = s["close_t2"] / s["buy_open_t1"] - 1
    s["win_t1"] = s["ret_close_t1"] > 0
    s["win_t2"] = s["ret_close_t2"] > 0

    # cumulative groups: top1/top2/top3/top5
    rows = []
    base_cols = [
        "trade_date",
        "ts_code",
        "score_total",
        "daily_rank",
        "rank_pct",
        "buy_date",
        "buy_open_t1",
        "close_t1",
        "close_t2",
        "ret_close_t1",
        "ret_close_t2",
        "win_t1",
        "win_t2",
        "label_abc",
    ]
    base = s[base_cols].copy()
    for grp, cond in [
        ("top1", base["daily_rank"] <= 1),
        ("top2", base["daily_rank"] <= 2),
        ("top3", base["daily_rank"] <= 3),
        ("top5", base["daily_rank"] <= 5),
        ("rank6_10", (base["daily_rank"] >= 6) & (base["daily_rank"] <= 10)),
    ]:
        g = base[cond].copy()
        g["daily_group"] = grp
        rows.append(g)
    review = pd.concat(rows, ignore_index=True)
    review.to_parquet(OUT_MAIN, index=False)

    # summaries
    topn_stats = []
    for grp in ["top1", "top2", "top3", "top5", "rank6_10"]:
        d = review[review["daily_group"] == grp]
        p = _perf(d)
        p["group"] = grp
        topn_stats.append(p)
    compare = pd.DataFrame(topn_stats)[
        ["group", "n", "avg_ret_t1", "med_ret_t1", "win_t1", "avg_ret_t2", "med_ret_t2", "win_t2"]
    ]
    compare.to_csv(OUT_COMPARE, index=False, encoding="utf-8-sig")

    # top3 vs top4-5 (exclusive)
    top3 = base[base["daily_rank"] <= 3].copy()
    top45 = base[(base["daily_rank"] >= 4) & (base["daily_rank"] <= 5)].copy()
    top3_vs_45 = pd.DataFrame(
        [
            {"group": "top1_3", **_perf(top3)},
            {"group": "top4_5", **_perf(top45)},
        ]
    )[
        ["group", "n", "avg_ret_t1", "med_ret_t1", "win_t1", "avg_ret_t2", "med_ret_t2", "win_t2"]
    ]
    top3_vs_45.to_csv(OUT_TOP3_VS_45, index=False, encoding="utf-8-sig")

    # label split
    label_rows = []
    for grp in ["top1", "top2", "top3", "top5", "rank6_10"]:
        d = review[review["daily_group"] == grp]
        for lab in ["A", "C"]:
            sub = d[d["label_abc"] == lab]
            p = _perf(sub)
            p.update({"group": grp, "label_abc": lab})
            label_rows.append(p)
    by_label = pd.DataFrame(label_rows)[
        ["group", "label_abc", "n", "avg_ret_t1", "med_ret_t1", "win_t1", "avg_ret_t2", "med_ret_t2", "win_t2"]
    ]
    by_label.to_csv(OUT_BY_LABEL, index=False, encoding="utf-8-sig")

    # stability (daily top5)
    d5 = base[base["daily_rank"] <= 5].groupby("trade_date").agg(
        top5_avg_t1=("ret_close_t1", "mean"),
        top5_win_t1=("win_t1", "mean"),
    ).reset_index()
    d610 = base[(base["daily_rank"] >= 6) & (base["daily_rank"] <= 10)].groupby("trade_date").agg(
        rank6_10_avg_t1=("ret_close_t1", "mean")
    ).reset_index()
    st = d5.merge(d610, on="trade_date", how="left")
    pos_days = int((st["top5_avg_t1"] > 0).sum())
    win50_days = int((st["top5_win_t1"] > 0.5).sum())
    better_days = int((st["top5_avg_t1"] > st["rank6_10_avg_t1"]).sum())
    st.to_csv(OUT_STABILITY, index=False, encoding="utf-8-sig")

    summary = {
        "win_definition": {
            "primary": "win_t2 = (ret_close_t2 > 0)",
            "secondary": "win_t1 = (ret_close_t1 > 0)",
            "why_primary_t2": "top5 review shows better average signal persistence at T+2 than T+1",
            "why_secondary_t1": "kept as stricter immediate outcome check",
        },
        "window": {
            "start": str(base["trade_date"].min()) if len(base) else None,
            "end": str(base["trade_date"].max()) if len(base) else None,
            "days": int(base["trade_date"].nunique()),
        },
        "topn": compare.to_dict(orient="records"),
        "top3_vs_top4_5": top3_vs_45.to_dict(orient="records"),
        "stability": {
            "days_top5_avg_t1_positive": pos_days,
            "days_top5_win_t1_gt_50pct": win50_days,
            "days_top5_better_than_6_10_t1": better_days,
            "total_days": int(len(st)),
        },
    }
    OUT_SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    # simple conclusions
    c = compare.set_index("group")
    best_win_t2_group = c["win_t2"].astype(float).idxmax()
    best_win_t1_group = c["win_t1"].astype(float).idxmax()
    top5_better_t2 = float(c.loc["top5", "avg_ret_t2"]) > float(c.loc["rank6_10", "avg_ret_t2"])
    top3_vs_45_t2 = float(top3_vs_45.loc[top3_vs_45["group"] == "top1_3", "avg_ret_t2"].iloc[0]) > float(
        top3_vs_45.loc[top3_vs_45["group"] == "top4_5", "avg_ret_t2"].iloc[0]
    )

    review_md = [
        "# true_breakout_selector_topn_review",
        "",
        "## Win definitions",
        "- primary: win_t2 (T+2 close > buy_open_t1)",
        "- secondary: win_t1 (T+1 close > buy_open_t1)",
        "",
        "## TopN compare",
        compare.to_string(index=False),
        "",
        "## Top3 vs Top4~5",
        top3_vs_45.to_string(index=False),
        "",
        "## Stability",
        f"- days(top5 avg t1 > 0): {pos_days}/{len(st)}",
        f"- days(top5 win t1 > 50%): {win50_days}/{len(st)}",
        f"- days(top5 avg t1 > rank6_10): {better_days}/{len(st)}",
        "",
        "## Answers",
        f"- best group by win_t2: {best_win_t2_group}",
        f"- best group by win_t1: {best_win_t1_group}",
        f"- top5 better than rank6_10 on t2 avg: {top5_better_t2}",
        f"- top1_3 better than top4_5 on t2 avg: {top3_vs_45_t2}",
    ]
    OUT_REVIEW.write_text("\n".join(review_md), encoding="utf-8")

    print("Generated:")
    print(" -", OUT_MAIN)
    print(" -", OUT_SUMMARY)
    print(" -", OUT_COMPARE)
    print(" -", OUT_TOP3_VS_45)
    print(" -", OUT_BY_LABEL)
    print(" -", OUT_STABILITY)
    print(" -", OUT_REVIEW)


if __name__ == "__main__":
    main()
