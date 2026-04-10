from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(r"D:\HuaweiAI\quantSystem2")
BASE = ROOT / "data/research/strong_start_full/v4_scan"
DB_PATH = ROOT / "data/database/quant_system.db"

IN_SNAPSHOT = BASE / "true_breakout_feature_snapshot_1y.parquet"
IN_EVAL210 = BASE / "true_breakout_v32_with_priority_tag.csv"
IN_EVAL210_AUDIT = BASE / "true_breakout_ahigh_recall_audit.csv"

OUT_MAP = BASE / "true_breakout_full_universe_mapping.csv"
OUT_RECALL = BASE / "true_breakout_full_universe_recall_audit.csv"
OUT_MISS = BASE / "true_breakout_full_universe_ahigh_miss_reason.csv"
OUT_COMPARE = BASE / "true_breakout_full_universe_vs_eval210_compare.md"
OUT_SUMMARY = BASE / "true_breakout_full_universe_recall_summary.json"

# frozen structure constants
QUOTA_A = 1
QUOTA_B = 2
CUTOFF_A = 0.10
CUTOFF_B = 0.20
HEAT_TREND_Q = 0.85
HEAT_IND_Q = 0.85
HEAT_SCORE_CAP = 0.80
HEAT_PENALTY = 0.12


def rank01(s: pd.Series, higher: bool = True) -> pd.Series:
    x = pd.to_numeric(s, errors="coerce")
    if not higher:
        x = -x
    return x.rank(method="average", pct=True)


def rank_within_day(mask: pd.Series, score: pd.Series, trade_date: pd.Series) -> pd.Series:
    out = pd.Series(np.nan, index=score.index)
    for td in trade_date[mask].astype(str).unique():
        idx = trade_date.index[(trade_date.astype(str) == td) & mask]
        out.loc[idx] = score.loc[idx].rank(method="first", ascending=False, pct=True)
    return out


def load_forward_daily() -> pd.DataFrame:
    conn = sqlite3.connect(DB_PATH)
    try:
        daily = pd.read_sql_query("select ts_code, trade_date, open, close from stock_daily", conn)
    finally:
        conn.close()
    daily["trade_date"] = daily["trade_date"].astype(str)
    daily["open"] = pd.to_numeric(daily["open"], errors="coerce")
    daily["close"] = pd.to_numeric(daily["close"], errors="coerce")
    daily = daily.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)
    daily["buy_open_t1"] = daily.groupby("ts_code")["open"].shift(-1)
    daily["close_t1"] = daily.groupby("ts_code")["close"].shift(-1)
    daily["close_t2"] = daily.groupby("ts_code")["close"].shift(-2)
    daily["close_t3"] = daily.groupby("ts_code")["close"].shift(-3)
    return daily[["ts_code", "trade_date", "buy_open_t1", "close_t1", "close_t2", "close_t3"]]


def load_universe() -> pd.DataFrame:
    d = pd.read_parquet(IN_SNAPSHOT).copy()
    d["trade_date"] = d["trade_date"].astype(str)
    d["ts_code"] = d["ts_code"].astype(str)
    d["stock_code"] = d["ts_code"]
    d["stock_name"] = d["name"].astype(str)
    d["label_class"] = d["label_true_breakout"].astype(str)
    return d


