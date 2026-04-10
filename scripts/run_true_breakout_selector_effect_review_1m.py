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

OUT_MAIN = OUT_DIR / "true_breakout_selector_effect_review_1m.parquet"
OUT_SUMMARY = OUT_DIR / "true_breakout_selector_effect_summary_1m.json"
OUT_BY_RANK = OUT_DIR / "true_breakout_selector_effect_by_rank_1m.csv"
OUT_BY_LABEL = OUT_DIR / "true_breakout_selector_effect_by_label_1m.csv"
OUT_REVIEW = OUT_DIR / "true_breakout_selector_effect_review_1m.md"


def rank01(s: pd.Series, higher: bool = True) -> pd.Series:
    x = pd.to_numeric(s, errors="coerce")
    if not higher:
        x = -x
    return x.rank(method="average", pct=True)


def build_selector(df: pd.DataFrame) -> pd.DataFrame:
    x = df.copy()
    x["pass_hard_filters"] = (
        (x["f_trend_close_ma20_gap"] >= 0.02)
        & (x["f_strength_rs20_xsec_q"] >= 0.70)
        & (x["f_ind_rank_pctchg"] >= 0.80)
    )
    x["score_strength_axis"] = (
        rank01(x["f_strength_ret20"], True)
        + rank01(x["f_strength_ret60"], True)
        + rank01(x["f_trend_ma20_ma60_gap"], True)
    ) / 3.0
    x["score_industry_axis"] = (
        rank01(x["f_ind_strength_3d"], True)
        + rank01(x["f_ind_strength_5d"], True)
        + rank01(x["f_ind_rank_pctchg"], True)
    ) / 3.0
    x["score_chip_axis"] = (
        rank01(x["f_chip_concentration"], True)
        + rank01(x["f_chip_winner_rate"], True)
        + rank01(x["f_chip_stability_std10"], True)
    ) / 3.0
    x["score_platform_axis"] = (
        rank01(x["f_platform_range_best"], True)
        + rank01(x["f_platform_compress_ratio"], True)
    ) / 2.0
    x["score_total"] = (
        0.40 * x["score_strength_axis"]
        + 0.35 * x["score_industry_axis"]
        + 0.20 * x["score_chip_axis"]
        + 0.05 * x["score_platform_axis"]
    )

    x["rank_pct"] = np.nan
    x["rank_bucket"] = "other"
    for d, g in x[x["pass_hard_filters"]].groupby("trade_date"):
        pct = g["score_total"].rank(method="first", ascending=False, pct=True)
        x.loc[g.index, "rank_pct"] = pct
    x.loc[x["rank_pct"] <= 0.10, "rank_bucket"] = "top10"
    x.loc[(x["rank_pct"] > 0.10) & (x["rank_pct"] <= 0.20), "rank_bucket"] = "top20"
    x.loc[(x["rank_pct"] > 0.20) & (x["rank_pct"] <= 0.30), "rank_bucket"] = "top30"
    x["is_candidate"] = x["pass_hard_filters"] & (x["rank_pct"] <= 0.30)
    x["selector_reject_reason"] = ""
    x.loc[x["f_trend_close_ma20_gap"].isna() | (x["f_trend_close_ma20_gap"] < 0.02), "selector_reject_reason"] += "trend_gap_below_floor|"
    x.loc[x["f_strength_rs20_xsec_q"].isna() | (x["f_strength_rs20_xsec_q"] < 0.70), "selector_reject_reason"] += "rs20_q_below_floor|"
    x.loc[x["f_ind_rank_pctchg"].isna() | (x["f_ind_rank_pctchg"] < 0.80), "selector_reject_reason"] += "industry_rank_too_weak|"
    x["selector_reject_reason"] = x["selector_reject_reason"].str.rstrip("|")
    x["selector_explain"] = (
        "hf="
        + x["pass_hard_filters"].astype(str)
        + ";score="
        + x["score_total"].round(4).astype(str)
        + ";bucket="
        + x["rank_bucket"].astype(str)
    )
    return x


