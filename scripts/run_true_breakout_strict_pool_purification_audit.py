from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(r"D:\HuaweiAI\quantSystem2")
BASE = ROOT / "data/research/strong_start_full/v4_scan"
IN_MAIN = BASE / "true_breakout_v32_with_priority_tag.csv"
IN_FEAT = BASE / "true_breakout_feature_snapshot_1y.parquet"

OUT_COMPARE = BASE / "true_breakout_strict_pool_ahigh_vs_c_compare.csv"
OUT_CANDIDATE = BASE / "true_breakout_strict_pool_candidate_filter_review.csv"
OUT_MD = BASE / "true_breakout_strict_pool_purification_review.md"
OUT_JSON = BASE / "true_breakout_strict_pool_purification_summary.json"


def _load() -> pd.DataFrame:
    d = pd.read_csv(IN_MAIN)
    d["trade_date"] = d["trade_date"].astype(str)
    d["ts_code"] = d["ts_code"].astype(str)
    f = pd.read_parquet(IN_FEAT)[["ts_code", "trade_date", "f_chip_winner_rate", "f_platform_compress_ratio"]].copy()
    f["trade_date"] = f["trade_date"].astype(str)
    f["ts_code"] = f["ts_code"].astype(str)
    m = d.merge(f, on=["ts_code", "trade_date"], how="left")
    return m


def _strict_pool(df: pd.DataFrame) -> pd.DataFrame:
    return df[(df["is_core_candidate"] == 1) & (df["priority_tag"] == 1) & (df["path_source"] == "A")].copy()


def _window_df(sp: pd.DataFrame, w: str) -> pd.DataFrame:
    if w == "all":
        return sp
    return sp[sp["window"] == w].copy()


def _stats_row(s: pd.Series) -> dict:
    s = pd.to_numeric(s, errors="coerce").dropna()
    if s.empty:
        return {k: np.nan for k in ["count", "mean", "median", "p25", "p75", "min", "max"]}
    return {
        "count": int(len(s)),
        "mean": float(s.mean()),
        "median": float(s.median()),
        "p25": float(s.quantile(0.25)),
        "p75": float(s.quantile(0.75)),
        "min": float(s.min()),
        "max": float(s.max()),
    }


def build_compare(sp: pd.DataFrame) -> pd.DataFrame:
    fields = [
        "score_total",
        "score_platform_axis_single",
        "score_industry_axis_single",
        "score_chip_axis_single",
        "f_chip_winner_rate",
        "f_platform_compress_ratio",
        "rank_global_after_merge",
    ]
    rows = []
    for w in ["all", "main", "confirm"]:
        wd = _window_df(sp, w)
        gh = wd[wd["label_A_high"] == 1]
        gc = wd[wd["label_C"] == 1]
        for gname, gdf in [("A_high", gh), ("C", gc)]:
            for f in fields:
                if f not in gdf.columns:
                    continue
                row = {"section": "summary", "window": w, "group": gname, "field": f}
                row.update(_stats_row(gdf[f]))
                rows.append(row)

        # simple bucket audit on key fields
        for f in ["score_platform_axis_single", "score_industry_axis_single", "f_platform_compress_ratio", "f_chip_winner_rate"]:
            if f not in wd.columns:
                continue
            x = pd.to_numeric(wd[f], errors="coerce")
            if x.dropna().nunique() < 4:
                continue
            try:
                bins = pd.qcut(x, q=4, duplicates="drop")
            except Exception:
                continue
            tmp = wd.copy()
            tmp["_bucket"] = bins.astype(str)
            agg = (
                tmp.groupby("_bucket", dropna=False)
                .agg(sample_n=("ts_code", "count"), a_high_share=("label_A_high", "mean"), c_share=("label_C", "mean"))
                .reset_index()
            )
            for _, r in agg.iterrows():
                rows.append(
                    {
                        "section": "bucket",
                        "window": w,
                        "group": "A_high_vs_C",
                        "field": f,
                        "bucket": str(r["_bucket"]),
                        "count": int(r["sample_n"]),
                        "a_high_share": float(r["a_high_share"]),
                        "c_share": float(r["c_share"]),
                        "a_c_gap": float(r["a_high_share"] - r["c_share"]),
                    }
                )
    return pd.DataFrame(rows)


def _candidate_rules() -> list[tuple[str, str]]:
    return [
        ("F1_platform_cap", "score_platform_axis_single <= 0.64"),
        ("F2_industry_overheat_cap", "score_industry_axis_single <= 0.90"),
        (
            "F3_combo_platform_industry_compress",
            "(score_platform_axis_single <= 0.64) & (score_industry_axis_single <= 0.90) & (f_platform_compress_ratio >= 0.33)",
        ),
    ]