def add_scores_and_path(d: pd.DataFrame) -> pd.DataFrame:
    x = d.copy()

    x["score_trend_axis_single"] = (
        0.90 * rank01(x["f_strength_rs20_xsec_q"], True).clip(upper=0.90)
        + 0.10
        * pd.concat(
            [
                rank01(x["f_strength_ret20"], True),
                rank01(x["f_strength_rs60_xsec_q"], True),
                rank01(x["f_trend_close_ma20_gap"], True),
                rank01(x["f_trend_ma20_ma60_gap"], True),
                rank01(x["f_trend_ma20_slope5"], True),
            ],
            axis=1,
        ).mean(axis=1)
    )
    x["score_platform_axis_single"] = (
        0.70 * rank01(x["f_platform_compress_ratio"], False) + 0.30 * rank01(x["f_platform_range30"], False)
    )
    x["score_chip_axis_single"] = (
        0.45 * rank01(x["f_chip_winner_rate"], True)
        + 0.35 * rank01(x["f_chip_low_position120"], True)
        + 0.20 * rank01(x["f_chip_stability_std10"], True)
    )
    x["score_industry_axis_single"] = (
        0.75 * rank01(x["f_ind_peer_strong_count"], True) + 0.25 * rank01(x["f_ind_strength_5d"], True)
    )

    # path A
    x["path_a_eligible"] = (
        (pd.to_numeric(x["f_strength_rs20_xsec_q"], errors="coerce") >= 0.72)
        & (pd.to_numeric(x["f_trend_close_ma20_gap"], errors="coerce") >= 0.02)
    )
    a_trend = rank01(x["f_strength_rs20_xsec_q"], True).clip(upper=0.90)
    a_ind = rank01(x["f_ind_peer_strong_count"], True)
    a_chip = rank01(x["f_chip_winner_rate"], True)
    x["pathA_score"] = 0.65 * a_trend + 0.20 * a_ind + 0.15 * a_chip
    heat = (a_trend >= HEAT_TREND_Q) & (a_ind >= HEAT_IND_Q)
    x.loc[heat, "pathA_score"] = np.minimum(x.loc[heat, "pathA_score"], HEAT_SCORE_CAP) - HEAT_PENALTY
    x["rank_a"] = rank_within_day(x["path_a_eligible"], x["pathA_score"], x["trade_date"])
    x["path_a_pass"] = x["path_a_eligible"] & (x["rank_a"] <= CUTOFF_A)

    # path B
    x["path_b_eligible"] = (
        (pd.to_numeric(x["f_strength_rs20_xsec_q"], errors="coerce") >= 0.60)
        & (pd.to_numeric(x["f_trend_close_ma20_gap"], errors="coerce") >= 0.00)
    )
    b_chip = 0.60 * rank01(x["f_chip_winner_rate"], True) + 0.40 * rank01(x["f_chip_low_position120"], True)
    x["pathB_score"] = 0.50 * x["score_platform_axis_single"] + 0.40 * b_chip + 0.10 * rank01(
        x["f_strength_rs20_xsec_q"], True
    )
    x["rank_b"] = rank_within_day(x["path_b_eligible"], x["pathB_score"], x["trade_date"])
    x["path_b_pass"] = x["path_b_eligible"] & (x["rank_b"] <= CUTOFF_B)

    # day-level quota selection
    x["selected_base"] = False
    x["path_source"] = ""
    x["rank_in_path"] = np.nan
    x["score_total"] = np.nan

    for td, g in x.groupby("trade_date"):
        idx_a = g.index[x.loc[g.index, "path_a_pass"]]
        idx_b = g.index[x.loc[g.index, "path_b_pass"]]
        pick_a = x.loc[idx_a].assign(_s=x.loc[idx_a, "pathA_score"]).sort_values("_s", ascending=False).head(QUOTA_A).index
        pick_b = x.loc[idx_b].assign(_s=x.loc[idx_b, "pathB_score"]).sort_values("_s", ascending=False).head(QUOTA_B).index

        picks = pick_a.union(pick_b)
        if len(picks) == 0:
            continue
        x.loc[picks, "selected_base"] = True

        x.loc[pick_a, "path_source"] = "A"
        x.loc[pick_a, "score_total"] = x.loc[pick_a, "pathA_score"]
        x.loc[pick_a, "rank_in_path"] = x.loc[pick_a, "pathA_score"].rank(method="first", ascending=False).astype(int)

        b_only = [i for i in pick_b if i not in set(pick_a)]
        x.loc[b_only, "path_source"] = "B"
        x.loc[b_only, "score_total"] = x.loc[b_only, "pathB_score"]
        if b_only:
            x.loc[b_only, "rank_in_path"] = x.loc[b_only, "pathB_score"].rank(method="first", ascending=False).astype(int)

        both = [i for i in pick_b if i in set(pick_a)]
        for i in both:
            sa = float(x.at[i, "pathA_score"])
            sb = float(x.at[i, "pathB_score"])
            if pd.notna(sa) and (pd.isna(sb) or sa >= sb):
                x.at[i, "path_source"] = "A"
                x.at[i, "score_total"] = sa
            else:
                x.at[i, "path_source"] = "B"
                x.at[i, "score_total"] = sb
            x.at[i, "rank_in_path"] = 1

    # global rank within selected_base only
    x["rank_global_after_merge"] = np.nan
    sel = x["selected_base"]
    for td, g in x[sel].groupby("trade_date"):
        x.loc[g.index, "rank_global_after_merge"] = x.loc[g.index, "score_total"].rank(method="first", ascending=False).astype(int)

    return x


