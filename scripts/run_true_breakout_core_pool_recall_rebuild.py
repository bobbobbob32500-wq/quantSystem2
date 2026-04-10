from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(r"D:\HuaweiAI\quantSystem2")
BASE = ROOT / "data/research/strong_start_full/v4_scan"
DB_PATH = ROOT / "data/database/quant_system.db"

IN_SNAPSHOT = BASE / "true_breakout_feature_snapshot_1y.parquet"

OUT_MISS_BREAKDOWN = BASE / "true_breakout_core_pool_ahigh_miss_breakdown.csv"
OUT_IN_OUT_COMPARE = BASE / "true_breakout_core_pool_ahigh_in_vs_out_compare.csv"
OUT_CANDIDATES = BASE / "true_breakout_core_pool_recall_candidates.csv"
OUT_REVIEW = BASE / "true_breakout_core_pool_recall_rebuild_review.md"
OUT_SUMMARY = BASE / "true_breakout_core_pool_recall_rebuild_summary.json"


@dataclass
class CoreConfig:
    name: str
    note: str
    quota_a: int = 1
    quota_b: int = 2
    cutoff_a: float = 0.10
    cutoff_b: float = 0.20
    path_a_rs20_min: float = 0.72
    path_a_trend_min: float = 0.02
    path_b_rs20_min: float = 0.60
    path_b_trend_min: float = 0.00


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
    td_ser = trade_date.astype(str)
    for td in td_ser[mask].unique():
        idx = td_ser.index[(td_ser == td) & mask]
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


def add_quality_labels(d: pd.DataFrame) -> pd.DataFrame:
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
        x.loc[valid.index[qscore >= q_high], "label_A_high"] = 1
        x.loc[valid.index[qscore <= q_low], "label_A_low"] = 1
        x.loc[valid.index[(qscore > q_low) & (qscore < q_high)], "label_A_mid"] = 1
        missing_idx = a.index.difference(valid.index)
        x.loc[missing_idx, "label_A_mid"] = 1

    return x


