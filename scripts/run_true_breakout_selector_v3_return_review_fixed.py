from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(r"D:\HuaweiAI\quantSystem2")
BASE = ROOT / "data/research/strong_start_full/v4_scan"
SNAPSHOT = BASE / "true_breakout_feature_snapshot_1y.parquet"
DB_PATH = ROOT / "data/database/quant_system.db"

OUT_MAIN = BASE / "true_breakout_selector_v3_return_review_main.csv"
OUT_CONFIRM = BASE / "true_breakout_selector_v3_return_review_confirm.csv"
OUT_BY_PATH = BASE / "true_breakout_selector_v3_return_by_path.csv"
OUT_BY_TOPN = BASE / "true_breakout_selector_v3_return_by_topn.csv"
OUT_REVIEW = BASE / "true_breakout_selector_v3_return_review.md"
OUT_SUMMARY = BASE / "true_breakout_selector_v3_return_summary.json"

MAIN_START = "20251230"
MAIN_END = "20260330"
CONFIRM_START = "20250929"
CONFIRM_END = "20251229"

# frozen candidate-2 params
QUOTA_A = 1
QUOTA_B = 2
CUTOFF_A = 0.10
CUTOFF_B = 0.20
HEAT_TREND_Q = 0.85
HEAT_IND_Q = 0.85
HEAT_SCORE_CAP = 0.80
HEAT_PENALTY = 0.12


def _rank01(s: pd.Series, higher: bool = True) -> pd.Series:
    x = pd.to_numeric(s, errors="coerce")
    if not higher:
        x = -x
    return x.rank(method="average", pct=True)


def _rank_within_day(mask: pd.Series, score: pd.Series, trade_date: pd.Series) -> pd.Series:
    out = pd.Series(np.nan, index=score.index)
    for d in trade_date[mask].unique():
        idx = trade_date.index[(trade_date == d) & mask]
        out.loc[idx] = score.loc[idx].rank(method="first", ascending=False, pct=True)
    return out


def _load_forward_from_daily() -> pd.DataFrame:
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
    daily["close_t3"] = daily.groupby("ts_code")["close"].shift(-3)
    return daily[["ts_code", "trade_date", "buy_date", "buy_open_t1", "close_t1", "close_t2", "close_t3"]]


def _build_selected_events(df: pd.DataFrame, start: str, end: str) -> pd.DataFrame:
    d = df.copy()
    d["trade_date"] = d["trade_date"].astype(str)
    d = d[(d["trade_date"] >= start) & (d["trade_date"] <= end)].copy()

    # path A
    pass_a = (
        (pd.to_numeric(d["f_strength_rs20_xsec_q"], errors="coerce") >= 0.72)
        & (pd.to_numeric(d["f_trend_close_ma20_gap"], errors="coerce") >= 0.02)
    )
    a_trend = _rank01(d["f_strength_rs20_xsec_q"], True).clip(upper=0.90)
    a_ind = _rank01(d["f_ind_peer_strong_count"], True)
    a_chip = _rank01(d["f_chip_winner_rate"], True)
    score_a = 0.65 * a_trend + 0.20 * a_ind + 0.15 * a_chip
    heat_res = (a_trend >= HEAT_TREND_Q) & (a_ind >= HEAT_IND_Q)
    score_a = score_a.copy()
    score_a.loc[heat_res] = np.minimum(score_a.loc[heat_res], HEAT_SCORE_CAP) - HEAT_PENALTY
    rank_a = _rank_within_day(pass_a, score_a, d["trade_date"])

    # path B
    pass_b = (
        (pd.to_numeric(d["f_strength_rs20_xsec_q"], errors="coerce") >= 0.60)
        & (pd.to_numeric(d["f_trend_close_ma20_gap"], errors="coerce") >= 0.00)
    )
    score_b = 0.50 * (
        0.70 * _rank01(d["f_platform_compress_ratio"], False) + 0.30 * _rank01(d["f_platform_range30"], False)
    ) + 0.40 * (
        0.60 * _rank01(d["f_chip_winner_rate"], True) + 0.40 * _rank01(d["f_chip_low_position120"], True)
    ) + 0.10 * _rank01(d["f_strength_rs20_xsec_q"], True)
    rank_b = _rank_within_day(pass_b, score_b, d["trade_date"])

    d["path_a_pass"] = pass_a & (rank_a <= CUTOFF_A)
    d["path_b_pass"] = pass_b & (rank_b <= CUTOFF_B)
    d["rank_a"] = rank_a
    d["rank_b"] = rank_b
    d["score_a"] = score_a
    d["score_b"] = score_b
    d["selected"] = False
    d["path_source_raw"] = ""

    for trade_date, g in d.groupby("trade_date"):
        idx_a = g.index[d.loc[g.index, "path_a_pass"]]
        idx_b = g.index[d.loc[g.index, "path_b_pass"]]
        pick_a = d.loc[idx_a].sort_values("rank_a", ascending=True).head(QUOTA_A).index
        pick_b = d.loc[idx_b].sort_values("rank_b", ascending=True).head(QUOTA_B).index
        picks = pick_a.union(pick_b)
        d.loc[picks, "selected"] = True
        d.loc[pick_a, "path_source_raw"] = "A"
        b_only = [x for x in pick_b if x not in set(pick_a)]
        d.loc[b_only, "path_source_raw"] = "B"
        both = [x for x in pick_b if x in set(pick_a)]
        if both:
            # tie-break for both-selected names
            for idx in both:
                ra = d.at[idx, "rank_a"]
                rb = d.at[idx, "rank_b"]
                d.at[idx, "path_source_raw"] = "A" if (pd.notna(ra) and (pd.isna(rb) or ra <= rb)) else "B"

    out = d[d["selected"]].copy()
    out["score_total"] = np.where(out["path_source_raw"] == "A", out["score_a"], out["score_b"])
    out["path_source"] = out["path_source_raw"].replace("", np.nan).fillna("B")

    out["rank_global_after_merge"] = np.nan
    for td, g in out.groupby("trade_date"):
        out.loc[g.index, "rank_global_after_merge"] = g["score_total"].rank(method="first", ascending=False).astype(int)
    out["rank_global_after_merge"] = out["rank_global_after_merge"].astype(int)
    return out


