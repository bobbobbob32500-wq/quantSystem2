# -*- coding: utf-8 -*-
"""
Parameter reverse-engineering (research-only, no backtest).

Input freeze (must not change sample or rerun A/C analysis):
- ac_feature_diff_summary.csv
- ac_feature_rankings.csv
- ac_feature_missing_audit.csv
- ac_feature_family_summary.md
- ac_feature_analysis_report.md
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd


def _research_dir() -> Path:
    return Path("data/research/strong_start_full")


REQ_FILES = [
    "ac_feature_analysis_set.parquet",  # only existence check
    "ac_feature_diff_summary.csv",
    "ac_feature_rankings.csv",
    "ac_feature_missing_audit.csv",
    "ac_feature_family_summary.md",
    "ac_feature_analysis_report.md",
]


def _parse_corr_pairs(report_text: str) -> List[Tuple[str, str, float]]:
    pat = re.compile(r"-\s+([a-zA-Z0-9_]+)\s+vs\s+([a-zA-Z0-9_]+):\s+corr=([-+]?\d*\.?\d+)")
    out: List[Tuple[str, str, float]] = []
    for m in pat.finditer(report_text):
        out.append((m.group(1), m.group(2), float(m.group(3))))
    return out


def _bounded(feature: str) -> bool:
    return (
        feature.endswith("_xsec_q")
        or feature.startswith("f_ind_rank_")
        or feature in ("f_chip_winner_rate", "f_k_close_pos")
    )


def _fmt_interval(kind: str, lo: float | None, hi: float | None) -> str:
    if kind == "gte":
        return f"[{lo:.6f}, +inf)"
    if kind == "lte":
        return f"(-inf, {hi:.6f}]"
    if kind == "range":
        return f"[{lo:.6f}, {hi:.6f}]"
    return "n/a"


def _intervals_from_medians(
    feature: str,
    direction: str,
    a_median: float,
    c_median: float,
) -> Tuple[str, str, str, str]:
    if np.isnan(a_median) or np.isnan(c_median):
        return ("n/a", "n/a", "n/a", "无法从中位数构造区间")

    gap = abs(a_median - c_median)
    if gap < 1e-12:
        gap = max(abs(a_median), abs(c_median), 1.0) * 0.02

    if direction == "A更高":
        loose = c_median + 0.20 * gap
        neutral = c_median + 0.50 * gap
        strict = c_median + 0.80 * gap
        if _bounded(feature):
            loose = float(np.clip(loose, 0.0, 1.0))
            neutral = float(np.clip(neutral, 0.0, 1.0))
            strict = float(np.clip(strict, 0.0, 1.0))
        return (
            _fmt_interval("gte", loose, None),
            _fmt_interval("gte", neutral, None),
            _fmt_interval("gte", strict, None),
            "大于更好",
        )
    if direction == "A更低":
        loose = c_median - 0.20 * gap
        neutral = c_median - 0.50 * gap
        strict = c_median - 0.80 * gap
        if _bounded(feature):
            loose = float(np.clip(loose, 0.0, 1.0))
            neutral = float(np.clip(neutral, 0.0, 1.0))
            strict = float(np.clip(strict, 0.0, 1.0))
        return (
            _fmt_interval("lte", None, loose),
            _fmt_interval("lte", None, neutral),
            _fmt_interval("lte", None, strict),
            "小于更好",
        )

    midpoint = (a_median + c_median) / 2.0
    width = gap * 0.6
    lo1, hi1 = midpoint - width, midpoint + width
    lo2, hi2 = midpoint - width * 0.7, midpoint + width * 0.7
    lo3, hi3 = midpoint - width * 0.4, midpoint + width * 0.4
    return (
        _fmt_interval("range", lo1, hi1),
        _fmt_interval("range", lo2, hi2),
        _fmt_interval("range", lo3, hi3),
        "区间更好",
    )


def main() -> None:
    root = _research_dir()
    for fn in REQ_FILES:
        p = root / fn
        if not p.exists():
            raise FileNotFoundError(f"missing required file: {p}")

    diff = pd.read_csv(root / "ac_feature_diff_summary.csv")
    rank = pd.read_csv(root / "ac_feature_rankings.csv")
    miss = pd.read_csv(root / "ac_feature_missing_audit.csv")
    family_md = (root / "ac_feature_family_summary.md").read_text(encoding="utf-8")
    report_md = (root / "ac_feature_analysis_report.md").read_text(encoding="utf-8")
    _ = family_md  # ensure file is read under frozen input rule

    merged = (
        rank.merge(
            miss[
                [
                    "feature",
                    "high_missing_flag",
                    "missing_imbalance_flag",
                    "stability_flag",
                ]
            ],
            on="feature",
            how="left",
        )
        .merge(
            diff[
                [
                    "feature",
                    "tail_ratio_q99q01_over_iqr",
                    "winsorize_recheck_suggest",
                ]
            ],
            on="feature",
            how="left",
        )
        .copy()
    )

    corr_pairs = _parse_corr_pairs(report_md)
    redundancy_rows: List[Dict[str, object]] = []
    secondary_to_primary: Dict[str, str] = {}
    corr_map: Dict[Tuple[str, str], float] = {}
    for a, b, c in corr_pairs:
        corr_map[(a, b)] = c
        corr_map[(b, a)] = c
        ra = merged.loc[merged["feature"] == a].iloc[0]
        rb = merged.loc[merged["feature"] == b].iloc[0]
        score_a = (float(ra["abs_cliffs_delta"]), -float(ra["missing_rate_max"]))
        score_b = (float(rb["abs_cliffs_delta"]), -float(rb["missing_rate_max"]))
        keep = a if score_a >= score_b else b
        drop = b if keep == a else a
        secondary_to_primary[drop] = keep
        redundancy_rows.append(
            {
                "feature_a": a,
                "feature_b": b,
                "spearman_corr": c,
                "keep_primary": keep,
                "downgrade_secondary": drop,
                "reason": f"高相关(|corr|={abs(c):.4f})，优先保留区分力更高/缺失更低者",
            }
        )

    # predefined layer priors
    trigger_pref = {
        "f_k_pct_chg",
        "f_k_body_to_atr",
        "f_k_close_pos",
        "f_k_upper_shadow_ratio",
        "f_k_lower_shadow_ratio",
        "f_k_break_pivot20_pct",
        "f_breakout_vol_ratio20",
        "f_up_down_vol_ratio20",
    }
    platform_soft = {
        "f_platform_len",
        "f_platform_range20",
        "f_platform_range30",
        "f_platform_range_best",
        "f_platform_compress_ratio",
        "f_atr_ratio",
        "f_near_pivot20",
    }
    peak_structure = {
        "f_chip_peak_count_sig",
        "f_chip_secondary_peak_ratio",
        "f_chip_peak_dominance",
        "f_chip_single_peak_score",
    }

    layering_rows: List[Dict[str, object]] = []
    for _, r in merged.sort_values("rank").iterrows():
        f = str(r["feature"])
        fam = str(r["family"])
        abs_d = float(r["abs_cliffs_delta"])
        miss_max = float(r["missing_rate_max"])
        direction = str(r["direction"])
        stable = str(r.get("stability_flag", "stable"))
        heavy_tail = int(r.get("winsorize_recheck_suggest", 0))
        redundant = f in secondary_to_primary

        layer = "连续评分候选"
        reasons: List[str] = [
            f"|delta|={abs_d:.4f}",
            f"missing_max={miss_max:.2%}",
            f"方向={direction}",
        ]

        if miss_max > 0.20:
            layer = "降级/弃用项"
            reasons.append("缺失偏高(>20%)")
        elif direction == "差异弱" and abs_d < 0.10:
            layer = "降级/弃用项"
            reasons.append("区分力弱")
        elif f in peak_structure and abs_d < 0.10:
            layer = "降级/弃用项"
            reasons.append("峰结构区分力不足")
        elif f in platform_soft and abs_d < 0.10:
            layer = "降级/弃用项"
            reasons.append("平台静态特征不宜过度约束")
        elif f in trigger_pref and abs_d >= 0.08:
            layer = "触发确认候选"
            reasons.append("更适合放在触发确认层")
        elif (
            abs_d >= 0.22
            and miss_max <= 0.12
            and direction != "差异弱"
            and fam in {"strength", "industry", "chip"}
            and (not redundant)
            and f not in trigger_pref
        ):
            layer = "硬过滤候选"
            reasons.append("高区分+低缺失+方向明确")
        elif abs_d >= 0.10 and direction != "差异弱":
            layer = "连续评分候选"
            reasons.append("有区分力，适合连续加分")
        else:
            layer = "降级/弃用项"
            reasons.append("边际信息有限")

        if redundant:
            if layer == "硬过滤候选":
                layer = "连续评分候选"
            reasons.append(f"与{secondary_to_primary[f]}高相关，避免重复约束")
        if stable != "stable":
            reasons.append("稳定性一般，需谨慎")
        if heavy_tail == 1:
            reasons.append("重尾分布，后续建议winsorize复核")

        layer_code_map = {
            "硬过滤候选": "hard_filter",
            "连续评分候选": "scoring",
            "触发确认候选": "trigger",
            "降级/弃用项": "downgrade",
        }

        layering_rows.append(
            {
                "feature": f,
                "family": fam,
                "rank": int(r["rank"]),
                "abs_cliffs_delta": abs_d,
                "missing_rate_max": miss_max,
                "direction": direction,
                "layer": layer,
                "layer_code": layer_code_map[layer],
                "redundant_with": secondary_to_primary.get(f, ""),
                "reason_summary": "；".join(reasons),
            }
        )

    layering_df = pd.DataFrame(layering_rows).sort_values(["layer", "rank"])

    # interval suggestions for重点特征（含用户指定6项）
    must_features = [
        "f_trend_close_ma20_gap",
        "f_k_pct_chg",
        "f_strength_rs20_xsec_q",
        "f_ind_rank_pctchg",
        "f_chip_winner_rate",
        "f_chip_stability_std10",
    ]
    plus_features = [
        "f_trend_close_ma60_gap",
        "f_strength_vs_index20",
        "f_k_body_to_atr",
        "f_k_close_pos",
        "f_breakout_vol_ratio20",
        "f_ind_rank_amount",
    ]
    interval_features = []
    for f in must_features + plus_features:
        if f in merged["feature"].values and f not in interval_features:
            interval_features.append(f)

    interval_rows: List[Dict[str, object]] = []
    for f in interval_features:
        r = merged.loc[merged["feature"] == f].iloc[0]
        loose, neutral, strict, dir_type = _intervals_from_medians(
            feature=f,
            direction=str(r["direction"]),
            a_median=float(r["median_a"]),
            c_median=float(r["median_c"]),
        )
        layer = layering_df.loc[layering_df["feature"] == f, "layer"].iloc[0]
        risk_note = []
        if layer == "硬过滤候选":
            risk_note.append("过严会错杀可交易A样本，建议先用宽松/中性")
            risk_note.append("过松会放入结构未启动的C样本")
        elif layer == "触发确认候选":
            risk_note.append("更适合T日/触发层，不宜前置硬卡")
        else:
            risk_note.append("建议以评分分层为主，避免硬阈值")
        if float(r["missing_rate_max"]) > 0.10:
            risk_note.append("存在一定缺失，需配合QC")

        interval_rows.append(
            {
                "feature": f,
                "family": str(r["family"]),
                "layer_candidate": layer,
                "direction_type": dir_type,
                "a_median": float(r["median_a"]),
                "c_median": float(r["median_c"]),
                "median_gap_abs": float(abs(r["median_a"] - r["median_c"])),
                "loose_interval": loose,
                "neutral_interval": neutral,
                "strict_interval": strict,
                "risk_note": "；".join(risk_note),
                "recommendation": (
                    "建议不设硬阈值，只做评分分层"
                    if layer == "连续评分候选"
                    else "可进入下一轮规则讨论"
                ),
            }
        )
    interval_df = pd.DataFrame(interval_rows)

    # structure draft markdown
    def _fmt_feature_list(layer_name: str, top_n: int = 12) -> List[str]:
        sub = layering_df[layering_df["layer"] == layer_name].sort_values("rank").head(top_n)
        lines = []
        for _, rr in sub.iterrows():
            lines.append(
                f"- `{rr['feature']}` ({rr['family']}, |delta|={rr['abs_cliffs_delta']:.4f})：{rr['reason_summary']}"
            )
        return lines

    md_lines: List[str] = []
    md_lines.append("# strong_start 研究版结构草图（参数反推阶段）")
    md_lines.append("")
    md_lines.append("## 第一层：硬过滤候选")
    md_lines.extend(_fmt_feature_list("硬过滤候选", 10) or ["- 暂无"])
    md_lines.append("")
    md_lines.append("## 第二层：连续评分候选")
    md_lines.extend(_fmt_feature_list("连续评分候选", 20) or ["- 暂无"])
    md_lines.append("")
    md_lines.append("## 第三层：触发确认候选")
    md_lines.extend(_fmt_feature_list("触发确认候选", 12) or ["- 暂无"])
    md_lines.append("")
    md_lines.append("## 第四层：降级/弃用项")
    md_lines.extend(_fmt_feature_list("降级/弃用项", 20) or ["- 暂无"])
    md_lines.append("")
    md_lines.append("## 区间建议说明")
    md_lines.append("- 采用 A/C 中位数差构造宽松/中性/严格三档，仅用于下一轮规则讨论。")
    md_lines.append("- 本文不输出最终精确阈值，不涉及回测。")
    draft_md = "\n".join(md_lines).strip() + "\n"

    # final report markdown
    hard_top5 = layering_df[layering_df["layer"] == "硬过滤候选"].sort_values("rank").head(5)
    score_top5 = layering_df[layering_df["layer"] == "连续评分候选"].sort_values("rank").head(5)
    trigger_top5 = layering_df[layering_df["layer"] == "触发确认候选"].sort_values("rank").head(5)
    downgrade_top10 = layering_df[layering_df["layer"] == "降级/弃用项"].sort_values("rank").head(10)

    # core answer helpers
    ind_front = merged[merged["feature"].isin(["f_ind_rank_pctchg", "f_ind_rank_amount"])]["abs_cliffs_delta"].mean()
    chip_base = merged[merged["feature"].isin(["f_chip_winner_rate", "f_chip_stability_std10", "f_chip_concentration"])]["abs_cliffs_delta"].mean()

    report: List[str] = []
    report.append("# 参数反推报告（研究阶段）")
    report.append("")
    report.append("## 1. 输入冻结确认")
    report.append("- 使用文件：`ac_feature_diff_summary.csv`、`ac_feature_rankings.csv`、`ac_feature_missing_audit.csv`、`ac_feature_family_summary.md`、`ac_feature_analysis_report.md`")
    report.append("- 未重跑 A/C 分析，未改样本口径，未进行回测。")
    report.append("")
    report.append("## 2. 特征分层结果")
    for layer in ["硬过滤候选", "连续评分候选", "触发确认候选", "降级/弃用项"]:
        cnt = int((layering_df["layer"] == layer).sum())
        report.append(f"- {layer}: {cnt} 个")
    report.append("")
    report.append("### 硬过滤候选 Top5")
    for _, rr in hard_top5.iterrows():
        report.append(f"- `{rr['feature']}`: {rr['reason_summary']}")
    report.append("")
    report.append("### 连续评分候选 Top5")
    for _, rr in score_top5.iterrows():
        report.append(f"- `{rr['feature']}`: {rr['reason_summary']}")
    report.append("")
    report.append("### 触发确认候选 Top5")
    for _, rr in trigger_top5.iterrows():
        report.append(f"- `{rr['feature']}`: {rr['reason_summary']}")
    report.append("")
    report.append("### 降级/弃用 Top10")
    for _, rr in downgrade_top10.iterrows():
        report.append(f"- `{rr['feature']}`: {rr['reason_summary']}")
    report.append("")
    report.append("## 3. 重点特征区间建议（非最终阈值）")
    for _, rr in interval_df.iterrows():
        report.append(
            f"- `{rr['feature']}` ({rr['layer_candidate']}): 宽松={rr['loose_interval']}，中性={rr['neutral_interval']}，严格={rr['strict_interval']}；{rr['risk_note']}"
        )
    report.append("")
    report.append("## 4. 冗余审计")
    top_red = pd.DataFrame(redundancy_rows).sort_values("spearman_corr", key=lambda x: x.abs(), ascending=False).head(12)
    for _, rr in top_red.iterrows():
        report.append(
            f"- `{rr['feature_a']}` vs `{rr['feature_b']}` corr={rr['spearman_corr']:.4f}，保留 `{rr['keep_primary']}`，降级 `{rr['downgrade_secondary']}`"
        )
    report.append("")
    report.append("## 5. 六个核心问题直答")
    report.append("1. 最适合进入硬过滤候选的前5个：")
    report.extend([f"   - {x}" for x in hard_top5["feature"].tolist()])
    report.append("2. 最适合进入连续评分层的前5个：")
    report.extend([f"   - {x}" for x in score_top5["feature"].tolist()])
    report.append("3. 最适合进入触发确认层的前5个：")
    report.extend([f"   - {x}" for x in trigger_top5["feature"].tolist()])
    report.append("4. 平台/收缩类不应再设过严：`f_platform_range20`、`f_platform_range30`、`f_platform_range_best`、`f_near_pivot20`、`f_atr_ratio`。")
    report.append(
        f"5. 基础筹码 vs 板块前排：基础筹码均值|delta|≈{chip_base:.4f}，板块前排均值|delta|≈{ind_front:.4f}；建议下一轮权重“板块前排略高，基础筹码紧随”。"
    )
    report.append("6. strong_start 里最该放松的3处：平台静态阈值、峰结构硬卡、把触发类信号前置为过滤条件。")
    report.append("")
    report.append("## 6. 说明")
    report.append("- 本报告仅为参数反推与分层草图，不含回测或收益结论。")
    report_md = "\n".join(report).strip() + "\n"

    # outputs
    layering_path = root / "feature_layering_candidates.csv"
    interval_path = root / "parameter_interval_candidates.csv"
    redundancy_path = root / "feature_redundancy_audit.csv"
    draft_path = root / "strong_start_research_structure_draft.md"
    reverse_report_path = root / "parameter_reverse_engineering_report.md"

    layering_df.to_csv(layering_path, index=False, encoding="utf-8-sig")
    interval_df.to_csv(interval_path, index=False, encoding="utf-8-sig")
    pd.DataFrame(redundancy_rows).to_csv(redundancy_path, index=False, encoding="utf-8-sig")
    draft_path.write_text(draft_md, encoding="utf-8")
    reverse_report_path.write_text(report_md, encoding="utf-8")

    print("=" * 72)
    print("parameter reverse-engineering done")
    print("=" * 72)
    print(f"layering={layering_path}")
    print(f"intervals={interval_path}")
    print(f"redundancy={redundancy_path}")
    print(f"draft={draft_path}")
    print(f"report={reverse_report_path}")


if __name__ == "__main__":
    main()