def run_selector_core(base: pd.DataFrame, cfg: CoreConfig) -> pd.DataFrame:
    d = base.copy()

    d["score_trend_axis_single"] = (
        0.90 * rank01(d["f_strength_rs20_xsec_q"], True).clip(upper=0.90)
        + 0.10
        * pd.concat(
            [
                rank01(d["f_strength_ret20"], True),
                rank01(d["f_strength_rs60_xsec_q"], True),
                rank01(d["f_trend_close_ma20_gap"], True),
                rank01(d["f_trend_ma20_ma60_gap"], True),
                rank01(d["f_trend_ma20_slope5"], True),
            ],
            axis=1,
        ).mean(axis=1)
    )
    d["score_platform_axis_single"] = (
        0.70 * rank01(d["f_platform_compress_ratio"], False) + 0.30 * rank01(d["f_platform_range30"], False)
    )
    d["score_chip_axis_single"] = (
        0.45 * rank01(d["f_chip_winner_rate"], True)
        + 0.35 * rank01(d["f_chip_low_position120"], True)
        + 0.20 * rank01(d["f_chip_stability_std10"], True)
    )
    d["score_industry_axis_single"] = (
        0.75 * rank01(d["f_ind_peer_strong_count"], True) + 0.25 * rank01(d["f_ind_strength_5d"], True)
    )

    # Path A
    d["path_a_eligible"] = (
        (pd.to_numeric(d["f_strength_rs20_xsec_q"], errors="coerce") >= cfg.path_a_rs20_min)
        & (pd.to_numeric(d["f_trend_close_ma20_gap"], errors="coerce") >= cfg.path_a_trend_min)
    )
    a_trend = rank01(d["f_strength_rs20_xsec_q"], True).clip(upper=0.90)
    a_ind = rank01(d["f_ind_peer_strong_count"], True)
    a_chip = rank01(d["f_chip_winner_rate"], True)
    d["pathA_score"] = 0.65 * a_trend + 0.20 * a_ind + 0.15 * a_chip

    heat = (a_trend >= HEAT_TREND_Q) & (a_ind >= HEAT_IND_Q)
    d.loc[heat, "pathA_score"] = np.minimum(d.loc[heat, "pathA_score"], HEAT_SCORE_CAP) - HEAT_PENALTY

    d["rank_a"] = rank_within_day(d["path_a_eligible"], d["pathA_score"], d["trade_date"])
    d["path_a_pass"] = d["path_a_eligible"] & (d["rank_a"] <= cfg.cutoff_a)

    # Path B
    d["path_b_eligible"] = (
        (pd.to_numeric(d["f_strength_rs20_xsec_q"], errors="coerce") >= cfg.path_b_rs20_min)
        & (pd.to_numeric(d["f_trend_close_ma20_gap"], errors="coerce") >= cfg.path_b_trend_min)
    )
    b_chip = 0.60 * rank01(d["f_chip_winner_rate"], True) + 0.40 * rank01(d["f_chip_low_position120"], True)
    d["pathB_score"] = 0.50 * d["score_platform_axis_single"] + 0.40 * b_chip + 0.10 * rank01(
        d["f_strength_rs20_xsec_q"], True
    )
    d["rank_b"] = rank_within_day(d["path_b_eligible"], d["pathB_score"], d["trade_date"])
    d["path_b_pass"] = d["path_b_eligible"] & (d["rank_b"] <= cfg.cutoff_b)

    # Daily quota picks
    d["selected_base"] = False
    d["path_source"] = ""
    d["rank_in_path"] = np.nan
    d["score_total"] = np.nan

    for td, g in d.groupby("trade_date"):
        idx_a = g.index[d.loc[g.index, "path_a_pass"]]
        idx_b = g.index[d.loc[g.index, "path_b_pass"]]
        pick_a = d.loc[idx_a].assign(_s=d.loc[idx_a, "pathA_score"]).sort_values("_s", ascending=False).head(cfg.quota_a).index
        pick_b = d.loc[idx_b].assign(_s=d.loc[idx_b, "pathB_score"]).sort_values("_s", ascending=False).head(cfg.quota_b).index

        picks = pick_a.union(pick_b)
        if len(picks) == 0:
            continue
        d.loc[picks, "selected_base"] = True

        d.loc[pick_a, "path_source"] = "A"
        d.loc[pick_a, "score_total"] = d.loc[pick_a, "pathA_score"]
        d.loc[pick_a, "rank_in_path"] = d.loc[pick_a, "pathA_score"].rank(method="first", ascending=False).astype(int)

        b_only = [i for i in pick_b if i not in set(pick_a)]
        d.loc[b_only, "path_source"] = "B"
        d.loc[b_only, "score_total"] = d.loc[b_only, "pathB_score"]
        if b_only:
            d.loc[b_only, "rank_in_path"] = d.loc[b_only, "pathB_score"].rank(method="first", ascending=False).astype(int)

        both = [i for i in pick_b if i in set(pick_a)]
        for i in both:
            sa = float(d.at[i, "pathA_score"])
            sb = float(d.at[i, "pathB_score"])
            if pd.notna(sa) and (pd.isna(sb) or sa >= sb):
                d.at[i, "path_source"] = "A"
                d.at[i, "score_total"] = sa
            else:
                d.at[i, "path_source"] = "B"
                d.at[i, "score_total"] = sb
            d.at[i, "rank_in_path"] = 1

    d["rank_global_after_merge"] = np.nan
    sel = d["selected_base"]
    for td, g in d[sel].groupby("trade_date"):
        d.loc[g.index, "rank_global_after_merge"] = d.loc[g.index, "score_total"].rank(method="first", ascending=False).astype(int)

    # Keep v3.2 robust R2/R3 style with run-local quantile thresholds.
    s = d[d["selected_base"]].copy()
    if s.empty:
        d["in_core_pool"] = 0
        d["r2_pass"] = False
        d["r3_pass"] = False
        return d

    q_ind_60 = s["score_industry_axis_single"].quantile(0.60)
    q_chip_65 = s["f_chip_winner_rate"].quantile(0.65)
    q_platform_35 = s["score_platform_axis_single"].quantile(0.35)
    q_comp_65 = s["f_platform_compress_ratio"].quantile(0.65)

    d["r2_pass"] = ~((d["score_industry_axis_single"] >= q_ind_60) & (d["f_chip_winner_rate"] >= q_chip_65))
    d["r3_pass"] = ~((d["score_platform_axis_single"] <= q_platform_35) & (d["f_platform_compress_ratio"] >= q_comp_65))
    d["in_core_pool"] = (d["selected_base"] & d["r2_pass"] & d["r3_pass"]).astype(int)
    return d


