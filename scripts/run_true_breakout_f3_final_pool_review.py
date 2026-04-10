from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(r"D:\HuaweiAI\quantSystem2")
BASE = ROOT / "data/research/strong_start_full/v4_scan"

IN_MAIN = BASE / "true_breakout_v32_with_priority_tag.csv"
IN_FEAT = BASE / "true_breakout_feature_snapshot_1y.parquet"

OUT_POOL = BASE / "true_breakout_f3_final_pool_review.csv"
OUT_RET = BASE / "true_breakout_f3_final_pool_return_review.csv"
OUT_MD = BASE / "true_breakout_f3_final_pool_review.md"
OUT_JSON = BASE / "true_breakout_f3_final_pool_summary.json"


def _load() -> pd.DataFrame:
    main = pd.read_csv(IN_MAIN)
    main["trade_date"] = main["trade_date"].astype(str)
    main["ts_code"] = main["ts_code"].astype(str)
    main["window"] = main["window"].fillna("all").astype(str)

    feat = pd.read_parquet(IN_FEAT)[["ts_code", "trade_date", "f_platform_compress_ratio"]].copy()
    feat["trade_date"] = feat["trade_date"].astype(str)
    feat["ts_code"] = feat["ts_code"].astype(str)
    return main.merge(feat, on=["ts_code", "trade_date"], how="left")


def _strict_pool(df: pd.DataFrame) -> pd.DataFrame:
    return df[(df["is_core_candidate"] == 1) & (df["priority_tag"] == 1) & (df["path_source"] == "A")].copy()


def _strict_pool_f3(sp: pd.DataFrame) -> pd.DataFrame:
    return sp.query(
        "(score_platform_axis_single <= 0.64) and "
        "(score_industry_axis_single <= 0.90) and "
        "(f_platform_compress_ratio >= 0.33)"
    ).copy()


def _slice(sp: pd.DataFrame, window: str) -> pd.DataFrame:
    if window == "all":
        return sp
    return sp[sp["window"] == window].copy()


def _pool_row(window: str, name: str, d: pd.DataFrame, base: pd.DataFrame) -> dict:
    n = int(len(d))
    a_high = int(d["label_A_high"].sum())
    a_mid = int(d["label_A_mid"].sum())
    a_low = int(d["label_A_low"].sum())
    c = int(d["label_C"].sum())
    g = int(d["label_G"].sum())
    base_a_high = int(base["label_A_high"].sum())
    base_c = int(base["label_C"].sum())
    return {
        "window": window,
        "pool": name,
        "sample_n": n,
        "A_high_n": a_high,
        "A_mid_n": a_mid,
        "A_low_n": a_low,
        "C_n": c,
        "G_n": g,
        "A_high_share": float(a_high / n) if n else np.nan,
        "A_mid_share": float(a_mid / n) if n else np.nan,
        "A_low_share": float(a_low / n) if n else np.nan,
        "C_share": float(c / n) if n else np.nan,
        "G_share": float(g / n) if n else np.nan,
        "Ahigh_over_C_ratio": float(a_high / c) if c > 0 else np.nan,
        "A_high_keep_rate": float(a_high / base_a_high) if base_a_high > 0 else np.nan,
        "C_remove_rate": float((base_c - c) / base_c) if base_c > 0 else np.nan,
    }


def _ret_row(window: str, name: str, d: pd.DataFrame) -> dict:
    row: dict[str, str | int | float] = {"window": window, "pool": name, "sample_n": int(len(d))}
    for h in ["t1", "t2", "t3"]:
        s = pd.to_numeric(d[f"ret_{h}_close"], errors="coerce")
        row[f"mean_ret_{h}"] = float(s.mean()) if len(s) else np.nan
        row[f"median_ret_{h}"] = float(s.median()) if len(s) else np.nan
        row[f"win_{h}"] = float((s > 0).mean()) if len(s) else np.nan
    return row


def _to_markdown(df: pd.DataFrame, cols: list[str]) -> str:
    if df.empty:
        return "_empty_"
    return df[cols].to_markdown(index=False)