def load_daily_with_forward() -> pd.DataFrame:
    conn = sqlite3.connect(DB_PATH)
    try:
        daily = pd.read_sql_query(
            "select ts_code, trade_date, open, close from stock_daily",
            conn,
        )
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


def summary_stats(df: pd.DataFrame, col: str) -> dict:
    s = pd.to_numeric(df[col], errors="coerce").dropna()
    if len(s) == 0:
        return {"n": 0, "avg": None, "median": None, "win_rate": None}
    return {
        "n": int(len(s)),
        "avg": float(s.mean()),
        "median": float(s.median()),
        "win_rate": float((s > 0).mean()),
    }


def grouped_stats(df: pd.DataFrame, group_col: str) -> pd.DataFrame:
    rows = []
    for g, d in df.groupby(group_col):
        rows.append(
            {
                "group": g,
                "n": int(len(d)),
                "avg_ret_t1": float(d["ret_close_t1"].mean()) if len(d) else np.nan,
                "med_ret_t1": float(d["ret_close_t1"].median()) if len(d) else np.nan,
                "win_t1": float((d["ret_close_t1"] > 0).mean()) if len(d) else np.nan,
                "avg_ret_t2": float(d["ret_close_t2"].mean()) if len(d) else np.nan,
                "med_ret_t2": float(d["ret_close_t2"].median()) if len(d) else np.nan,
                "win_t2": float((d["ret_close_t2"] > 0).mean()) if len(d) else np.nan,
                "avg_ret_t3": float(d["ret_close_t3"].mean()) if len(d) else np.nan,
                "med_ret_t3": float(d["ret_close_t3"].median()) if len(d) else np.nan,
                "win_t3": float((d["ret_close_t3"] > 0).mean()) if len(d) else np.nan,
            }
        )
    return pd.DataFrame(rows)


