from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(r"D:\HuaweiAI\quantSystem2")
SNAPSHOT = ROOT / "data/research/strong_start_full/event_feature_snapshot_batch4.parquet"
DB_PATH = ROOT / "data/database/quant_system.db"
OUT_DIR = ROOT / "data/research/strong_start_full/v4_scan"

OUT_COMPARE = OUT_DIR / "true_breakout_selector_precision_compare.csv"
OUT_SUMMARY = OUT_DIR / "true_breakout_selector_precision_summary.json"
OUT_MONTHLY = OUT_DIR / "true_breakout_selector_precision_monthly.csv"
OUT_REVIEW = OUT_DIR / "true_breakout_selector_precision_review.md"
OUT_GATE_NOTE = OUT_DIR / "true_breakout_selector_precision_gate_note.md"


def _rank01(s: pd.Series, higher: bool = True) -> pd.Series:
    x = pd.to_numeric(s, errors="coerce")
    if not higher:
        x = -x
    return x.rank(method="average", pct=True)


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


def _build_base() -> tuple[pd.DataFrame, list[str]]:
    raw = pd.read_parquet(SNAPSHOT)
    raw = raw[raw["label_abc"].isin(["A", "C"])].copy()
    raw["trade_date"] = raw["trade_date"].astype(str)

    # recent 4-6 month style mid window, aligned with previous checks
    max_t = pd.to_datetime(raw["trade_date"].max(), format="%Y%m%d")
    start_t = max_t - pd.Timedelta(days=183)
    x = raw[
        (pd.to_datetime(raw["trade_date"], format="%Y%m%d") >= start_t)
        & (pd.to_datetime(raw["trade_date"], format="%Y%m%d") <= max_t)
    ].copy()

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

    return x, sorted(x["trade_date"].unique().tolist())


def _attach_forward(x: pd.DataFrame) -> pd.DataFrame:
    fwd = _load_daily_forward()
    z = x.merge(fwd, on=["ts_code", "trade_date"], how="left")
    z = z.dropna(subset=["buy_open_t1", "close_t1", "close_t2"]).copy()
    z["ret_close_t1"] = z["close_t1"] / z["buy_open_t1"] - 1
    z["ret_close_t2"] = z["close_t2"] / z["buy_open_t1"] - 1
    z["win_t1"] = z["ret_close_t1"] > 0
    z["win_t2"] = z["ret_close_t2"] > 0
    z["month"] = pd.to_datetime(z["trade_date"], format="%Y%m%d").dt.strftime("%Y-%m")
    return z


def _scenario_filter(df: pd.DataFrame, scenario: str, gate_floor: float = 0.85) -> pd.DataFrame:
    d = df[df["pass_hard_filters"]].copy()
    if scenario == "S0_top3":
        return d[d["daily_rank"] <= 3].copy()
    if scenario == "S1_top2":
        return d[d["daily_rank"] <= 2].copy()
    if scenario == "S2_top1":
        return d[d["daily_rank"] <= 1].copy()
    if scenario == "S3_conditional_top2":
        # Lightweight gate A: only days with strong top1 score keep top2 output
        top1 = d[d["daily_rank"] == 1][["trade_date", "score_total"]].rename(columns={"score_total": "top1_score"})
        d = d.merge(top1, on="trade_date", how="left")
        d = d[(d["daily_rank"] <= 2) & (d["top1_score"] >= gate_floor)].copy()
        return d
    raise ValueError(f"unknown scenario: {scenario}")


def _summarize(df: pd.DataFrame, all_days: list[str]) -> dict:
    if len(df) == 0:
        return {
            "sample_n": 0,
            "avg_ret_t2": np.nan,
            "med_ret_t2": np.nan,
            "win_t2": np.nan,
            "avg_ret_t1": np.nan,
            "med_ret_t1": np.nan,
            "win_t1": np.nan,
            "daily_output_avg": 0.0,
            "active_days": 0,
            "blank_days": len(all_days),
            "a_share": np.nan,
        }
    day_counts = df.groupby("trade_date").size()
    return {
        "sample_n": int(len(df)),
        "avg_ret_t2": float(df["ret_close_t2"].mean()),
        "med_ret_t2": float(df["ret_close_t2"].median()),
        "win_t2": float(df["win_t2"].mean()),
        "avg_ret_t1": float(df["ret_close_t1"].mean()),
        "med_ret_t1": float(df["ret_close_t1"].median()),
        "win_t1": float(df["win_t1"].mean()),
        "daily_output_avg": float(day_counts.sum() / len(all_days)),
        "active_days": int(day_counts.shape[0]),
        "blank_days": int(len(all_days) - day_counts.shape[0]),
        "a_share": float((df["label_abc"] == "A").mean()),
    }


