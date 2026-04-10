# -*- coding: utf-8 -*-
"""
A/C feature-difference analysis (research stage only).

Strict scope:
- use frozen A/C research set + batch4 feature snapshot
- no parameter reverse-engineering
- no backtest/trading evaluation
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd
from scipy.stats import mannwhitneyu


def _research_dir() -> Path:
    return Path("data/research/strong_start_full")


def _family_of(feature: str) -> str:
    if feature.startswith("f_strength_") or feature.startswith("f_trend_"):
        return "strength"
    if feature.startswith("f_platform_") or feature in ("f_atr_ratio", "f_near_pivot20"):
        return "platform"
    if feature.startswith("f_vol") or feature in ("f_low_vol_days10", "f_breakout_vol_ratio20", "f_up_down_vol_ratio20"):
        return "volume"
    if feature.startswith("f_chip_"):
        return "chip"
    if feature.startswith("f_k_"):
        return "kline"
    if feature.startswith("f_ind_"):
        return "industry"
    return "unknown"


def _effect_bucket(abs_delta: float) -> str:
    if np.isnan(abs_delta):
        return "na"
    if abs_delta < 0.147:
        return "negligible"
    if abs_delta < 0.33:
        return "small"
    if abs_delta < 0.474:
        return "medium"
    return "large"


def _direction(delta: float, median_diff: float) -> str:
    if np.isnan(delta):
        return "差异弱"
    if abs(delta) < 0.05 and abs(median_diff) < 1e-12:
        return "差异弱"
    if abs(delta) < 0.05:
        return "差异弱"
    return "A更高" if delta > 0 else "A更低"


def _calc_cliffs_delta(x_a: pd.Series, x_c: pd.Series) -> Tuple[float, float]:
    if len(x_a) < 2 or len(x_c) < 2:
        return np.nan, np.nan
    u, p = mannwhitneyu(x_a, x_c, alternative="two-sided")
    delta = (2.0 * float(u) / (len(x_a) * len(x_c))) - 1.0
    return delta, float(p)


def _tail_flag(s: pd.Series) -> Tuple[bool, float]:
    if s.empty:
        return False, np.nan
    q01 = float(s.quantile(0.01))
    q25 = float(s.quantile(0.25))
    q75 = float(s.quantile(0.75))
    q99 = float(s.quantile(0.99))
    iqr = q75 - q25
    tail_ratio = (q99 - q01) / (abs(iqr) + 1e-12)
    return bool(tail_ratio > 10), float(tail_ratio)


def _candidate_role(abs_delta: float, miss_max: float) -> str:
    if np.isnan(abs_delta):
        return "辅助解释项"
    if abs_delta >= 0.33 and miss_max <= 0.10:
        return "候选硬过滤讨论"
    if abs_delta >= 0.147:
        return "候选连续评分讨论"
    return "辅助解释项"


def main() -> None:
    root = _research_dir()
    ac_path = root / "ac_main_research_set.parquet"
    feat_path = root / "event_feature_snapshot_batch4.parquet"

    if not ac_path.exists():
        raise FileNotFoundError(f"missing: {ac_path}")
    if not feat_path.exists():
        raise FileNotFoundError(f"missing: {feat_path}")

    ac = pd.read_parquet(ac_path).copy()
    feat = pd.read_parquet(feat_path).copy()
    ac["trade_date"] = ac["trade_date"].astype(str)
    feat["trade_date"] = feat["trade_date"].astype(str)

    if set(ac["label_abc"].unique()) - {"A", "C"}:
        raise ValueError("ac_main_research_set contains labels outside A/C")

    if ac.duplicated(["ts_code", "trade_date"]).any():
        raise ValueError("duplicate key in ac_main_research_set")
    if feat.duplicated(["ts_code", "trade_date"]).any():
        raise ValueError("duplicate key in event_feature_snapshot_batch4")

    analysis = ac.merge(
        feat,
        on=["ts_code", "trade_date", "label_abc", "event_type_candidate", "name", "industry"],
        how="left",
        indicator=True,
    )
    if (analysis["_merge"] != "both").any():
        miss = int((analysis["_merge"] != "both").sum())
        raise ValueError(f"analysis set join failed, missing rows: {miss}")
    analysis = analysis.drop(columns=["_merge"])

    analysis_path = root / "ac_feature_analysis_set.parquet"
    analysis.to_parquet(analysis_path, index=False)

    forbidden_patterns = ["_fwd_", "entry_", "max_favorable_excursion", "max_adverse_excursion", "structure_break"]
    forbidden_cols = [c for c in analysis.columns if any(p in c for p in forbidden_patterns)]
    if forbidden_cols:
        raise ValueError(f"forbidden columns present: {forbidden_cols}")

    all_f_cols = [c for c in analysis.columns if c.startswith("f_")]
    main_features = [c for c in all_f_cols if _family_of(c) != "unknown"]
    unknown_f = sorted(set(all_f_cols) - set(main_features))

    group_fields = ["label_abc", "event_type_candidate", "name", "industry", "trade_date", "ts_code"]
    exclude_fields = [
        "feature_ready_flag",
        "missing_ratio",
        "data_version",
        "feature_spec_version",
        "source_coverage_flag",
        "qc_note",
    ] + [c for c in analysis.columns if c.startswith("cost_") or c in ("winner_rate", "range_low_120", "range_high_120")]

    # ensure numeric for features
    for c in main_features:
        analysis[c] = pd.to_numeric(analysis[c], errors="coerce")

    a_mask = analysis["label_abc"] == "A"
    c_mask = analysis["label_abc"] == "C"
    n_a_total = int(a_mask.sum())
    n_c_total = int(c_mask.sum())

    # ready subset for stability check only
    ready_mask = analysis["feature_ready_flag"].fillna(0).astype(int).eq(1)

    rows: List[Dict[str, object]] = []
    for f in main_features:
        xa = analysis.loc[a_mask, f]
        xc = analysis.loc[c_mask, f]
        xa_non = xa.dropna()
        xc_non = xc.dropna()

        miss_a = float(xa.isna().mean())
        miss_c = float(xc.isna().mean())
        med_a = float(xa_non.median()) if not xa_non.empty else np.nan
        med_c = float(xc_non.median()) if not xc_non.empty else np.nan
        med_diff = med_a - med_c if (not np.isnan(med_a) and not np.isnan(med_c)) else np.nan

        delta, pvalue = _calc_cliffs_delta(xa_non, xc_non)
        abs_delta = abs(delta) if not np.isnan(delta) else np.nan

        combined = pd.concat([xa_non, xc_non], axis=0)
        heavy_tail, tail_ratio = _tail_flag(combined)

        # stability in ready-only subset
        xa_r = analysis.loc[a_mask & ready_mask, f].dropna()
        xc_r = analysis.loc[c_mask & ready_mask, f].dropna()
        delta_r, _ = _calc_cliffs_delta(xa_r, xc_r)
        delta_shift = abs(delta - delta_r) if (not np.isnan(delta) and not np.isnan(delta_r)) else np.nan

        rows.append(
            {
                "feature": f,
                "family": _family_of(f),
                "n_a_nonnull": int(len(xa_non)),
                "n_c_nonnull": int(len(xc_non)),
                "missing_rate_a": miss_a,
                "missing_rate_c": miss_c,
                "missing_rate_gap_abs": abs(miss_a - miss_c),
                "missing_rate_max": max(miss_a, miss_c),
                "median_a": med_a,
                "median_c": med_c,
                "median_diff_a_minus_c": med_diff,
                "direction": _direction(delta, med_diff),
                "cliffs_delta": delta,
                "abs_cliffs_delta": abs_delta,
                "effect_bucket": _effect_bucket(abs_delta),
                "mannwhitney_pvalue": pvalue,
                "heavy_tail_flag": int(heavy_tail),
                "tail_ratio_q99q01_over_iqr": tail_ratio,
                "ready_cliffs_delta": delta_r,
                "ready_delta_shift_abs": delta_shift,
                "winsorize_recheck_suggest": int(bool(heavy_tail)),
            }
        )

    diff_df = pd.DataFrame(rows).sort_values("abs_cliffs_delta", ascending=False)

    # ranking table
    rank_df = diff_df.copy()
    rank_df["rank"] = np.arange(1, len(rank_df) + 1)
    rank_df["candidate_role"] = rank_df.apply(
        lambda r: _candidate_role(float(r["abs_cliffs_delta"]), float(r["missing_rate_max"])),
        axis=1,
    )

    # correlation redundancy (Spearman)
    corr = analysis[main_features].corr(method="spearman")
    pairs: List[Tuple[str, str, float]] = []
    cols = corr.columns.tolist()
    for i in range(len(cols)):
        for j in range(i + 1, len(cols)):
            val = corr.iat[i, j]
            if pd.notna(val) and abs(float(val)) >= 0.85:
                pairs.append((cols[i], cols[j], float(val)))
    pairs_sorted = sorted(pairs, key=lambda x: abs(x[2]), reverse=True)
    redundant_text = [
        {"feature_a": a, "feature_b": b, "spearman_corr": v} for a, b, v in pairs_sorted[:80]
    ]

    # missing/stability audit
    miss_audit = diff_df[
        [
            "feature",
            "family",
            "missing_rate_a",
            "missing_rate_c",
            "missing_rate_gap_abs",
            "missing_rate_max",
            "n_a_nonnull",
            "n_c_nonnull",
            "abs_cliffs_delta",
            "effect_bucket",
            "ready_cliffs_delta",
            "ready_delta_shift_abs",
            "heavy_tail_flag",
            "winsorize_recheck_suggest",
        ]
    ].copy()
    miss_audit["high_missing_flag"] = (miss_audit["missing_rate_max"] > 0.20).astype(int)
    miss_audit["missing_imbalance_flag"] = (miss_audit["missing_rate_gap_abs"] > 0.05).astype(int)
    miss_audit["stability_flag"] = np.where(
        miss_audit["ready_delta_shift_abs"].fillna(0) > 0.05,
        "needs_caution",
        "stable",
    )

    # family summary markdown
    family_order = ["strength", "platform", "volume", "chip", "kline", "industry"]
    family_lines: List[str] = []
    family_lines.append("# A/C 六大维度差异汇总\n")
    family_lines.append(f"- 样本量：A={n_a_total}，C={n_c_total}")
    family_lines.append(f"- 主分析特征数：{len(main_features)}\n")
    for fam in family_order:
        sub = diff_df[diff_df["family"] == fam].copy()
        if sub.empty:
            continue
        top = sub.head(5)
        weak = sub.sort_values("abs_cliffs_delta", ascending=True).head(3)
        family_lines.append(f"## {fam}")
        family_lines.append(
            f"- 维度中位区分强度（|Cliff's delta| 中位数）：{sub['abs_cliffs_delta'].median():.4f}"
        )
        family_lines.append("- Top 特征：")
        for _, r in top.iterrows():
            family_lines.append(
                f"  - {r['feature']}: |delta|={r['abs_cliffs_delta']:.4f}, "
                f"方向={r['direction']}, A-C中位数差={r['median_diff_a_minus_c']:.6f}"
            )
        family_lines.append("- 弱特征：")
        for _, r in weak.iterrows():
            family_lines.append(
                f"  - {r['feature']}: |delta|={r['abs_cliffs_delta']:.4f}, 方向={r['direction']}"
            )
        family_lines.append("")

    family_md = "\n".join(family_lines).strip() + "\n"

    # full report markdown
    top15 = rank_df.head(15)
    bottom10 = rank_df.sort_values("abs_cliffs_delta", ascending=True).head(10)
    report_lines: List[str] = []
    report_lines.append("# A/C 特征差异分析报告（阶段：研究）")
    report_lines.append("")
    report_lines.append("## 1. 输入冻结")
    report_lines.append("- 主研究集：`ac_main_research_set.parquet`")
    report_lines.append("- 特征快照：`event_feature_snapshot_batch4.parquet`")
    report_lines.append("- 本次样本口径：仅 A/C，不含 B/N，不重抽样")
    report_lines.append(f"- 合并后样本：A={n_a_total}, C={n_c_total}, total={len(analysis)}")
    report_lines.append("")
    report_lines.append("## 2. 字段白名单")
    report_lines.append(f"- 主分析特征（f_*）数量：{len(main_features)}")
    report_lines.append(f"- 分组解释字段：{', '.join(group_fields)}")
    report_lines.append(f"- 排除字段（QC/元数据/原始辅助列）数量：{len(exclude_fields)}")
    report_lines.append(f"- 未归类 f_* 字段：{', '.join(unknown_f) if unknown_f else '无'}")
    report_lines.append(f"- 未来/交易字段混入检查：{'发现异常' if forbidden_cols else '未发现'}")
    report_lines.append("")
    report_lines.append("## 3. Top 15 区分特征")
    for _, r in top15.iterrows():
        report_lines.append(
            f"- {int(r['rank'])}. {r['feature']} ({r['family']}): |delta|={r['abs_cliffs_delta']:.4f}, "
            f"方向={r['direction']}, p={r['mannwhitney_pvalue']:.3e}, 缺失max={r['missing_rate_max']:.2%}"
        )
    report_lines.append("")
    report_lines.append("## 4. Bottom 10 弱特征")
    for _, r in bottom10.iterrows():
        report_lines.append(
            f"- {r['feature']} ({r['family']}): |delta|={r['abs_cliffs_delta']:.4f}, "
            f"方向={r['direction']}, 缺失max={r['missing_rate_max']:.2%}"
        )
    report_lines.append("")
    report_lines.append("## 5. 冗余/强相关提示（|Spearman|>=0.85）")
    if redundant_text:
        for item in redundant_text[:25]:
            report_lines.append(
                f"- {item['feature_a']} vs {item['feature_b']}: corr={item['spearman_corr']:.4f}"
            )
    else:
        report_lines.append("- 未发现达到阈值的强相关对")
    report_lines.append("")
    report_lines.append("## 6. 缺失与稳定性审计")
    high_miss = miss_audit[miss_audit["high_missing_flag"] == 1].sort_values("missing_rate_max", ascending=False)
    if high_miss.empty:
        report_lines.append("- 无高缺失特征（阈值 >20%）")
    else:
        report_lines.append("- 高缺失特征：")
        for _, r in high_miss.iterrows():
            report_lines.append(
                f"  - {r['feature']}: 缺失max={r['missing_rate_max']:.2%}, "
                f"|delta|={r['abs_cliffs_delta']:.4f}, 稳定性={r['stability_flag']}"
            )
    report_lines.append("")
    report_lines.append("## 7. 核心问题快答（仅重要性，不给阈值）")
    chip_top = rank_df[rank_df["family"] == "chip"].head(3)
    ind_top = rank_df[rank_df["family"] == "industry"].head(3)
    k_top = rank_df[rank_df["family"] == "kline"].head(3)
    platform_top = rank_df[rank_df["family"] == "platform"].head(3)
    report_lines.append(
        f"- 板块/行业 vs 峰结构：行业Top3 |delta|均值={ind_top['abs_cliffs_delta'].mean():.4f}；"
        f"筹码Top3 |delta|均值={chip_top['abs_cliffs_delta'].mean():.4f}"
    )
    report_lines.append(
        f"- K线质量Top3 |delta|均值={k_top['abs_cliffs_delta'].mean():.4f}；"
        f"平台Top3 |delta|均值={platform_top['abs_cliffs_delta'].mean():.4f}"
    )

    report_md = "\n".join(report_lines).strip() + "\n"

    # write outputs
    diff_path = root / "ac_feature_diff_summary.csv"
    rank_path = root / "ac_feature_rankings.csv"
    fam_md_path = root / "ac_feature_family_summary.md"
    miss_path = root / "ac_feature_missing_audit.csv"
    report_path = root / "ac_feature_analysis_report.md"
    whitelist_path = root / "ac_feature_whitelist_manifest.json"

    diff_df.to_csv(diff_path, index=False, encoding="utf-8-sig")
    rank_df.to_csv(rank_path, index=False, encoding="utf-8-sig")
    miss_audit.to_csv(miss_path, index=False, encoding="utf-8-sig")
    fam_md_path.write_text(family_md, encoding="utf-8")
    report_path.write_text(report_md, encoding="utf-8")

    whitelist_payload = {
        "main_features": main_features,
        "group_fields": group_fields,
        "excluded_fields": exclude_fields,
        "unknown_f_fields": unknown_f,
        "forbidden_cols_detected": forbidden_cols,
        "input_files": {
            "ac_main_research_set": str(ac_path.as_posix()),
            "event_feature_snapshot_batch4": str(feat_path.as_posix()),
        },
    }
    whitelist_path.write_text(json.dumps(whitelist_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print("=" * 72)
    print("ac feature diff analysis done")
    print("=" * 72)
    print(f"samples A={n_a_total} C={n_c_total} total={len(analysis)}")
    print(f"main_features={len(main_features)} unknown_f={len(unknown_f)}")
    print(f"analysis_set={analysis_path}")
    print(f"diff_summary={diff_path}")
    print(f"rankings={rank_path}")
    print(f"family_md={fam_md_path}")
    print(f"missing_audit={miss_path}")
    print(f"report_md={report_path}")
    print(f"whitelist_manifest={whitelist_path}")


if __name__ == "__main__":
    main()

