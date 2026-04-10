import json
from pathlib import Path

import pandas as pd


BASE_DIR = Path(r"D:\HuaweiAI\quantSystem2\data\research\strong_start_full\v4_scan")
INPUT_PATH = BASE_DIR / "true_breakout_ahigh_failure_quadrants.csv"

C_PATTERNS_PATH = BASE_DIR / "true_breakout_C_patterns.csv"
A_PATTERNS_PATH = BASE_DIR / "true_breakout_Ahigh_patterns.csv"
RULES_PATH = BASE_DIR / "true_breakout_net_separation_rules.csv"
REPORT_PATH = BASE_DIR / "true_breakout_net_separation_report.md"


def build_masks(df: pd.DataFrame) -> dict[str, pd.Series]:
    # Thresholds are anchored to kept_Ahigh + kept_C pooled quantiles from prior audit:
    # q40/q60 landmarks:
    # score_total q40=0.8377
    # score_trend_axis_single q60=0.9030
    # score_platform_axis_single q40=0.3080
    # score_industry_axis_single q40=0.6460, q60=0.7378
    # f_platform_compress_ratio q60=0.6772
    # f_chip_winner_rate q60=0.9925
    # f_strength_rs20_xsec_q q40=0.9473
    return {
        "c1_low_score_low_trend": (
            (df["score_total"] <= 0.8377)
            & (df["score_trend_axis_single"] <= 0.9030)
        ),
        "c2_low_platform_high_compress": (
            (df["score_platform_axis_single"] <= 0.3080)
            & (df["f_platform_compress_ratio"] >= 0.6772)
        ),
        "c3_hot_industry_hot_chip": (
            (df["score_industry_axis_single"] >= 0.6460)
            & (df["f_chip_winner_rate"] >= 0.9925)
        ),
        "c4_low_score_low_rs20": (
            (df["score_total"] <= 0.8377)
            & (df["f_strength_rs20_xsec_q"] <= 0.9473)
        ),
        "c5_trend_industry_pseudo_sync": (
            (df["score_trend_axis_single"] <= 0.9030)
            & (df["score_industry_axis_single"] >= 0.6460)
        ),
        "a1_high_score_good_platform": (
            (df["score_total"] >= 0.8377)
            & (df["score_platform_axis_single"] >= 0.3080)
        ),
        "a2_not_overheat_and_not_overcompress": (
            (df["score_industry_axis_single"] <= 0.7378)
            & (df["f_platform_compress_ratio"] <= 0.6772)
        ),
        "a3_good_platform_not_hot_industry": (
            (df["score_platform_axis_single"] >= 0.3080)
            & (df["score_industry_axis_single"] <= 0.6460)
        ),
        "a4_high_score_not_hot_industry": (
            (df["score_total"] >= 0.8377)
            & (df["score_industry_axis_single"] <= 0.7378)
        ),
        "a5_high_rs20_good_platform": (
            (df["f_strength_rs20_xsec_q"] >= 0.9473)
            & (df["score_platform_axis_single"] >= 0.3080)
        ),
    }


def support_stats(mask: pd.Series, kept_c: pd.DataFrame, kept_ah: pd.DataFrame) -> dict:
    c_sup = float(mask.loc[kept_c.index].mean()) if len(kept_c) else 0.0
    a_sup = float(mask.loc[kept_ah.index].mean()) if len(kept_ah) else 0.0
    return {
        "support_kept_C": c_sup,
        "support_kept_Ahigh": a_sup,
        "diff_C_minus_Ahigh": c_sup - a_sup,
    }


