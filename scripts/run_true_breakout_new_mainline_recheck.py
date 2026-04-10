from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from run_true_breakout_core_pool_recall_rebuild import CoreConfig, add_quality_labels, load_universe, run_selector_core
from run_true_breakout_dual_channel_fast_review import assign_archetype
from run_true_breakout_dual_channel_mainline_v1_validation import build_ech2_mask


ROOT = Path(r"D:\HuaweiAI\quantSystem2")
BASE = ROOT / "data/research/strong_start_full/v4_scan"

OUT_MAPPING = BASE / "true_breakout_new_mainline_full_mapping.csv"
OUT_RECALL = BASE / "true_breakout_new_mainline_recall_recheck.csv"
OUT_MISS = BASE / "true_breakout_new_mainline_ahigh_miss_reason.csv"
OUT_ARCH = BASE / "true_breakout_new_mainline_archetype_recheck.csv"
OUT_REVIEW = BASE / "true_breakout_new_mainline_recheck.md"

MAIN_FROM = "2025-12-30"
MAIN_TO = "2026-03-30"
CONFIRM_FROM = "2025-09-29"
CONFIRM_TO = "2025-12-29"


def _window_mask(df: pd.DataFrame, dfrom: str, dto: str) -> pd.Series:
    td = pd.to_datetime(df["trade_date"], errors="coerce")
    return (td >= pd.Timestamp(dfrom)) & (td <= pd.Timestamp(dto))


def build_new_mainline(df_c2a: pd.DataFrame) -> pd.DataFrame:
    d = df_c2a.copy()
    d["in_C2A"] = d["in_core_pool"].eq(1)
    d["in_ech2_base"] = build_ech2_mask(d).fillna(False)

    increment_mask = d["in_ech2_base"] & (~d["in_C2A"])
    ind = pd.to_numeric(d["score_industry_axis_single"], errors="coerce")
    rs20 = pd.to_numeric(d["f_strength_rs20_xsec_q"], errors="coerce")

    q_ind_75 = float(ind[increment_mask].quantile(0.75))
    q_rs20_40 = float(rs20[increment_mask].quantile(0.40))

    d["ech2_q2_ind_ok"] = ind <= q_ind_75
    d["ech2_q2_rs20_ok"] = rs20 >= q_rs20_40
    d["in_ECH2_Q2"] = d["in_ech2_base"] & d["ech2_q2_ind_ok"] & d["ech2_q2_rs20_ok"]
    d["in_mainline_current"] = d["in_C2A"] | d["in_ECH2_Q2"]

    d["q2_industry_cap"] = q_ind_75
    d["q2_rs20_floor"] = q_rs20_40
    return d


def _recall_block(df: pd.DataFrame, scope: str, mask: pd.Series) -> list[dict]:
    g = df[mask].copy()
    out = []
    for scenario, col in [("C2A", "in_C2A"), ("C2A+ECH2_Q2", "in_mainline_current")]:
        sel = g[g[col].fillna(False)]
        a_total = int((g["label_class"] == "A").sum())
        ah_total = int((g["label_A_high"] == 1).sum())
        a_sel = int((sel["label_class"] == "A").sum())
        ah_sel = int((sel["label_A_high"] == 1).sum())
        out.append(
            {
                "scope": scope,
                "scenario": scenario,
                "A_total": a_total,
                "A_recall_count": a_sel,
                "A_recall_rate": float(a_sel / a_total) if a_total else np.nan,
                "A_high_total": ah_total,
                "A_high_recall_count": ah_sel,
                "A_high_recall_rate": float(ah_sel / ah_total) if ah_total else np.nan,
            }
        )
    return out


def miss_reason_breakdown(df: pd.DataFrame) -> pd.DataFrame:
    ah = df[df["label_A_high"] == 1].copy()
    miss = ah[~ah["in_mainline_current"]].copy()
    total_ah = len(ah)
    total_miss = len(miss)

    miss["flag_not_in_path_A"] = ~miss["path_a_eligible"].fillna(False)
    miss["flag_not_in_C2A_channel"] = ~miss["in_C2A"].fillna(False)
    miss["flag_not_in_ECH2_channel"] = ~miss["in_ECH2_Q2"].fillna(False)

    primary = np.where(
        miss["flag_not_in_path_A"],
        "not_in_path_A",
        np.where(
            (~miss["in_ech2_base"].fillna(False)),
            "not_in_ECH2_channel_scope",
            np.where(
                miss["in_ech2_base"].fillna(False) & (~miss["in_ECH2_Q2"].fillna(False)),
                "not_in_ECH2_channel_q2_gate",
                "not_in_C2A_channel_other",
            ),
        ),
    )
    miss["primary_reason"] = primary

    rows = []
    primary_df = miss.groupby("primary_reason", as_index=False).size().rename(columns={"size": "miss_count"})
    for _, r in primary_df.iterrows():
        rows.append(
            {
                "reason_group": "primary",
                "reason": r["primary_reason"],
                "miss_count": int(r["miss_count"]),
                "miss_share_in_remaining_A_high": float(r["miss_count"] / total_miss) if total_miss else np.nan,
                "miss_share_in_total_A_high": float(r["miss_count"] / total_ah) if total_ah else np.nan,
            }
        )

    bucket_flags = {
        "not_in_path_A": miss["flag_not_in_path_A"],
        "not_in_C2A_channel": miss["flag_not_in_C2A_channel"],
        "not_in_ECH2_channel": miss["flag_not_in_ECH2_channel"],
        "other_identified": miss["primary_reason"].eq("not_in_C2A_channel_other"),
    }
    for reason, flag in bucket_flags.items():
        c = int(flag.sum())
        rows.append(
            {
                "reason_group": "bucket_flag",
                "reason": reason,
                "miss_count": c,
                "miss_share_in_remaining_A_high": float(c / total_miss) if total_miss else np.nan,
                "miss_share_in_total_A_high": float(c / total_ah) if total_ah else np.nan,
            }
        )

    return pd.DataFrame(rows).sort_values(["reason_group", "miss_count"], ascending=[True, False])