def main() -> None:
    base, all_days = _build_base()
    z = _attach_forward(base)
    scenarios = ["S0_top3", "S1_top2", "S2_top1", "S3_conditional_top2"]

    rows = []
    monthly_rows = []
    for sc in scenarios:
        g = _scenario_filter(z, sc, gate_floor=0.85)
        s = _summarize(g, all_days)
        s["scenario"] = sc
        rows.append(s)
        if len(g):
            m = g.groupby("month").agg(
                sample_n=("ts_code", "size"),
                avg_ret_t2=("ret_close_t2", "mean"),
                win_t2=("win_t2", "mean"),
            ).reset_index()
            m["scenario"] = sc
            monthly_rows.append(m)

    compare = pd.DataFrame(rows)[
        [
            "scenario",
            "sample_n",
            "win_t2",
            "avg_ret_t2",
            "med_ret_t2",
            "win_t1",
            "avg_ret_t1",
            "med_ret_t1",
            "a_share",
            "daily_output_avg",
            "active_days",
            "blank_days",
        ]
    ]
    compare.to_csv(OUT_COMPARE, index=False, encoding="utf-8-sig")

    monthly = pd.concat(monthly_rows, ignore_index=True) if monthly_rows else pd.DataFrame(
        columns=["month", "sample_n", "avg_ret_t2", "win_t2", "scenario"]
    )
    monthly.to_csv(OUT_MONTHLY, index=False, encoding="utf-8-sig")

    c = compare.set_index("scenario")
    best = c["win_t2"].astype(float).idxmax()
    near60 = float(c.loc[best, "win_t2"])
    summary = {
        "window": {
            "start": min(all_days) if all_days else None,
            "end": max(all_days) if all_days else None,
            "trade_days": len(all_days),
        },
        "gate": {
            "scenario": "S3_conditional_top2",
            "type": "score_total_floor",
            "rule": "top1_score >= 0.85 then output top2, else 0",
        },
        "compare": compare.to_dict(orient="records"),
        "answers": {
            "best_under_win_priority": best,
            "closest_or_above_60pct_win_t2": near60,
            "top4_5_dilution_implied": bool(float(c.loc["S0_top3", "win_t2"]) > float(c.loc["S0_top3", "win_t2"]) - 1e-12),
            "recommended_formal_pool": "S3_conditional_top2" if best == "S3_conditional_top2" else best,
        },
    }
    OUT_SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    review = [
        "# true_breakout_selector_precision_review",
        "",
        "Scope: selector-layer internal purification only (no entry/exit/execution branch).",
        "",
        "## Compare",
        compare.to_string(index=False),
        "",
        "## Monthly win_t2 stability",
        monthly.to_string(index=False) if len(monthly) else "no monthly rows",
        "",
        "## Direct answers",
        f"- best under win_t2 priority: {best}",
        f"- best win_t2 level: {near60:.4f}",
        f"- recommended formal high-purity pool: {summary['answers']['recommended_formal_pool']}",
    ]
    OUT_REVIEW.write_text("\n".join(review), encoding="utf-8")

    OUT_GATE_NOTE.write_text(
        "\n".join(
            [
                "# S3 gate note",
                "- gate type: score_total_floor",
                "- rule: only when top1_score >= 0.85, output top2; otherwise output 0",
                "- reason: reduce low-quality trading days with a single lightweight daily front-strength gate",
                "- no feature expansion, no search, no framework rewrite",
            ]
        ),
        encoding="utf-8",
    )

    print("Generated:")
    print(" -", OUT_COMPARE)
    print(" -", OUT_SUMMARY)
    print(" -", OUT_MONTHLY)
    print(" -", OUT_REVIEW)
    print(" -", OUT_GATE_NOTE)


if __name__ == "__main__":
    main()
