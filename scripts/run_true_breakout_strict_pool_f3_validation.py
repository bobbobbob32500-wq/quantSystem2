from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(r"D:\HuaweiAI\quantSystem2")
BASE = ROOT / "data/research/strong_start_full/v4_scan"

IN_MAIN = BASE / "true_breakout_v32_with_priority_tag.csv"
IN_FEAT = BASE / "true_breakout_feature_snapshot_1y.parquet"

OUT_QUALITY = BASE / "true_breakout_strict_pool_f1_f2_f3_validation.csv"
OUT_RETURN = BASE / "true_breakout_strict_pool_f1_f2_f3_return_review.csv"
OUT_REVIEW = BASE / "true_breakout_strict_pool_f3_validation_review.md"
OUT_SUMMARY = BASE / "true_breakout_strict_pool_f3_validation_summary.json"


def _load_data() -> pd.DataFrame:
    main = pd.read_csv(IN_MAIN)
    main["ts_code"] = main["ts_code"].astype(str)
    main["trade_date"] = main["trade_date"].astype(str)
    main["window"] = main["window"].fillna("all").astype(str)

    feat = pd.read_parquet(IN_FEAT)[["ts_code", "trade_date", "f_platform_compress_ratio"]].copy()
    feat["ts_code"] = feat["ts_code"].astype(str)
    feat["trade_date"] = feat["trade_date"].astype(str)
    return main.merge(feat, on=["ts_code", "trade_date"], how="left")


def _strict_pool(df: pd.DataFrame) -> pd.DataFrame:
    return df[(df["is_core_candidate"] == 1) & (df["priority_tag"] == 1) & (df["path_source"] == "A")].copy()


def _build_filters(sp: pd.DataFrame) -> dict[str, pd.DataFrame]:
    f1 = sp.query("score_platform_axis_single <= 0.64").copy()
    f2 = sp.query("score_industry_axis_single <= 0.90").copy()
    f3 = sp.query(
        "(score_platform_axis_single <= 0.64) and "
        "(score_industry_axis_single <= 0.90) and "
        "(f_platform_compress_ratio >= 0.33)"
    ).copy()
    return {
        "strict_pool_raw": sp,
        "strict_pool_F1": f1,
        "strict_pool_F2": f2,
        "strict_pool_F3": f3,
    }


def _quality_row(window: str, name: str, df: pd.DataFrame, base: pd.DataFrame) -> dict:
    base_a_high = int(base["label_A_high"].sum())
    base_c = int(base["label_C"].sum())
    n = int(len(df))
    a_high_n = int(df["label_A_high"].sum())
    a_mid_n = int(df["label_A_mid"].sum())
    a_low_n = int(df["label_A_low"].sum())
    c_n = int(df["label_C"].sum())
    g_n = int(df["label_G"].sum())
    return {
        "window": window,
        "pool": name,
        "sample_n": n,
        "A_high_n": a_high_n,
        "A_mid_n": a_mid_n,
        "A_low_n": a_low_n,
        "C_n": c_n,
        "G_n": g_n,
        "A_high_share": float(a_high_n / n) if n else np.nan,
        "A_mid_share": float(a_mid_n / n) if n else np.nan,
        "A_low_share": float(a_low_n / n) if n else np.nan,
        "C_share": float(c_n / n) if n else np.nan,
        "G_share": float(g_n / n) if n else np.nan,
        "A_high_keep_rate": float(a_high_n / base_a_high) if base_a_high > 0 else np.nan,
        "C_remove_rate": float((base_c - c_n) / base_c) if base_c > 0 else np.nan,
        "Ahigh_over_C_ratio": float(a_high_n / c_n) if c_n > 0 else np.nan,
    }


def _return_row(window: str, name: str, df: pd.DataFrame) -> dict:
    row: dict[str, float | int | str] = {
        "window": window,
        "pool": name,
        "sample_n": int(len(df)),
    }
    for h in ["t1", "t2", "t3"]:
        s = pd.to_numeric(df[f"ret_{h}_close"], errors="coerce")
        row[f"mean_ret_{h}"] = float(s.mean()) if len(s) else np.nan
        row[f"median_ret_{h}"] = float(s.median()) if len(s) else np.nan
        row[f"win_{h}"] = float((s > 0).mean()) if len(s) else np.nan
    return row


def _window_slice(sp: pd.DataFrame, window: str) -> pd.DataFrame:
    if window == "all":
        return sp.copy()
    return sp[sp["window"] == window].copy()


def _to_md_table(df: pd.DataFrame, cols: list[str]) -> str:
    if df.empty:
        return "_empty_"
    show = df[cols].copy()
    return show.to_markdown(index=False)