def _attach_returns(selected_df: pd.DataFrame, fwd: pd.DataFrame) -> pd.DataFrame:
    x = selected_df.merge(fwd, on=["ts_code", "trade_date"], how="left")
    x = x.dropna(subset=["buy_open_t1", "close_t1", "close_t2", "close_t3"]).copy()
    x["ret_t1"] = x["close_t1"] / x["buy_open_t1"] - 1
    x["ret_t2"] = x["close_t2"] / x["buy_open_t1"] - 1
    x["ret_t3"] = x["close_t3"] / x["buy_open_t1"] - 1
    x["win_t1"] = x["ret_t1"] > 0
    x["win_t2"] = x["ret_t2"] > 0
    x["win_t3"] = x["ret_t3"] > 0
    x["rank_bucket"] = np.select(
        [
            x["rank_global_after_merge"] <= 1,
            x["rank_global_after_merge"] <= 2,
            x["rank_global_after_merge"] <= 3,
            x["rank_global_after_merge"] <= 5,
        ],
        ["top1", "top2", "top3", "top5"],
        default="other",
    )
    return x


def _agg_metrics(df: pd.DataFrame) -> dict:
    return {
        "sample_n": int(len(df)),
        "mean_ret_t1": float(df["ret_t1"].mean()) if len(df) else np.nan,
        "mean_ret_t2": float(df["ret_t2"].mean()) if len(df) else np.nan,
        "mean_ret_t3": float(df["ret_t3"].mean()) if len(df) else np.nan,
        "median_ret_t1": float(df["ret_t1"].median()) if len(df) else np.nan,
        "median_ret_t2": float(df["ret_t2"].median()) if len(df) else np.nan,
        "median_ret_t3": float(df["ret_t3"].median()) if len(df) else np.nan,
        "win_t1": float((df["ret_t1"] > 0).mean()) if len(df) else np.nan,
        "win_t2": float((df["ret_t2"] > 0).mean()) if len(df) else np.nan,
        "win_t3": float((df["ret_t3"] > 0).mean()) if len(df) else np.nan,
    }


def _by_group(df: pd.DataFrame, group_col: str, window_name: str) -> pd.DataFrame:
    rows = []
    for g, d in df.groupby(group_col):
        m = _agg_metrics(d)
        m.update({"window": window_name, "group": g})
        rows.append(m)
    return pd.DataFrame(rows)