def miss_breakdown(d: pd.DataFrame) -> pd.DataFrame:
    ah = d[d["label_A_high"] == 1].copy()
    miss = ah[ah["in_core_pool"] == 0].copy()

    reason = np.full(len(miss), "", dtype=object)
    pae = miss["path_a_eligible"].fillna(False).to_numpy()
    pbe = miss["path_b_eligible"].fillna(False).to_numpy()
    pap = miss["path_a_pass"].fillna(False).to_numpy()
    pbp = miss["path_b_pass"].fillna(False).to_numpy()
    sel = miss["selected_base"].fillna(False).to_numpy()
    r2 = miss["r2_pass"].fillna(False).to_numpy()
    r3 = miss["r3_pass"].fillna(False).to_numpy()

    reason[(~pae) & (~pbe)] = "step1_fail_dual_path_eligibility"
    m = (reason == "") & (pae & (~pap) & ((~pbe) | (~pbp)))
    reason[m] = "step2_fail_pathA_rank_cutoff"
    m = (reason == "") & (pbe & (~pbp) & ((~pae) | (~pap)))
    reason[m] = "step2_fail_pathB_rank_cutoff"
    m = (reason == "") & ((pap | pbp) & (~sel))
    reason[m] = "step3_fail_daily_quota_pick"
    m = (reason == "") & (sel & (~r2) & (~r3))
    reason[m] = "step4_fail_r2_r3_both"
    m = (reason == "") & (sel & (~r2) & r3)
    reason[m] = "step4_fail_r2_only"
    m = (reason == "") & (sel & r2 & (~r3))
    reason[m] = "step4_fail_r3_only"
    reason[reason == ""] = "stepX_fail_other"

    miss["miss_step_reason"] = reason
    total_ah = int(len(ah))
    total_miss = int(len(miss))

    out = (
        miss.groupby("miss_step_reason", as_index=False)
        .size()
        .rename(columns={"size": "miss_count"})
        .sort_values("miss_count", ascending=False)
    )
    out["miss_ratio_in_total_A_high"] = out["miss_count"] / total_ah if total_ah else np.nan
    out["miss_ratio_in_not_in_core_A_high"] = out["miss_count"] / total_miss if total_miss else np.nan
    out["rank_by_miss"] = np.arange(1, len(out) + 1)
    out["is_top3_source"] = (out["rank_by_miss"] <= 3).astype(int)
    return out


def in_vs_out_compare(d: pd.DataFrame) -> pd.DataFrame:
    fields = [
        "score_total",
        "score_platform_axis_single",
        "score_industry_axis_single",
        "f_chip_winner_rate",
        "f_platform_compress_ratio",
        "rank_global_after_merge",
        "f_strength_rs20_xsec_q",
        "f_trend_close_ma20_gap",
        "f_strength_ret20",
        "f_ind_peer_strong_count",
        "f_ind_rank_pctchg",
        "f_ind_rank_amount",
        "f_k_pct_chg",
        "f_k_body_to_atr",
        "f_k_upper_shadow_ratio",
        "f_vol20_vol60",
        "f_breakout_vol_ratio20",
    ]
    ah = d[d["label_A_high"] == 1].copy()
    groups = {
        "A_high_in_core_pool": ah[ah["in_core_pool"] == 1],
        "A_high_out_core_pool": ah[ah["in_core_pool"] == 0],
    }

    rows = []
    for gname, gdf in groups.items():
        for col in fields:
            if col not in gdf.columns:
                continue
            s = pd.to_numeric(gdf[col], errors="coerce").dropna()
            rows.append(
                {
                    "group": gname,
                    "field": col,
                    "count": int(s.shape[0]),
                    "mean": float(s.mean()) if len(s) else np.nan,
                    "median": float(s.median()) if len(s) else np.nan,
                    "p25": float(s.quantile(0.25)) if len(s) else np.nan,
                    "p75": float(s.quantile(0.75)) if len(s) else np.nan,
                }
            )
    return pd.DataFrame(rows)