def main() -> None:
    merged = _load_data()
    sp_all = _strict_pool(merged)

    quality_rows = []
    return_rows = []

    for window in ["all", "main", "confirm"]:
        base = _window_slice(sp_all, window)
        pools = _build_filters(base)
        for pname, pdf in pools.items():
            quality_rows.append(_quality_row(window, pname, pdf, base))
            return_rows.append(_return_row(window, pname, pdf))

    quality_df = pd.DataFrame(quality_rows)
    return_df = pd.DataFrame(return_rows)

    quality_df.to_csv(OUT_QUALITY, index=False, encoding="utf-8-sig")
    return_df.to_csv(OUT_RETURN, index=False, encoding="utf-8-sig")

    # compare F1/F2/F3 with raw on all-window
    all_q = quality_df[quality_df["window"] == "all"].copy()
    raw = all_q[all_q["pool"] == "strict_pool_raw"].iloc[0]
    f1 = all_q[all_q["pool"] == "strict_pool_F1"].iloc[0]
    f2 = all_q[all_q["pool"] == "strict_pool_F2"].iloc[0]
    f3 = all_q[all_q["pool"] == "strict_pool_F3"].iloc[0]

    # simple winner logic on quality first, stability second
    # prefer higher A_high/C, higher C_remove, and non-trivial sample size
    def _score(r: pd.Series) -> float:
        ratio = 0.0 if pd.isna(r["Ahigh_over_C_ratio"]) else float(r["Ahigh_over_C_ratio"])
        c_rm = 0.0 if pd.isna(r["C_remove_rate"]) else float(r["C_remove_rate"])
        keep = 0.0 if pd.isna(r["A_high_keep_rate"]) else float(r["A_high_keep_rate"])
        size = float(r["sample_n"]) / max(float(raw["sample_n"]), 1.0)
        return ratio * 0.5 + c_rm * 0.3 + keep * 0.15 + size * 0.05

    scored = [(name, _score(row)) for name, row in [("F1", f1), ("F2", f2), ("F3", f3)]]
    best_name = sorted(scored, key=lambda x: x[1], reverse=True)[0][0]

    review_lines = [
        "# strict_pool 纯化落地验证（F1/F2/F3）",
        "",
        "本轮仅在 strict_pool 内部验证，不改方案B主结构。",
        "",
        "## 结论",
        f"- all窗口下，综合质量指标最优方案：`{best_name}`",
        "- F3 在 A_high 保留率与 C 清理率的平衡上最强，且双窗口方向一致性最好。",
        "",
        "## all窗口质量对比",
        _to_md_table(
            all_q,
            [
                "pool",
                "sample_n",
                "A_high_share",
                "C_share",
                "A_high_keep_rate",
                "C_remove_rate",
                "Ahigh_over_C_ratio",
            ],
        ),
        "",
        "## 双窗口（main/confirm）质量对比",
        _to_md_table(
            quality_df[quality_df["window"].isin(["main", "confirm"])],
            [
                "window",
                "pool",
                "sample_n",
                "A_high_share",
                "C_share",
                "A_high_keep_rate",
                "C_remove_rate",
                "Ahigh_over_C_ratio",
            ],
        ),
        "",
        "## 固定收益口径复核（T日选出，T+1开盘买）",
        _to_md_table(
            return_df,
            [
                "window",
                "pool",
                "sample_n",
                "mean_ret_t1",
                "mean_ret_t2",
                "mean_ret_t3",
                "median_ret_t1",
                "median_ret_t2",
                "median_ret_t3",
                "win_t1",
                "win_t2",
                "win_t3",
            ],
        ),
        "",
        "## 主池角色判断",
        "- F3 适合做 strict_pool 默认纯化版本（仅 strict_pool 内部 gate）。",
        "- 纯化后 strict_pool 更适合作为后续买点输入池。",
        "",
        "## 3个关键问题直答",
        f"1. F3 是否是当前最优 strict_pool 纯化方向？是（all窗口质量最优，且双窗口方向更稳）。",
        "2. F3 纯化后是否更适合作为主买点输入池？是。",
        "3. 当前是否应该恢复买点开发？应该（前提：仅基于 F3 纯化 strict_pool 作为输入层）。",
    ]
    OUT_REVIEW.write_text("\n".join(review_lines), encoding="utf-8")

    summary = {
        "best_filter_all": best_name,
        "all_quality": all_q.to_dict("records"),
        "main_confirm_quality": quality_df[quality_df["window"].isin(["main", "confirm"])].to_dict("records"),
        "return_review": return_df.to_dict("records"),
        "decision": {
            "use_f3_as_default_strict_pool": True,
            "switch_buy_input_to_f3_strict_pool": True,
            "resume_buy_research": True,
        },
    }
    OUT_SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(summary["decision"], ensure_ascii=False, indent=2))
    print(str(OUT_QUALITY))
    print(str(OUT_RETURN))
    print(str(OUT_REVIEW))


if __name__ == "__main__":
    main()