def archetype_recheck(df: pd.DataFrame) -> pd.DataFrame:
    ah = df[df["label_A_high"] == 1].copy()
    ah["archetype"] = assign_archetype(ah)

    keep_types = [
        "A1_momentum_frontline",
        "A2_structure_chip",
        "A3_early_structure_low_rs20",
        "A4_balanced_highscore",
        "A5_mixed_other",
    ]

    rows = []
    for arche in keep_types:
        g = ah[ah["archetype"] == arche]
        total = len(g)
        old_cov = float(g["in_C2A"].mean()) if total else np.nan
        new_cov = float(g["in_mainline_current"].mean()) if total else np.nan
        rows.append(
            {
                "archetype": arche,
                "archetype_total": int(total),
                "coverage_C2A": old_cov,
                "coverage_C2A_ECH2_Q2": new_cov,
                "coverage_delta": (new_cov - old_cov) if total else np.nan,
                "captured_C2A": int(g["in_C2A"].sum()),
                "captured_C2A_ECH2_Q2": int(g["in_mainline_current"].sum()),
            }
        )
    return pd.DataFrame(rows)


def write_review(df_recall: pd.DataFrame, df_miss: pd.DataFrame, df_arch: pd.DataFrame) -> None:
    full_old = df_recall[(df_recall["scope"] == "full_year") & (df_recall["scenario"] == "C2A")].iloc[0]
    full_new = df_recall[(df_recall["scope"] == "full_year") & (df_recall["scenario"] == "C2A+ECH2_Q2")].iloc[0]

    d_ah = float(full_new["A_high_recall_rate"] - full_old["A_high_recall_rate"])
    d_a = float(full_new["A_recall_rate"] - full_old["A_recall_rate"])

    primary = df_miss[df_miss["reason_group"] == "primary"].sort_values("miss_count", ascending=False)
    top_reason = primary.iloc[0]["reason"] if not primary.empty else "NA"

    lines = [
        "# 新主线全年漏抓复核",
        "",
        "## 结论摘要",
        f"- 新主线（C2A+ECH2_Q2）对全年 A_high 召回相对 C2A 提升：{d_ah:+.2%}（A 召回提升 {d_a:+.2%}）",
        f"- 当前剩余 A_high 最大漏抓源：{top_reason}",
        "- 下一步仍应优先修召回，不应恢复买点开发。",
        "",
        "## 四问直答",
        f"1. 新主线 A_high 召回是否实质改善：{'是' if d_ah > 0 else '否'}",
        f"2. 当前剩余最大漏抓源头：{top_reason}",
        "3. 下一步是否还必须继续修召回：是",
        "4. 当前是否还应该继续买点开发：不应该",
        "",
        "## Archetype 覆盖增量（C2A+ECH2_Q2 - C2A）",
    ]
    for _, r in df_arch.iterrows():
        lines.append(f"- {r['archetype']}: {r['coverage_delta']:+.2%}")

    OUT_REVIEW.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    base = load_universe()
    base = add_quality_labels(base)

    cfg_c2a = CoreConfig(
        name="C2A",
        note="frozen single-channel baseline",
        quota_a=2,
        quota_b=3,
        cutoff_a=0.20,
        cutoff_b=0.20,
        path_a_rs20_min=0.72,
        path_a_trend_min=0.02,
        path_b_rs20_min=0.60,
        path_b_trend_min=0.00,
    )
    d = run_selector_core(base, cfg_c2a)
    d = build_new_mainline(d)

    mapping_cols = [
        "trade_date",
        "stock_code",
        "stock_name",
        "label_class",
        "label_A_high",
        "path_source",
        "in_C2A",
        "in_ECH2_Q2",
        "in_mainline_current",
        "score_total",
        "score_platform_axis_single",
        "score_industry_axis_single",
        "f_chip_winner_rate",
        "f_platform_compress_ratio",
        "rank_global_after_merge",
    ]
    d[mapping_cols].to_csv(OUT_MAPPING, index=False, encoding="utf-8-sig")

    recall_rows = []
    recall_rows.extend(_recall_block(d, "full_year", pd.Series(True, index=d.index)))
    recall_rows.extend(_recall_block(d, "main_window", _window_mask(d, MAIN_FROM, MAIN_TO)))
    recall_rows.extend(_recall_block(d, "confirm_window", _window_mask(d, CONFIRM_FROM, CONFIRM_TO)))
    recall_df = pd.DataFrame(recall_rows)
    recall_df.to_csv(OUT_RECALL, index=False, encoding="utf-8-sig")

    miss_df = miss_reason_breakdown(d)
    miss_df.to_csv(OUT_MISS, index=False, encoding="utf-8-sig")

    arch_df = archetype_recheck(d)
    arch_df.to_csv(OUT_ARCH, index=False, encoding="utf-8-sig")

    write_review(recall_df, miss_df, arch_df)

    print(str(OUT_MAPPING))
    print(str(OUT_RECALL))
    print(str(OUT_MISS))
    print(str(OUT_ARCH))
    print(str(OUT_REVIEW))


if __name__ == "__main__":
    main()

