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

OUT_MAIN = OUT_DIR / "true_breakout_selector_effect_review_mid.parquet"
OUT_SUMMARY = OUT_DIR / "true_breakout_selector_effect_summary_mid.json"
OUT_BY_RANK = OUT_DIR / "true_breakout_selector_effect_by_rank_mid.csv"
OUT_BY_MONTH = OUT_DIR / "true_breakout_selector_effect_by_month_mid.csv"
OUT_BY_LABEL = OUT_DIR / "true_breakout_selector_effect_by_label_mid.csv"
OUT_REVIEW = OUT_DIR / "true_breakout_selector_effect_review_mid.md"


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
    for d, g in x[x["pass_hard_filters"]].groupby("trade_date"):
        x.loc[g.index, "rank_pct"] = g["score_total"].rank(method="first", ascending=False, pct=True)
    x["rank_bucket"] = "other"
    x.loc[x["rank_pct"] <= 0.10, "rank_bucket"] = "top10"
    x.loc[(x["rank_pct"] > 0.10) & (x["rank_pct"] <= 0.20), "rank_bucket"] = "top20"
    x.loc[(x["rank_pct"] > 0.20) & (x["rank_pct"] <= 0.30), "rank_bucket"] = "top30"
    x["is_candidate"] = x["pass_hard_filters"] & (x["rank_pct"] <= 0.30)
    return x


def load_daily_forward() -> pd.DataFrame:
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


def stats_block(df: pd.DataFrame, col: str) -> dict:
    s = pd.to_numeric(df[col], errors="coerce").dropna()
    if len(s) == 0:
        return {"n": 0, "avg": None, "median": None, "win_rate": None}
    return {"n": int(len(s)), "avg": float(s.mean()), "median": float(s.median()), "win_rate": float((s > 0).mean())}