def main() -> None:
    data = pd.read_parquet(SNAPSHOT)
    data["trade_date"] = data["trade_date"].astype(str)
    data = data[data["label_abc"].isin(["A", "C"])].copy()
    data = build_selector(data)
    candidates = data[data["is_candidate"]].copy()

    # recent one-month window from latest available candidate trade_date,
    # truncated to keep full T+3 observability
    max_t = pd.to_datetime(candidates["trade_date"].max(), format="%Y%m%d")
    start_t = max_t - pd.Timedelta(days=31)
    candidates = candidates[
        (pd.to_datetime(candidates["trade_date"], format="%Y%m%d") >= start_t)
        & (pd.to_datetime(candidates["trade_date"], format="%Y%m%d") <= max_t)
    ].copy()

    fwd = load_daily_with_forward()
    main = candidates.merge(
        fwd, on=["ts_code", "trade_date"], how="left"
    )
    # ensure full T+3
    main = main.dropna(subset=["buy_open_t1", "close_t1", "close_t2", "close_t3"]).copy()

    main["ret_close_t1"] = main["close_t1"] / main["buy_open_t1"] - 1
    main["ret_close_t2"] = main["close_t2"] / main["buy_open_t1"] - 1
    main["ret_close_t3"] = main["close_t3"] / main["buy_open_t1"] - 1
    main["win_t1"] = main["ret_close_t1"] > 0
    main["win_t2"] = main["ret_close_t2"] > 0
    main["win_t3"] = main["ret_close_t3"] > 0

    out_cols = [
        "ts_code",
        "trade_date",
        "score_total",
        "rank_pct",
        "rank_bucket",
        "is_candidate",
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
    main[out_cols].to_parquet(OUT_MAIN, index=False)

    summary = {
        "window": {
            "start": str(main["trade_date"].min()) if len(main) else None,
            "end": str(main["trade_date"].max()) if len(main) else None,
            "sample_count": int(len(main)),
        },
        "overall": {
            "t1": summary_stats(main, "ret_close_t1"),
            "t2": summary_stats(main, "ret_close_t2"),
            "t3": summary_stats(main, "ret_close_t3"),
        },
    }
    OUT_SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    # rank grouping as cumulative Top10/20/30
    by_rank_rows = []
    for n, p in [("top10", 0.10), ("top20", 0.20), ("top30", 0.30)]:
        sub = main[main["rank_pct"] <= p].copy()
        if len(sub) == 0:
            by_rank_rows.append(
                {"rank_group": n, "n": 0, "avg_ret_t1": np.nan, "med_ret_t1": np.nan, "win_t1": np.nan,
                 "avg_ret_t2": np.nan, "med_ret_t2": np.nan, "win_t2": np.nan,
                 "avg_ret_t3": np.nan, "med_ret_t3": np.nan, "win_t3": np.nan}
            )
            continue
        by_rank_rows.append(
            {
                "rank_group": n,
                "n": int(len(sub)),
                "avg_ret_t1": float(sub["ret_close_t1"].mean()),
                "med_ret_t1": float(sub["ret_close_t1"].median()),
                "win_t1": float((sub["ret_close_t1"] > 0).mean()),
                "avg_ret_t2": float(sub["ret_close_t2"].mean()),
                "med_ret_t2": float(sub["ret_close_t2"].median()),
                "win_t2": float((sub["ret_close_t2"] > 0).mean()),
                "avg_ret_t3": float(sub["ret_close_t3"].mean()),
                "med_ret_t3": float(sub["ret_close_t3"].median()),
                "win_t3": float((sub["ret_close_t3"] > 0).mean()),
            }
        )
    by_rank = pd.DataFrame(by_rank_rows)
    by_rank.to_csv(OUT_BY_RANK, index=False, encoding="utf-8-sig")

    by_label = grouped_stats(main, "label_abc")
    by_label.to_csv(OUT_BY_LABEL, index=False, encoding="utf-8-sig")

    # two judgments
    # 1) direction judgement
    if len(by_rank) and by_rank.loc[by_rank["rank_group"] == "top10", "avg_ret_t1"].iloc[0] > by_rank.loc[by_rank["rank_group"] == "top30", "avg_ret_t1"].iloc[0]:
        j1 = "只有最前排分组有效"
    elif summary["overall"]["t1"]["avg"] is not None and summary["overall"]["t1"]["avg"] > 0:
        j1 = "选股方向对，但买点粗糙"
    elif summary["overall"]["t3"]["avg"] is not None and summary["overall"]["t3"]["avg"] > summary["overall"]["t1"]["avg"]:
        j1 = "选股本身一般"
    else:
        j1 = "整体都偏弱"

    # 2) holding horizon hint by avg return
    means = {
        "T+1": summary["overall"]["t1"]["avg"] if summary["overall"]["t1"]["avg"] is not None else -999,
        "T+2": summary["overall"]["t2"]["avg"] if summary["overall"]["t2"]["avg"] is not None else -999,
        "T+3": summary["overall"]["t3"]["avg"] if summary["overall"]["t3"]["avg"] is not None else -999,
    }
    best_h = max(means, key=means.get)
    if best_h == "T+1":
        j2 = "次日开盘后短持"
    elif best_h == "T+2":
        j2 = "持有到 T+2"
    else:
        j2 = "持有到 T+3"

    review = [
        "# true_breakout_selector_effect_review_1m",
        "",
        "## Window",
        f"- trade_date window: {summary['window']['start']} ~ {summary['window']['end']}",
        f"- sample count: {summary['window']['sample_count']}",
        "",
        "## Overall (T+1/T+2/T+3)",
        f"- T+1: {summary['overall']['t1']}",
        f"- T+2: {summary['overall']['t2']}",
        f"- T+3: {summary['overall']['t3']}",
        "",
        "## By rank (Top10/20/30)",
        by_rank.to_string(index=False),
        "",
        "## By label (A/C)",
        by_label.to_string(index=False),
        "",
        "## Judgments",
        f"- judgment_1: {j1}",
        f"- judgment_2: {j2}",
    ]
    OUT_REVIEW.write_text("\n".join(review), encoding="utf-8")

    print("Generated:")
    print(" -", OUT_MAIN)
    print(" -", OUT_SUMMARY)
    print(" -", OUT_BY_RANK)
    print(" -", OUT_BY_LABEL)
    print(" -", OUT_REVIEW)


if __name__ == "__main__":
    main()