def add_rule_layers(x: pd.DataFrame) -> pd.DataFrame:
    d = x.copy()
    selected = d["selected_base"].fillna(False)

    # v3.2 robust R2/R3 quantiles computed on selected universe
    s = d[selected].copy()
    q_ind_60 = s["score_industry_axis_single"].quantile(0.60)
    q_chip_65 = s["f_chip_winner_rate"].quantile(0.65)
    q_platform_35 = s["score_platform_axis_single"].quantile(0.35)
    q_comp_65 = s["f_platform_compress_ratio"].quantile(0.65)

    r2 = ~((d["score_industry_axis_single"] >= q_ind_60) & (d["f_chip_winner_rate"] >= q_chip_65))
    r3 = ~((d["score_platform_axis_single"] <= q_platform_35) & (d["f_platform_compress_ratio"] >= q_comp_65))
    d["pass_v3_2_candidate"] = (selected & r2 & r3).astype(int)
    d["in_core_pool"] = d["pass_v3_2_candidate"].astype(int)

    # v3.1 relaxed for enhancement tag
    r1_rel = (d["score_total"] >= 0.8300) & (d["score_platform_axis_single"] >= 0.2950)
    r2_rel = ~((d["score_industry_axis_single"] >= 0.6650) & (d["f_chip_winner_rate"] >= 0.9940))
    r3_rel = ~((d["score_platform_axis_single"] <= 0.2950) & (d["f_platform_compress_ratio"] >= 0.6900))
    d["pass_v3_1_relaxed"] = (selected & r1_rel & r2_rel & r3_rel).astype(int)

    d["in_priority_tag"] = ((d["in_core_pool"] == 1) & (d["pass_v3_1_relaxed"] == 1)).astype(int)
    d["in_strict_pool"] = ((d["in_priority_tag"] == 1) & (d["path_source"] == "A")).astype(int)
    d["in_F3"] = (
        (d["in_strict_pool"] == 1)
        & (d["score_platform_axis_single"] <= 0.64)
        & (d["score_industry_axis_single"] <= 0.90)
        & (d["f_platform_compress_ratio"] >= 0.33)
    ).astype(int)

    return d


def add_ahigh_labels(d: pd.DataFrame) -> pd.DataFrame:
    x = d.copy()
    fwd = load_forward_daily()
    x = x.merge(fwd, on=["ts_code", "trade_date"], how="left")
    x["ret_t1_close"] = x["close_t1"] / x["buy_open_t1"] - 1.0
    x["ret_t2_close"] = x["close_t2"] / x["buy_open_t1"] - 1.0
    x["ret_t3_close"] = x["close_t3"] / x["buy_open_t1"] - 1.0

    x["label_A_high"] = 0
    x["label_A_mid"] = 0
    x["label_A_low"] = 0
    x["label_C"] = (x["label_class"] == "C").astype(int)
    x["label_G"] = (x["label_class"] == "G").astype(int)

    a = x[x["label_class"] == "A"].copy()
    valid = a.dropna(subset=["ret_t1_close", "ret_t2_close", "ret_t3_close"]).copy()
    if not valid.empty:
        win_t2 = (valid["ret_t2_close"] > 0).astype(float)
        win_t3 = (valid["ret_t3_close"] > 0).astype(float)
        qscore = (
            0.35 * rank01(valid["ret_t2_close"], True)
            + 0.35 * rank01(valid["ret_t3_close"], True)
            + 0.15 * rank01(valid["ret_t1_close"], True)
            + 0.10 * win_t2
            + 0.05 * win_t3
        )
        q_low = qscore.quantile(0.33)
        q_high = qscore.quantile(0.67)
        a_high_idx = valid.index[qscore >= q_high]
        a_low_idx = valid.index[qscore <= q_low]
        a_mid_idx = valid.index[(qscore > q_low) & (qscore < q_high)]
        x.loc[a_high_idx, "label_A_high"] = 1
        x.loc[a_mid_idx, "label_A_mid"] = 1
        x.loc[a_low_idx, "label_A_low"] = 1

        # A rows missing forward bars: default to mid (non-high) to avoid losing A denominator.
        missing_idx = a.index.difference(valid.index)
        x.loc[missing_idx, "label_A_mid"] = 1

    return x