def recall_candidate_metrics(d: pd.DataFrame, cfg: CoreConfig) -> dict:
    out = run_selector_core(d, cfg)
    selected = out[out["in_core_pool"] == 1].copy()

    a_total = int((out["label_class"] == "A").sum())
    ah_total = int((out["label_A_high"] == 1).sum())
    c_selected = int((selected["label_class"] == "C").sum())
    ah_selected = int((selected["label_A_high"] == 1).sum())
    a_selected = int((selected["label_class"] == "A").sum())

    def _mean(sname: str) -> float:
        s = pd.to_numeric(selected[sname], errors="coerce")
        return float(s.mean()) if len(s) else np.nan

    def _win(sname: str) -> float:
        s = pd.to_numeric(selected[sname], errors="coerce")
        return float((s > 0).mean()) if len(s) else np.nan

    return {
        "candidate": cfg.name,
        "note": cfg.note,
        "selected_n": int(len(selected)),
        "recall_count_A": a_selected,
        "recall_rate_A": float(a_selected / a_total) if a_total else np.nan,
        "recall_count_A_high": ah_selected,
        "recall_rate_A_high": float(ah_selected / ah_total) if ah_total else np.nan,
        "A_high_over_C": float(ah_selected / c_selected) if c_selected else np.nan,
        "mean_ret_t1": _mean("ret_t1_close"),
        "mean_ret_t2": _mean("ret_t2_close"),
        "mean_ret_t3": _mean("ret_t3_close"),
        "win_t1": _win("ret_t1_close"),
        "win_t2": _win("ret_t2_close"),
        "win_t3": _win("ret_t3_close"),
    }