def main() -> None:
    snap = pd.read_parquet(SNAPSHOT)
    snap["trade_date"] = snap["trade_date"].astype(str)
    # keep all labels if present, no filtering by label for selection output
    fwd = _load_forward_from_daily()

    main_sel = _build_selected_events(snap, MAIN_START, MAIN_END)
    main_ret = _attach_returns(main_sel, fwd)

    confirm_sel = _build_selected_events(snap, CONFIRM_START, CONFIRM_END)
    confirm_ret = _attach_returns(confirm_sel, fwd)

    keep_cols = [
        "ts_code",
        "trade_date",
        "name",
        "industry",
        "label_true_breakout",
        "path_source",
        "score_total",
        "rank_global_after_merge",
        "rank_bucket",
        "buy_date",
        "buy_open_t1",
        "close_t1",
        "close_t2",
        "close_t3",
        "ret_t1",
        "ret_t2",
        "ret_t3",
        "win_t1",
        "win_t2",
        "win_t3",
    ]
    main_ret[keep_cols].to_csv(OUT_MAIN, index=False, encoding="utf-8-sig")
    confirm_ret[keep_cols].to_csv(OUT_CONFIRM, index=False, encoding="utf-8-sig")

    by_path = pd.concat(
        [
            _by_group(main_ret, "path_source", "main"),
            _by_group(confirm_ret, "path_source", "confirm"),
        ],
        ignore_index=True,
    )
    by_path.to_csv(OUT_BY_PATH, index=False, encoding="utf-8-sig")

    # cumulative TopN groups (rank<=N), not mutually-exclusive buckets
    topn_rows = []
    for window_name, d in [("main", main_ret), ("confirm", confirm_ret)]:
        for n in [1, 2, 3, 5]:
            sub = d[d["rank_global_after_merge"] <= n]
            m = _agg_metrics(sub)
            m.update({"window": window_name, "group": f"top{n}"})
            topn_rows.append(m)
    by_topn = pd.DataFrame(topn_rows)
    by_topn.to_csv(OUT_BY_TOPN, index=False, encoding="utf-8-sig")

    overall_main = _agg_metrics(main_ret)
    overall_confirm = _agg_metrics(confirm_ret)
    summary = {
        "selector": "true_breakout_selector_v3_freeze_candidate_2",
        "params": {
            "quota_a": QUOTA_A,
            "quota_b": QUOTA_B,
            "heat_cap": "high",
            "path_a_cutoff": "top10%",
            "path_b_cutoff": "top20%",
        },
        "windows": {
            "main": {"start": MAIN_START, "end": MAIN_END, **overall_main},
            "confirm": {"start": CONFIRM_START, "end": CONFIRM_END, **overall_confirm},
        },
    }
    OUT_SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    best_h_main = max(
        [("T+1", overall_main["mean_ret_t1"]), ("T+2", overall_main["mean_ret_t2"]), ("T+3", overall_main["mean_ret_t3"])],
        key=lambda x: x[1],
    )[0]

    lines = [
        "# true_breakout_selector_v3_return_review",
        "",
        "## Fixed scope",
        "- selector: true_breakout_selector_v3_freeze_candidate_2",
        "- params: quota=1:2, heat-cap=high, pathA=Top10%, pathB=Top20%",
        "- entry: T+1 open; horizons: T+1/T+2/T+3 close",
        "",
        "## Main window",
        f"- {MAIN_START} ~ {MAIN_END}",
        f"- sample_n: {overall_main['sample_n']}",
        f"- mean_ret: t1={overall_main['mean_ret_t1']:.6f}, t2={overall_main['mean_ret_t2']:.6f}, t3={overall_main['mean_ret_t3']:.6f}",
        f"- median_ret: t1={overall_main['median_ret_t1']:.6f}, t2={overall_main['median_ret_t2']:.6f}, t3={overall_main['median_ret_t3']:.6f}",
        f"- win_rate: t1={overall_main['win_t1']:.4f}, t2={overall_main['win_t2']:.4f}, t3={overall_main['win_t3']:.4f}",
        "",
        "## Confirm window",
        f"- {CONFIRM_START} ~ {CONFIRM_END}",
        f"- sample_n: {overall_confirm['sample_n']}",
        f"- mean_ret: t1={overall_confirm['mean_ret_t1']:.6f}, t2={overall_confirm['mean_ret_t2']:.6f}, t3={overall_confirm['mean_ret_t3']:.6f}",
        f"- median_ret: t1={overall_confirm['median_ret_t1']:.6f}, t2={overall_confirm['median_ret_t2']:.6f}, t3={overall_confirm['median_ret_t3']:.6f}",
        f"- win_rate: t1={overall_confirm['win_t1']:.4f}, t2={overall_confirm['win_t2']:.4f}, t3={overall_confirm['win_t3']:.4f}",
        "",
        "## By path",
        by_path.to_string(index=False),
        "",
        "## By global rank bucket",
        by_topn.sort_values(["window", "group"]).to_string(index=False),
        "",
        f"## Main window best horizon: {best_h_main}",
    ]
    OUT_REVIEW.write_text("\n".join(lines), encoding="utf-8")

    print("Generated:")
    print(" -", OUT_MAIN)
    print(" -", OUT_CONFIRM)
    print(" -", OUT_BY_PATH)
    print(" -", OUT_BY_TOPN)
    print(" -", OUT_REVIEW)
    print(" -", OUT_SUMMARY)


if __name__ == "__main__":
    main()