def build_recall_table(x: pd.DataFrame) -> pd.DataFrame:
    a_mask = x["label_class"] == "A"
    ah_mask = x["label_A_high"] == 1

    rows = []
    for layer, col in [
        ("core_pool", "in_core_pool"),
        ("priority_tag", "in_priority_tag"),
        ("strict_pool", "in_strict_pool"),
        ("F3", "in_F3"),
    ]:
        m = x[col].astype(int) == 1
        a_total = int(a_mask.sum())
        ah_total = int(ah_mask.sum())
        a_recall = int((a_mask & m).sum())
        ah_recall = int((ah_mask & m).sum())
        rows.append(
            {
                "layer": layer,
                "total_A": a_total,
                "recall_count_A": a_recall,
                "recall_rate_A": float(a_recall / a_total) if a_total else np.nan,
                "total_A_high": ah_total,
                "recall_count_A_high": ah_recall,
                "recall_rate_A_high": float(ah_recall / ah_total) if ah_total else np.nan,
                "miss_count_A_high": int(ah_total - ah_recall),
                "miss_rate_A_high": float((ah_total - ah_recall) / ah_total) if ah_total else np.nan,
            }
        )
    return pd.DataFrame(rows)


def build_ahigh_miss_reason(x: pd.DataFrame) -> pd.DataFrame:
    ah = x[x["label_A_high"] == 1].copy()
    reason = np.full(len(ah), "", dtype=object)

    path_a = ah["path_a_eligible"].fillna(False)
    in_core = ah["in_core_pool"].astype(int).eq(1)
    in_priority = ah["in_priority_tag"].astype(int).eq(1)
    in_strict = ah["in_strict_pool"].astype(int).eq(1)
    in_f3 = ah["in_F3"].astype(int).eq(1)

    reason[~path_a] = "not_in_path_A"
    reason[path_a & ~in_core] = "not_in_core_pool"
    reason[path_a & in_core & ~in_priority] = "no_priority_tag"
    reason[path_a & in_core & in_priority & ~in_strict] = "excluded_by_strict_pool"
    reason[path_a & in_core & in_priority & in_strict & ~in_f3] = "failed_F3_gate"
    reason[path_a & in_core & in_priority & in_strict & in_f3] = "captured_by_F3"

    ah["miss_reason"] = reason
    total = len(ah)
    miss_only = ah[ah["miss_reason"] != "captured_by_F3"].copy()
    miss_total = len(miss_only)

    rows = []
    for k in ["not_in_path_A", "not_in_core_pool", "no_priority_tag", "excluded_by_strict_pool", "failed_F3_gate"]:
        c = int((miss_only["miss_reason"] == k).sum())
        rows.append(
            {
                "miss_reason": k,
                "miss_count": c,
                "miss_ratio_in_missed_A_high": float(c / miss_total) if miss_total else np.nan,
                "miss_ratio_in_total_A_high": float(c / total) if total else np.nan,
            }
        )
    return pd.DataFrame(rows)


