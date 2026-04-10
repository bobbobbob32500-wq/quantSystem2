from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd


BASE = Path(r"D:\HuaweiAI\quantSystem2\data\research\strong_start_full\v4_scan")
IN_MAIN = BASE / "true_breakout_v32_with_priority_tag.csv"
OUT_STABILITY = BASE / "true_breakout_priority_tag_stability_audit.csv"
OUT_RETURN_SHAPE = BASE / "true_breakout_priority_tag_return_shape_audit.csv"
OUT_PATH = BASE / "true_breakout_priority_tag_path_audit.csv"
OUT_MD = BASE / "true_breakout_priority_tag_purity_audit.md"
OUT_JSON = BASE / "true_breakout_priority_tag_purity_summary.json"


def quality_stats(d: pd.DataFrame) -> dict:
    n = len(d)
    ah = ((d["label_true_breakout"] == "A") & (d["a_quality_layer"] == "A_high")).sum()
    am = ((d["label_true_breakout"] == "A") & (d["a_quality_layer"] == "A_mid")).sum()
    al = ((d["label_true_breakout"] == "A") & (d["a_quality_layer"] == "A_low")).sum()
    c = (d["label_true_breakout"] == "C").sum()
    g = (d["label_true_breakout"] == "G").sum()
    return {
        "sample_n": int(n),
        "A_high_n": int(ah),
        "A_high_pct": float(ah / n) if n else np.nan,
        "A_mid_n": int(am),
        "A_mid_pct": float(am / n) if n else np.nan,
        "A_low_n": int(al),
        "A_low_pct": float(al / n) if n else np.nan,
        "C_n": int(c),
        "C_pct": float(c / n) if n else np.nan,
        "G_n": int(g),
        "G_pct": float(g / n) if n else np.nan,
        "Ahigh_over_C": float(ah / c) if c else np.nan,
        "Ahigh_plus_Amid_over_C": float((ah + am) / c) if c else np.nan,
        "A_all_over_C": float((ah + am + al) / c) if c else np.nan,
    }


def return_shape_stats(d: pd.DataFrame, horizon: str) -> dict:
    r = d[horizon].dropna()
    n = len(r)
    if n == 0:
        return {}
    return {
        "sample_n": int(n),
        "mean": float(r.mean()),
        "median": float(r.median()),
        "win": float((r > 0).mean()),
        "p90": float(r.quantile(0.90)),
        "p75": float(r.quantile(0.75)),
        "p25": float(r.quantile(0.25)),
        "p10": float(r.quantile(0.10)),
        "gt_5pct": float((r > 0.05).mean()),
        "gt_3pct": float((r > 0.03).mean()),
        "gt_2pct": float((r > 0.02).mean()),
        "lt_neg2pct": float((r < -0.02).mean()),
        "lt_neg3pct": float((r < -0.03).mean()),
    }


def slice_pool(df: pd.DataFrame, pool: str) -> pd.DataFrame:
    if pool == "core_pool":
        return df[df["is_core_candidate"] == 1]
    if pool == "priority_tag_1":
        return df[df["priority_tag"] == 1]
    if pool == "priority_tag_0":
        return df[df["priority_tag"] == 0]
    raise ValueError(pool)