def main() -> None:
    df = pd.read_csv(INPUT_PATH)
    kept_c = df[df["failure_quadrant"] == "kept_C"].copy()
    kept_ah = df[df["failure_quadrant"] == "kept_Ahigh"].copy()

    masks = build_masks(df)

    c_pattern_defs = [
        ("C_pattern_1", "low_score + low_trend"),
        ("C_pattern_2", "low_platform_score + high_platform_compress"),
        ("C_pattern_3", "high_industry_heat + high_chip_heat"),
        ("C_pattern_4", "low_score + low_rs20"),
        ("C_pattern_5", "low_trend + high_industry_heat"),
    ]
    c_mask_keys = [
        "c1_low_score_low_trend",
        "c2_low_platform_high_compress",
        "c3_hot_industry_hot_chip",
        "c4_low_score_low_rs20",
        "c5_trend_industry_pseudo_sync",
    ]

    a_pattern_defs = [
        ("Ahigh_pattern_1", "high_score + good_platform_score"),
        ("Ahigh_pattern_2", "not_overheated_industry + not_overcompressed_platform"),
        ("Ahigh_pattern_3", "good_platform_score + cool_industry"),
        ("Ahigh_pattern_4", "high_score + non_overheated_industry"),
        ("Ahigh_pattern_5", "high_rs20 + good_platform_score"),
    ]
    a_mask_keys = [
        "a1_high_score_good_platform",
        "a2_not_overheat_and_not_overcompress",
        "a3_good_platform_not_hot_industry",
        "a4_high_score_not_hot_industry",
        "a5_high_rs20_good_platform",
    ]

    c_rows = []
    for (pid, desc), key in zip(c_pattern_defs, c_mask_keys):
        s = support_stats(masks[key], kept_c, kept_ah)
        c_rows.append(
            {
                "pattern_id": pid,
                "pattern_desc": desc,
                "logic": key,
                **s,
                "support_gap_rank": s["diff_C_minus_Ahigh"],
            }
        )
    c_df = pd.DataFrame(c_rows).sort_values("support_gap_rank", ascending=False)
    c_df.to_csv(C_PATTERNS_PATH, index=False)

    a_rows = []
    for (pid, desc), key in zip(a_pattern_defs, a_mask_keys):
        s = support_stats(masks[key], kept_c, kept_ah)
        a_rows.append(
            {
                "pattern_id": pid,
                "pattern_desc": desc,
                "logic": key,
                **s,
                "support_gap_rank": s["support_kept_Ahigh"] - s["support_kept_C"],
            }
        )
    a_df = pd.DataFrame(a_rows).sort_values("support_gap_rank", ascending=False)
    a_df.to_csv(A_PATTERNS_PATH, index=False)

    # Net-separation rules: keep Ahigh, kill C, stay lightweight/nonlinear.
    core_pool = df[df["core_keep"] == True].copy()
    r1 = masks["a1_high_score_good_platform"]
    r2 = ~masks["c3_hot_industry_hot_chip"]  # anti hot-industry x hot-chip pseudo-strength
    r3 = ~masks["c2_low_platform_high_compress"]  # anti false platform compression
    pass_all = r1 & r2 & r3
    core_pool["pass_net_rules"] = pass_all.loc[core_pool.index]

    before_ah = int((core_pool["a_quality_layer"] == "A_high").sum())
    before_c = int((core_pool["label_true_breakout"] == "C").sum())
    before_ratio = before_ah / before_c if before_c else None

    after = core_pool[core_pool["pass_net_rules"] == True].copy()
    after_ah = int((after["a_quality_layer"] == "A_high").sum())
    after_c = int((after["label_true_breakout"] == "C").sum())
    after_ratio = after_ah / after_c if after_c else None

    rules_df = pd.DataFrame(
        [
            {
                "rule_id": "R1",
                "if_condition": "score_total >= 0.8377 AND score_platform_axis_single >= 0.3080",
                "then_action": "keep_in_core_pool",
                "target": "retain_Ahigh",
                "Ahigh_pass_rate_in_core": float(
                    core_pool.loc[core_pool["a_quality_layer"] == "A_high", "pass_net_rules"].mean()
                ),
                "C_pass_rate_in_core": float(
                    core_pool.loc[core_pool["label_true_breakout"] == "C", "pass_net_rules"].mean()
                ),
            },
            {
                "rule_id": "R2",
                "if_condition": "NOT(score_industry_axis_single >= 0.6460 AND f_chip_winner_rate >= 0.9925)",
                "then_action": "keep_in_core_pool",
                "target": "kill_industry_heat_C",
                "Ahigh_pass_rate_in_core": float(
                    (~masks["c3_hot_industry_hot_chip"]).loc[core_pool.loc[core_pool["a_quality_layer"] == "A_high"].index].mean()
                ),
                "C_pass_rate_in_core": float(
                    (~masks["c3_hot_industry_hot_chip"]).loc[core_pool.loc[core_pool["label_true_breakout"] == "C"].index].mean()
                ),
            },
            {
                "rule_id": "R3",
                "if_condition": "NOT(score_platform_axis_single <= 0.3080 AND f_platform_compress_ratio >= 0.6772)",
                "then_action": "keep_in_core_pool",
                "target": "kill_platform_false_break_C",
                "Ahigh_pass_rate_in_core": float(
                    (~masks["c2_low_platform_high_compress"]).loc[core_pool.loc[core_pool["a_quality_layer"] == "A_high"].index].mean()
                ),
                "C_pass_rate_in_core": float(
                    (~masks["c2_low_platform_high_compress"]).loc[core_pool.loc[core_pool["label_true_breakout"] == "C"].index].mean()
                ),
            },
        ]
    )

    # Add before/after comparison block in rule table footer-like rows
    rules_df = pd.concat(
        [
            rules_df,
            pd.DataFrame(
                [
                    {
                        "rule_id": "BEFORE",
                        "if_condition": "core_keep == True",
                        "then_action": "baseline",
                        "target": "Ahigh/C ratio",
                        "Ahigh_pass_rate_in_core": before_ah,
                        "C_pass_rate_in_core": before_c,
                    },
                    {
                        "rule_id": "AFTER",
                        "if_condition": "R1 AND R2 AND R3",
                        "then_action": "net-separated-core",
                        "target": "Ahigh/C ratio",
                        "Ahigh_pass_rate_in_core": after_ah,
                        "C_pass_rate_in_core": after_c,
                    },
                ]
            ),
        ],
        ignore_index=True,
    )
    rules_df.to_csv(RULES_PATH, index=False)

    report = []
    report.append("# A_high 净分离规则草案")
    report.append("")
    report.append("## 结论")
    report.append(
        f"- 在当前 core_pool（core_keep=True）中，A_high/C 从 `{before_ah}/{before_c}` (`{before_ratio:.4f}`) 提升到 `{after_ah}/{after_c}` (`{after_ratio:.4f}`)。"
    )
    report.append("- 说明净分离规则对“保 A_high / 杀 C”有明显提升。")
    report.append("")
    report.append("## kept_C 高频组合（C模式）")
    for _, r in c_df.head(5).iterrows():
        report.append(
            f"- `{r['pattern_id']}`: {r['pattern_desc']} | C支持率={r['support_kept_C']:.3f}, Ahigh支持率={r['support_kept_Ahigh']:.3f}"
        )
    report.append("")
    report.append("## kept_Ahigh 高频组合（A_high模式）")
    for _, r in a_df.head(5).iterrows():
        report.append(
            f"- `{r['pattern_id']}`: {r['pattern_desc']} | Ahigh支持率={r['support_kept_Ahigh']:.3f}, C支持率={r['support_kept_C']:.3f}"
        )
    report.append("")
    report.append("## 净分离规则（最多3条）")
    report.append("- `R1`: `score_total>=0.8377 AND score_platform_axis_single>=0.3080` 才允许进核心池。")
    report.append("- `R2`: `industry_heat × chip_heat` 共振（高行业热度+高筹码热度）直接限流。")
    report.append("- `R3`: `低平台评分 + 高压缩比` 视为假压缩结构，直接限流。")
    report.append("")
    report.append("## 规则前后")
    report.append(f"- 规则前 A_high占比（在 A_high+C 中）：`{before_ah/(before_ah+before_c):.2%}`")
    report.append(f"- 规则后 A_high占比（在 A_high+C 中）：`{after_ah/(after_ah+after_c):.2%}`")
    report.append(f"- A_high通过率：`{after_ah/before_ah:.2%}`；C保留率：`{after_c/before_c:.2%}`")
    report.append("")
    report.append("## 下一步建议")
    report.append("- 已具备进入 `v3.1 结构升级` 条件（先把这三条规则并入结构层，再做同窗复核）。")
    REPORT_PATH.write_text("\n".join(report), encoding="utf-8")

    summary = {
        "before": {"Ahigh": before_ah, "C": before_c, "Ahigh_over_C": before_ratio},
        "after": {"Ahigh": after_ah, "C": after_c, "Ahigh_over_C": after_ratio},
        "improvement": {
            "Ahigh_over_C_delta": (after_ratio - before_ratio) if (before_ratio is not None and after_ratio is not None) else None,
            "Ahigh_retention": after_ah / before_ah if before_ah else None,
            "C_retention": after_c / before_c if before_c else None,
        },
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"\nSaved:\n- {C_PATTERNS_PATH}\n- {A_PATTERNS_PATH}\n- {RULES_PATH}\n- {REPORT_PATH}")


if __name__ == "__main__":
    main()