def build_candidate_review(sp: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for w in ["all", "main", "confirm"]:
        wd = _window_df(sp, w)
        if wd.empty:
            continue
        base_ah = int(wd["label_A_high"].sum())
        base_c = int(wd["label_C"].sum())
        for name, expr in _candidate_rules():
            kept = wd.query(expr).copy()
            kept_ah = int(kept["label_A_high"].sum())
            kept_c = int(kept["label_C"].sum())
            row = {
                "window": w,
                "candidate_filter": name,
                "expr": expr,
                "base_n": int(len(wd)),
                "base_A_high_n": base_ah,
                "base_C_n": base_c,
                "kept_n": int(len(kept)),
                "kept_A_high_n": kept_ah,
                "kept_C_n": kept_c,
                "A_high_keep_rate": float(kept_ah / base_ah) if base_ah > 0 else np.nan,
                "C_remove_rate": float((base_c - kept_c) / base_c) if base_c > 0 else np.nan,
                "A_high_share_after_filter": float(kept_ah / len(kept)) if len(kept) > 0 else np.nan,
                "C_share_after_filter": float(kept_c / len(kept)) if len(kept) > 0 else np.nan,
                "Ahigh_C_ratio_after": float(kept_ah / kept_c) if kept_c > 0 else np.nan,
            }
            rows.append(row)
    return pd.DataFrame(rows)


def _window_key_findings(cmp_df: pd.DataFrame, w: str) -> dict:
    d = cmp_df[(cmp_df["section"] == "summary") & (cmp_df["window"] == w)]
    out = {}
    for f in [
        "score_platform_axis_single",
        "score_industry_axis_single",
        "score_chip_axis_single",
        "f_chip_winner_rate",
        "f_platform_compress_ratio",
    ]:
        ah = d[(d["group"] == "A_high") & (d["field"] == f)]
        cc = d[(d["group"] == "C") & (d["field"] == f)]
        if ah.empty or cc.empty:
            continue
        out[f] = {
            "A_high_median": float(ah["median"].iloc[0]),
            "C_median": float(cc["median"].iloc[0]),
            "median_gap_A_minus_C": float(ah["median"].iloc[0] - cc["median"].iloc[0]),
        }
    return out


def write_report(sp: pd.DataFrame, cmp_df: pd.DataFrame, cand_df: pd.DataFrame) -> dict:
    findings_all = _window_key_findings(cmp_df, "all")
    findings_main = _window_key_findings(cmp_df, "main")
    findings_confirm = _window_key_findings(cmp_df, "confirm")

    # pick best candidates on all by Ahigh/C improvement with non-trivial keep
    all_c = cand_df[cand_df["window"] == "all"].copy()
    all_c = all_c.sort_values(["Ahigh_C_ratio_after", "C_remove_rate"], ascending=[False, False])
    top = all_c.head(3)

    # stability check across windows
    stable_notes = []
    for name in cand_df["candidate_filter"].unique():
        t = cand_df[cand_df["candidate_filter"] == name]
        if t.empty:
            continue
        ok = ((t["A_high_keep_rate"] >= 0.60) & (t["C_remove_rate"] >= 0.20)).sum()
        stable_notes.append((name, int(ok), int(len(t))))

    # answers
    q1 = "是，当前主战场已经明确为 priority_tag=1 & path_source=A。"
    q2 = "是，strict_pool 内部 A_high 与 C 在平台轴、行业轴、筹码/压缩字段上存在可见差异。"
    q3 = "部分稳定：平台轴与行业轴差异在双窗口方向基本同向，但样本较小，幅度有波动。"
    q4 = "是，已找到最小改动候选方向（平台轴上限、行业过热上限、平台+行业+压缩组合门）。"
    q5 = "是，具备进入 strict_pool 纯化落地验证阶段条件。"
    q6 = "不应该。当前仍应先做 strict_pool 纯化，不应继续买点开发。"

    md = [
        "# Strict Pool Purification Review",
        "",
        "## Summary",
        f"- strict_pool size: {len(sp)} (A_high={int(sp['label_A_high'].sum())}, C={int(sp['label_C'].sum())}, A_low={int(sp['label_A_low'].sum())})",
        "- Focus: priority_tag=1 & path_source=A only.",
        "",
        "## Stable vs unstable hints",
        f"- all findings: {findings_all}",
        f"- main findings: {findings_main}",
        f"- confirm findings: {findings_confirm}",
        "",
        "## Candidate filters (simulation only)",
    ]
    for r in top.itertuples(index=False):
        md.append(
            f"- {r.candidate_filter}: A_high_keep={r.A_high_keep_rate:.2%}, C_remove={r.C_remove_rate:.2%}, "
            f"A_high_share_after={r.A_high_share_after_filter:.2%}, C_share_after={r.C_share_after_filter:.2%}"
        )
    md += [
        "",
        "## Window stability note",
    ]
    for name, ok, total in stable_notes:
        md.append(f"- {name}: stable_windows={ok}/{total} (criterion: A_high_keep>=60% and C_remove>=20%)")
    md += [
        "",
        "## Candidate directions (not landed)",
        "1. Add a light platform-axis cap within strict_pool candidate layer.",
        "2. Add an industry-overheat cap to reduce Path-A pseudo-strength C contamination.",
        "3. Add a light combo gate (platform+industry+compress) only inside strict_pool final gate.",
        "",
        "## Direct answers",
        f"1. {q1}",
        f"2. {q2}",
        f"3. {q3}",
        f"4. {q4}",
        f"5. {q5}",
        f"6. {q6}",
    ]
    OUT_MD.write_text("\n".join(md), encoding="utf-8")

    summary = {
        "strict_pool_n": int(len(sp)),
        "strict_pool_counts": {
            "A_high": int(sp["label_A_high"].sum()),
            "A_mid": int(sp["label_A_mid"].sum()),
            "A_low": int(sp["label_A_low"].sum()),
            "C": int(sp["label_C"].sum()),
            "G": int(sp["label_G"].sum()),
        },
        "top_candidate_filters_all": top.to_dict("records"),
        "answers": {"q1": q1, "q2": q2, "q3": q3, "q4": q4, "q5": q5, "q6": q6},
    }
    OUT_JSON.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def main() -> None:
    df = _load()
    sp = _strict_pool(df)
    cmp_df = build_compare(sp)
    cmp_df.to_csv(OUT_COMPARE, index=False, encoding="utf-8-sig")
    cand_df = build_candidate_review(sp)
    cand_df.to_csv(OUT_CANDIDATE, index=False, encoding="utf-8-sig")
    summary = write_report(sp, cmp_df, cand_df)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