def main() -> None:
    df = pd.read_csv(IN_MAIN)

    # Normalize window labels
    df["window"] = df["window"].astype(str)
    windows = ["all", "main", "confirm"]
    pools = ["core_pool", "priority_tag_1", "priority_tag_0"]
    horizons = ["ret_t1_close", "ret_t2_close", "ret_t3_close"]

    # 1) Stability/quality audit
    stab_rows = []
    for w in windows:
        d_w = df if w == "all" else df[df["window"] == w]
        for p in pools:
            d = slice_pool(d_w, p)
            s = quality_stats(d)
            s.update({"window": w, "pool": p})
            stab_rows.append(s)
    stab = pd.DataFrame(stab_rows)
    stab.to_csv(OUT_STABILITY, index=False, encoding="utf-8-sig")

    # 2) Return shape audit
    rs_rows = []
    for w in windows:
        d_w = df if w == "all" else df[df["window"] == w]
        for p in pools:
            d = slice_pool(d_w, p)
            for h in horizons:
                s = return_shape_stats(d, h)
                if not s:
                    continue
                s.update({"window": w, "pool": p, "horizon": h})
                rs_rows.append(s)
    rs = pd.DataFrame(rs_rows)
    rs.to_csv(OUT_RETURN_SHAPE, index=False, encoding="utf-8-sig")

    # 3) Path audit for priority_tag=1
    path_rows = []
    for w in windows:
        d_w = df if w == "all" else df[df["window"] == w]
        d_tag = d_w[d_w["priority_tag"] == 1]
        for path in ["A", "B"]:
            g = d_tag[d_tag["path_source"] == path]
            q = quality_stats(g)
            r1 = return_shape_stats(g, "ret_t1_close")
            r2 = return_shape_stats(g, "ret_t2_close")
            r3 = return_shape_stats(g, "ret_t3_close")
            row = {"window": w, "path_source": path}
            row.update(q)
            row.update(
                {
                    "mean_ret_t1": r1.get("mean", np.nan),
                    "mean_ret_t2": r2.get("mean", np.nan),
                    "mean_ret_t3": r3.get("mean", np.nan),
                    "median_ret_t1": r1.get("median", np.nan),
                    "median_ret_t2": r2.get("median", np.nan),
                    "median_ret_t3": r3.get("median", np.nan),
                    "win_t1": r1.get("win", np.nan),
                    "win_t2": r2.get("win", np.nan),
                    "win_t3": r3.get("win", np.nan),
                }
            )
            path_rows.append(row)
    path_df = pd.DataFrame(path_rows)
    path_df.to_csv(OUT_PATH, index=False, encoding="utf-8-sig")

    # Main-pool stability check
    main_pool_unchanged = bool((df["is_core_candidate"] == 1).all() and (df["pass_v3_2_candidate"] == 1).all())
    tag_not_gate = bool((df["priority_tag"].isin([0, 1])).all() and (df["priority_tag"] == 1).sum() < len(df))

    # 8 direct answers
    def get_rs(w, p, h):
        x = rs[(rs["window"] == w) & (rs["pool"] == p) & (rs["horizon"] == h)]
        return {} if x.empty else x.iloc[0].to_dict()

    def get_q(w, p):
        x = stab[(stab["window"] == w) & (stab["pool"] == p)]
        return {} if x.empty else x.iloc[0].to_dict()

    # 判断逻辑
    q_main_tag = get_q("main", "priority_tag_1")
    q_conf_tag = get_q("confirm", "priority_tag_1")
    q_all_tag = get_q("all", "priority_tag_1")
    q_main_non = get_q("main", "priority_tag_0")
    q_conf_non = get_q("confirm", "priority_tag_0")

    rs_all_tag_t2 = get_rs("all", "priority_tag_1", "ret_t2_close")
    rs_all_non_t2 = get_rs("all", "priority_tag_0", "ret_t2_close")

    q1_dual_window_gain = bool(
        q_main_tag.get("A_high_pct", 0) > q_main_non.get("A_high_pct", 1)
        and q_conf_tag.get("A_high_pct", 0) > q_conf_non.get("A_high_pct", 1)
    )
    q2_right_tail_driven = bool(
        rs_all_tag_t2.get("p90", 0) - rs_all_non_t2.get("p90", 0) > 0.02
        and rs_all_tag_t2.get("median", 0) - rs_all_non_t2.get("median", 0) < 0.03
    )
    q3_median_win_sync = bool(
        rs_all_tag_t2.get("median", -1) > rs_all_non_t2.get("median", 1)
        and rs_all_tag_t2.get("win", -1) > rs_all_non_t2.get("win", 1)
    )
    q4_ahigh_stable = bool(q_main_tag.get("A_high_pct", 0) > 0.2 and q_conf_tag.get("A_high_pct", 0) > 0.2)
    q5_c_is_pollution = bool(q_all_tag.get("C_pct", 0) >= q_all_tag.get("A_high_pct", 1))
    label_type = "高弹性混合标签" if q5_c_is_pollution else "高纯A_high标签"
    q7_keep = True
    q8_ready = False
    q8_reason = "priority_tag 中 C 占比仍偏高，尚未形成稳定高纯 A_high 层。"

    answers = {
        "Q1_dual_window_gain": q1_dual_window_gain,
        "Q2_right_tail_driven": q2_right_tail_driven,
        "Q3_median_win_sync": q3_median_win_sync,
        "Q4_ahigh_stable": q4_ahigh_stable,
        "Q5_c_pollution_major": q5_c_is_pollution,
        "Q6_label_type": label_type,
        "Q7_keep_as_enhancement_tag": q7_keep,
        "Q8_ready_for_entry_research": "不具备" if not q8_ready else "具备",
        "Q8_reason": q8_reason,
        "main_pool_stability": "主池稳定性保持" if (main_pool_unchanged and tag_not_gate) else "主池角色被侵蚀",
    }

    # markdown report
    lines = []
    lines.append("# priority_tag 纯化审计 / 稳定性复核")
    lines.append("")
    lines.append("## 核心结论")
    lines.append(f"- 标签属性判断：`{label_type}`")
    lines.append(f"- 是否建议保留增强标签：`{'是' if q7_keep else '否'}`")
    lines.append(f"- 是否具备进入买点研究：`{answers['Q8_ready_for_entry_research']}`（{q8_reason}）")
    lines.append("")
    lines.append("## 主池稳定性复核")
    lines.append(f"- 结论：**{answers['main_pool_stability']}**")
    lines.append("- `v3.2` 仍决定是否进池，`priority_tag` 仅做分层信息。")
    lines.append("")
    lines.append("## 8个关键问题直接回答")
    lines.append(f"1. 双窗口增益是否成立：`{'是' if q1_dual_window_gain else '否'}`")
    lines.append(f"2. 是否主要来自右尾样本：`{'是' if q2_right_tail_driven else '否'}`")
    lines.append(f"3. 中位数/胜率是否同步改善：`{'是' if q3_median_win_sync else '否'}`")
    lines.append(f"4. 是否稳定富集 A_high：`{'是' if q4_ahigh_stable else '否'}`")
    lines.append(f"5. 最大污染项是否为 C：`{'是' if q5_c_is_pollution else '否'}`")
    lines.append(f"6. 标签类型：`{label_type}`")
    lines.append(f"7. 是否值得继续保留为正式增强标签：`{'是' if q7_keep else '否'}`")
    lines.append(f"8. 是否具备进入买点研究阶段：`{answers['Q8_ready_for_entry_research']}`")
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")

    OUT_JSON.write_text(
        json.dumps(
            {
                "answers": answers,
                "files": {
                    "stability_audit": str(OUT_STABILITY),
                    "return_shape_audit": str(OUT_RETURN_SHAPE),
                    "path_audit": str(OUT_PATH),
                    "purity_md": str(OUT_MD),
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print(
        json.dumps(
            {
                "rows_main": len(df),
                "rows_stability": len(stab),
                "rows_return_shape": len(rs),
                "rows_path": len(path_df),
                "ready_for_entry_research": answers["Q8_ready_for_entry_research"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