def by_group(df: pd.DataFrame, group_col: str) -> pd.DataFrame:
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
    raw = pd.read_parquet(SNAPSHOT)
    raw["trade_date"] = raw["trade_date"].astype(str)
    raw = raw[raw["label_abc"].isin(["A", "C"])].copy()
    x = build_selector(raw)
    cand = x[x["is_candidate"]].copy()

    # recent 6 months window (within required 4~6 months)
    max_t = pd.to_datetime(cand["trade_date"].max(), format="%Y%m%d")
    start_t = max_t - pd.Timedelta(days=183)
    cand = cand[
        (pd.to_datetime(cand["trade_date"], format="%Y%m%d") >= start_t)
        & (pd.to_datetime(cand["trade_date"], format="%Y%m%d") <= max_t)
    ].copy()

    fwd = load_daily_forward()
    main = cand.merge(fwd, on=["ts_code", "trade_date"], how="left")
    main = main.dropna(subset=["buy_open_t1", "close_t1", "close_t2", "close_t3"]).copy()
    main["ret_close_t1"] = main["close_t1"] / main["buy_open_t1"] - 1
    main["ret_close_t2"] = main["close_t2"] / main["buy_open_t1"] - 1
    main["ret_close_t3"] = main["close_t3"] / main["buy_open_t1"] - 1
    main["win_t1"] = main["ret_close_t1"] > 0
    main["win_t2"] = main["ret_close_t2"] > 0
    main["win_t3"] = main["ret_close_t3"] > 0
    main["month"] = pd.to_datetime(main["trade_date"], format="%Y%m%d").dt.to_period("M").astype(str)

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
        "month",
    ]
    main[out_cols].to_parquet(OUT_MAIN, index=False)

    overall = {
        "t1": stats_block(main, "ret_close_t1"),
        "t2": stats_block(main, "ret_close_t2"),
        "t3": stats_block(main, "ret_close_t3"),
    }

    by_rank_rows = []
    for name, p in [("top10", 0.10), ("top20", 0.20), ("top30", 0.30)]:
        sub = main[main["rank_pct"] <= p]
        by_rank_rows.append(
            {
                "rank_group": name,
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
    by_rank = pd.DataFrame(by_rank_rows)
    by_rank.to_csv(OUT_BY_RANK, index=False, encoding="utf-8-sig")

    # month x rank groups
    month_rows = []
    for (m, rg), d in main.assign(
        rank_group=np.select(
            [main["rank_pct"] <= 0.10, main["rank_pct"] <= 0.20, main["rank_pct"] <= 0.30],
            ["top10", "top20", "top30"],
            default="other",
        )
    ).query("rank_group in ['top10','top20','top30']").groupby(["month", "rank_group"]):
        month_rows.append(
            {
                "month": m,
                "rank_group": rg,
                "n": int(len(d)),
                "avg_ret_t1": float(d["ret_close_t1"].mean()),
                "win_t1": float((d["ret_close_t1"] > 0).mean()),
                "avg_ret_t2": float(d["ret_close_t2"].mean()),
                "win_t2": float((d["ret_close_t2"] > 0).mean()),
                "avg_ret_t3": float(d["ret_close_t3"].mean()),
                "win_t3": float((d["ret_close_t3"] > 0).mean()),
            }
        )
    by_month = pd.DataFrame(month_rows).sort_values(["month", "rank_group"])
    by_month.to_csv(OUT_BY_MONTH, index=False, encoding="utf-8-sig")

    by_label = by_group(main, "label_abc")
    by_label.to_csv(OUT_BY_LABEL, index=False, encoding="utf-8-sig")

    summary = {
        "window": {
            "start": str(main["trade_date"].min()) if len(main) else None,
            "end": str(main["trade_date"].max()) if len(main) else None,
            "months": sorted(main["month"].dropna().unique().tolist()),
            "sample_count": int(len(main)),
        },
        "overall": overall,
    }
    OUT_SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    # 3 direct questions helper
    top10 = by_rank[by_rank["rank_group"] == "top10"].iloc[0]
    top20 = by_rank[by_rank["rank_group"] == "top20"].iloc[0]
    top30 = by_rank[by_rank["rank_group"] == "top30"].iloc[0]
    top10_strong = (top10["avg_ret_t1"] >= top20["avg_ret_t1"]) and (top10["avg_ret_t1"] >= top30["avg_ret_t1"])
    monotonic_t1 = top10["avg_ret_t1"] >= top20["avg_ret_t1"] >= top30["avg_ret_t1"]
    best_h = max({"T+1": overall["t1"]["avg"], "T+2": overall["t2"]["avg"], "T+3": overall["t3"]["avg"]}, key=lambda k: -999 if overall[k.replace('+','').lower() if False else "t1"] is None else {"T+1": overall["t1"]["avg"], "T+2": overall["t2"]["avg"], "T+3": overall["t3"]["avg"]}[k])

    # safe best horizon
    means = {"T+1": overall["t1"]["avg"], "T+2": overall["t2"]["avg"], "T+3": overall["t3"]["avg"]}
    means = {k: (-999 if v is None else v) for k, v in means.items()}
    best_h = max(means, key=means.get)

    review = [
        "# true_breakout_selector_effect_review_mid",
        "",
        f"- window: {summary['window']['start']} ~ {summary['window']['end']}",
        f"- months: {', '.join(summary['window']['months'])}",
        f"- sample_count: {summary['window']['sample_count']}",
        "",
        "## overall",
        f"- T+1: {overall['t1']}",
        f"- T+2: {overall['t2']}",
        f"- T+3: {overall['t3']}",
        "",
        "## by rank",
        by_rank.to_string(index=False),
        "",
        "## by month",
        by_month.to_string(index=False),
        "",
        "## by label",
        by_label.to_string(index=False),
        "",
        "## answers",
        f"- q1_top10_strong: {top10_strong}",
        f"- q2_monotonic_top10_top20_top30_t1: {monotonic_t1}",
        f"- q3_positioning_front_only: {'yes' if top10_strong else 'no'}",
        f"- horizon_hint: {best_h}",
    ]
    OUT_REVIEW.write_text("\n".join(review), encoding="utf-8")

    print("Generated:")
    print(" -", OUT_MAIN)
    print(" -", OUT_SUMMARY)
    print(" -", OUT_BY_RANK)
    print(" -", OUT_BY_MONTH)
    print(" -", OUT_BY_LABEL)
    print(" -", OUT_REVIEW)


if __name__ == "__main__":
    main()