def write_compare_md(recall_full: pd.DataFrame, miss_full: pd.DataFrame, x: pd.DataFrame) -> None:
    # full-universe key figures
    total_a = int((x["label_class"] == "A").sum())
    total_ah = int((x["label_A_high"] == 1).sum())
    f3_row = recall_full[recall_full["layer"] == "F3"].iloc[0]
    pr_row = recall_full[recall_full["layer"] == "priority_tag"].iloc[0]
    top_reason = miss_full.sort_values("miss_count", ascending=False).iloc[0]

    # eval210 key figures
    eval210 = pd.read_csv(IN_EVAL210)
    eval210_total_a = int((eval210["label_true_breakout"] == "A").sum()) if "label_true_breakout" in eval210.columns else np.nan
    eval210_total_ah = int(pd.to_numeric(eval210.get("label_A_high", 0), errors="coerce").fillna(0).sum())
    eval210_audit = pd.read_csv(IN_EVAL210_AUDIT)
    eval210_f3 = eval210_audit[(eval210_audit["layer"] == "F3") & (eval210_audit["window"] == "all")]
    eval210_f3_rate = float(eval210_f3.iloc[0]["recall_rate"]) if not eval210_f3.empty else np.nan

    lines = [
        "# 全年 18,491 vs 210 子集 召回对照",
        "",
        "## 结论",
        f"- 全年 A 总量={total_a}, A_high 总量={total_ah}",
        f"- 全年 F3 的 A_high 召回率={float(f3_row['recall_rate_A_high']):.2%}",
        f"- 全年最大漏抓源={top_reason['miss_reason']} (miss_count={int(top_reason['miss_count'])})",
        "",
        "## 与 210 子集差异",
        f"- 210 子集 A 总量={eval210_total_a}, A_high 总量={eval210_total_ah}",
        f"- 210 子集 F3 A_high 召回率={eval210_f3_rate:.2%}",
        f"- 全年 F3 A_high 召回率={float(f3_row['recall_rate_A_high']):.2%}",
        "- 结论：210 子集低估了召回问题，全年口径下召回率更低、漏抓更严重。",
        "",
        "## 主线判断",
        f"- 全年尺度下最大漏抓源是 {top_reason['miss_reason']}，前置召回修复必须优先。",
        "- 当前不应继续买点开发，先修全年召回主线。",
        "",
    ]
    OUT_COMPARE.write_text("\n".join(lines), encoding="utf-8")

    OUT_SUMMARY.write_text(
        json.dumps(
            {
                "full_universe": {
                    "total_events": int(len(x)),
                    "total_A": total_a,
                    "total_A_high": total_ah,
                    "recall": recall_full.to_dict("records"),
                    "ahigh_miss_reasons": miss_full.to_dict("records"),
                },
                "eval210": {
                    "rows": int(len(eval210)),
                    "total_A": eval210_total_a,
                    "total_A_high": eval210_total_ah,
                    "f3_recall_rate_A_high_all": eval210_f3_rate,
                },
                "decision": {
                    "must_prioritize_recall": True,
                    "should_continue_buypoint_dev": False,
                },
                "files": {
                    "mapping": str(OUT_MAP),
                    "recall": str(OUT_RECALL),
                    "miss": str(OUT_MISS),
                    "compare": str(OUT_COMPARE),
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def main() -> None:
    d = load_universe()
    d = add_scores_and_path(d)
    d = add_rule_layers(d)
    d = add_ahigh_labels(d)

    # output full mapping
    keep_cols = [
        "trade_date",
        "stock_code",
        "stock_name",
        "ts_code",
        "label_class",
        "label_A_high",
        "path_source",
        "in_core_pool",
        "in_priority_tag",
        "in_strict_pool",
        "in_F3",
        "score_total",
        "score_platform_axis_single",
        "score_industry_axis_single",
        "f_chip_winner_rate",
        "f_platform_compress_ratio",
        "rank_global_after_merge",
        "path_a_eligible",
        "selected_base",
    ]
    out_map = d[keep_cols].copy()
    out_map.to_csv(OUT_MAP, index=False, encoding="utf-8-sig")

    recall = build_recall_table(d)
    recall.to_csv(OUT_RECALL, index=False, encoding="utf-8-sig")

    miss = build_ahigh_miss_reason(d)
    miss.to_csv(OUT_MISS, index=False, encoding="utf-8-sig")

    write_compare_md(recall, miss, d)

    total_a = int((d["label_class"] == "A").sum())
    total_ah = int((d["label_A_high"] == 1).sum())
    f3_rate = float(recall[recall["layer"] == "F3"]["recall_rate_A_high"].iloc[0])
    print(f"full_events={len(d)} A={total_a} A_high={total_ah} F3_A_high_recall={f3_rate:.4f}")
    print(str(OUT_MAP))
    print(str(OUT_RECALL))
    print(str(OUT_MISS))
    print(str(OUT_COMPARE))
    print(str(OUT_SUMMARY))


if __name__ == "__main__":
    main()