def write_review(
    miss_df: pd.DataFrame,
    cmp_df: pd.DataFrame,
    cand_df: pd.DataFrame,
    total_ah: int,
    total_a: int,
) -> None:
    top3 = miss_df.head(3).copy()
    best = cand_df.sort_values(["recall_rate_A_high", "A_high_over_C"], ascending=[False, False]).iloc[0]

    # quick directional hints from compare table
    pivot = cmp_df.pivot(index="field", columns="group", values="median")
    insight_lines = []
    for field in ["score_platform_axis_single", "score_industry_axis_single", "f_platform_compress_ratio", "f_chip_winner_rate"]:
        if field in pivot.index:
            v_in = pivot.at[field, "A_high_in_core_pool"] if "A_high_in_core_pool" in pivot.columns else np.nan
            v_out = pivot.at[field, "A_high_out_core_pool"] if "A_high_out_core_pool" in pivot.columns else np.nan
            insight_lines.append(f"- `{field}` median: in={v_in:.4f}, out={v_out:.4f}")

    md = [
        "# core_pool 召回优先重建审计",
        "",
        "## 结论摘要",
        f"- 当前 core_pool 对全年 A_high（n={total_ah}）召回明显不足，属于召回优先问题。",
        f"- `not_in_core_pool` 分层漏抓 Top3：{', '.join(top3['miss_step_reason'].tolist())}",
        f"- 候选方向中最优（按 A_high 召回优先）为：`{best['candidate']}`。",
        "",
        "## not_in_core_pool A_high 漏因 Top3",
    ]
    for _, r in top3.iterrows():
        md.append(
            f"- {r['miss_step_reason']}: miss={int(r['miss_count'])}, "
            f"占A_high总量={r['miss_ratio_in_total_A_high']:.2%}, 占not_in_core_A_high={r['miss_ratio_in_not_in_core_A_high']:.2%}"
        )

    md.extend(
        [
            "",
            "## A_high in_core vs out_core 中位数快照",
            *insight_lines,
            "",
            "## 召回优先 candidate 结论",
            f"- 推荐下一轮落地方向：`{best['candidate']}`（{best['note']}）",
            f"- A_high 召回率：{best['recall_rate_A_high']:.2%}，A 召回率：{best['recall_rate_A']:.2%}",
            f"- 选中样本数：{int(best['selected_n'])}，A_high/C：{best['A_high_over_C']:.4f}",
            "",
            "## 推进判断",
            "- 应先进入“召回优先 core_pool 落地验证”阶段。",
            "- 当前不应继续买点开发，先修复全年召回主矛盾。",
        ]
    )
    OUT_REVIEW.write_text("\n".join(md), encoding="utf-8")

    OUT_SUMMARY.write_text(
        json.dumps(
            {
                "totals": {"A_total": total_a, "A_high_total": total_ah},
                "miss_top3": top3.to_dict("records"),
                "best_candidate": best.to_dict(),
                "decision": {
                    "enter_recall_first_corepool_validation": True,
                    "continue_buypoint_development": False,
                },
                "files": {
                    "miss_breakdown": str(OUT_MISS_BREAKDOWN),
                    "in_out_compare": str(OUT_IN_OUT_COMPARE),
                    "candidates": str(OUT_CANDIDATES),
                    "review": str(OUT_REVIEW),
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def main() -> None:
    base = load_universe()
    base = add_quality_labels(base)

    # Baseline core mapping first.
    baseline_cfg = CoreConfig(name="baseline_v32_core", note="current frozen core_pool logic")
    baseline = run_selector_core(base, baseline_cfg)

    miss_df = miss_breakdown(baseline)
    miss_df.to_csv(OUT_MISS_BREAKDOWN, index=False, encoding="utf-8-sig")

    cmp_df = in_vs_out_compare(baseline)
    cmp_df.to_csv(OUT_IN_OUT_COMPARE, index=False, encoding="utf-8-sig")

    # recall-first candidates (no large grid search)
    candidates = [
        CoreConfig(
            name="C1_relax_rank_thresholds",
            note="keep quotas, relax path rank cutoffs (A:10%->20%, B:20%->30%)",
            cutoff_a=0.20,
            cutoff_b=0.30,
        ),
        CoreConfig(
            name="C2_expand_daily_quotas",
            note="keep cutoffs, expand day quotas (A:1->2, B:2->3)",
            quota_a=2,
            quota_b=3,
        ),
        CoreConfig(
            name="C3_recall_friendly_front_pool",
            note="mild relax pathA eligibility + wider A cutoff + larger quotas",
            quota_a=2,
            quota_b=3,
            cutoff_a=0.20,
            cutoff_b=0.20,
            path_a_rs20_min=0.68,
            path_a_trend_min=0.00,
        ),
    ]

    rows = [recall_candidate_metrics(base, baseline_cfg)]
    rows.extend(recall_candidate_metrics(base, c) for c in candidates)
    cand_df = pd.DataFrame(rows)
    cand_df.to_csv(OUT_CANDIDATES, index=False, encoding="utf-8-sig")

    total_ah = int((baseline["label_A_high"] == 1).sum())
    total_a = int((baseline["label_class"] == "A").sum())
    write_review(miss_df, cmp_df, cand_df, total_ah=total_ah, total_a=total_a)

    top3 = miss_df.head(3)[["miss_step_reason", "miss_count"]].to_dict("records")
    print(f"A_total={total_a} A_high_total={total_ah}")
    print(f"Top3_miss={top3}")
    print(str(OUT_MISS_BREAKDOWN))
    print(str(OUT_IN_OUT_COMPARE))
    print(str(OUT_CANDIDATES))
    print(str(OUT_REVIEW))
    print(str(OUT_SUMMARY))


if __name__ == "__main__":
    main()