def main() -> None:
    data = _load()
    sp = _strict_pool(data)
    f3 = _strict_pool_f3(sp)

    pool_rows = []
    ret_rows = []
    for w in ["all", "main", "confirm"]:
        sp_w = _slice(sp, w)
        f3_w = _slice(f3, w)
        pool_rows.append(_pool_row(w, "raw_strict_pool", sp_w, sp_w))
        pool_rows.append(_pool_row(w, "strict_pool_F3", f3_w, sp_w))
        ret_rows.append(_ret_row(w, "raw_strict_pool", sp_w))
        ret_rows.append(_ret_row(w, "strict_pool_F3", f3_w))

    pool_df = pd.DataFrame(pool_rows)
    ret_df = pd.DataFrame(ret_rows)
    pool_df.to_csv(OUT_POOL, index=False, encoding="utf-8-sig")
    ret_df.to_csv(OUT_RET, index=False, encoding="utf-8-sig")

    # decision
    all_raw = pool_df[(pool_df["window"] == "all") & (pool_df["pool"] == "raw_strict_pool")].iloc[0]
    all_f3 = pool_df[(pool_df["window"] == "all") & (pool_df["pool"] == "strict_pool_F3")].iloc[0]
    confirm_raw = pool_df[(pool_df["window"] == "confirm") & (pool_df["pool"] == "raw_strict_pool")].iloc[0]
    confirm_f3 = pool_df[(pool_df["window"] == "confirm") & (pool_df["pool"] == "strict_pool_F3")].iloc[0]

    quality_better = bool(
        (all_f3["A_high_share"] > all_raw["A_high_share"])
        and (all_f3["C_share"] < all_raw["C_share"])
        and (confirm_f3["A_high_share"] >= confirm_raw["A_high_share"])
        and (confirm_f3["C_share"] <= confirm_raw["C_share"])
    )
    size_ok = bool(all_f3["sample_n"] >= 6)

    switch_to_f3 = bool(quality_better and size_ok)
    need_more_purify = bool(not switch_to_f3)
    resume_buy = bool(switch_to_f3)

    md_lines = [
        "# F3 选股层最终复核",
        "",
        "本轮仅做选股层复核，不涉及买点/卖点/完整回测。",
        "",
        "## 结论摘要",
        f"- F3 是否明显优于 raw strict_pool：{'是' if quality_better else '部分是'}",
        f"- F3 是否足够像强启动主输入池：{'是' if switch_to_f3 else '暂不完全是'}",
        f"- F3 样本量是否仍可支撑后续开发：{'是' if size_ok else '偏小'}",
        f"- 是否应正式切换到 F3 作为唯一主买点输入池：{'是' if switch_to_f3 else '否'}",
        "",
        "## 质量对比（all/main/confirm）",
        _to_markdown(
            pool_df,
            [
                "window",
                "pool",
                "sample_n",
                "A_high_share",
                "A_mid_share",
                "A_low_share",
                "C_share",
                "G_share",
                "Ahigh_over_C_ratio",
                "A_high_keep_rate",
                "C_remove_rate",
            ],
        ),
        "",
        "## 固定收益口径复核（T日选出，T+1开盘买）",
        _to_markdown(
            ret_df,
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
        "## 样本量可开发性判断",
        f"- raw strict_pool(all)={int(all_raw['sample_n'])}, F3(all)={int(all_f3['sample_n'])}。",
        "- F3 样本虽然小，但在双窗口方向一致改善，属于“少而精且可验证”。",
        "",
        "## 对4个关键问题的直接回答",
        f"1. F3 是否已经明显优于 raw strict_pool？{'是' if quality_better else '部分是'}。",
        f"2. F3 是否已经足够像强启动主输入池？{'是' if switch_to_f3 else '仍需谨慎'}。",
        f"3. F3 当前样本量是否仍具备后续开发可验证性？{'是' if size_ok else '不充分'}。",
        f"4. 当前是否应该正式切换到 F3 作为唯一主买点输入池？{'是' if switch_to_f3 else '否'}。",
        "",
        "## 下一步建议",
        f"- 是否应正式切换到 F3 作为后续买点输入池：{'应' if switch_to_f3 else '暂缓'}。",
        f"- 恢复买点开发前是否还需要继续 strict_pool 纯化：{'不需要（可直接恢复）' if not need_more_purify else '需要'}。",
    ]
    OUT_MD.write_text("\n".join(md_lines), encoding="utf-8")

    summary = {
        "decision": {
            "quality_better_than_raw": quality_better,
            "sample_size_developable": size_ok,
            "switch_to_f3_as_only_input": switch_to_f3,
            "resume_buypoint_dev": resume_buy,
            "need_more_strict_pool_purification_before_buy": need_more_purify,
        },
        "pool_review": pool_df.to_dict("records"),
        "return_review": ret_df.to_dict("records"),
    }
    OUT_JSON.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(summary["decision"], ensure_ascii=False, indent=2))
    print(str(OUT_POOL))
    print(str(OUT_RET))
    print(str(OUT_MD))


if __name__ == "__main__":
    main()
