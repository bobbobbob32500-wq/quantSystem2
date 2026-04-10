from __future__ import annotations

from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(r"D:\HuaweiAI\quantSystem2")
BASE = ROOT / "data/research/strong_start_full/v4_scan"

IN_SELECTOR = BASE / "true_breakout_v32_with_priority_tag.csv"
IN_FEAT = BASE / "true_breakout_feature_snapshot_1y.parquet"

OUT_ALL_AHIGH = BASE / "true_breakout_all_ahigh_cases.csv"
OUT_RECALL = BASE / "true_breakout_ahigh_recall_audit.csv"
OUT_MISS = BASE / "true_breakout_ahigh_miss_reason_review.csv"
OUT_REVIEW = BASE / "true_breakout_ahigh_recall_review.md"


def _load() -> pd.DataFrame:
    d = pd.read_csv(IN_SELECTOR)
    d["ts_code"] = d["ts_code"].astype(str)
    d["trade_date"] = d["trade_date"].astype(str)

    feat = pd.read_parquet(IN_FEAT)[["ts_code", "trade_date", "f_platform_compress_ratio", "f_chip_winner_rate"]].copy()
    feat["ts_code"] = feat["ts_code"].astype(str)
    feat["trade_date"] = feat["trade_date"].astype(str)

    out = d.merge(feat, on=["ts_code", "trade_date"], how="left")
    if "stock_code" not in out.columns:
        out["stock_code"] = out["ts_code"]
    if "stock_name" not in out.columns:
        out["stock_name"] = out.get("name", "")
    out["stock_code"] = out["stock_code"].fillna(out["ts_code"]).astype(str)
    out["stock_name"] = out["stock_name"].fillna(out.get("name", "")).astype(str)
    return out


def _layer_masks(df: pd.DataFrame) -> dict[str, pd.Series]:
    core = pd.to_numeric(df["is_core_candidate"], errors="coerce").fillna(0).eq(1)
    prio = pd.to_numeric(df["priority_tag"], errors="coerce").fillna(0).eq(1)
    strict = prio & df["path_source"].astype(str).eq("A")
    f3 = (
        strict
        & (pd.to_numeric(df["score_platform_axis_single"], errors="coerce") <= 0.64)
        & (pd.to_numeric(df["score_industry_axis_single"], errors="coerce") <= 0.90)
        & (pd.to_numeric(df["f_platform_compress_ratio"], errors="coerce") >= 0.33)
    )
    return {"core_pool": core, "priority_tag_1": prio, "strict_pool": strict, "F3": f3}


def _build_all_ahigh(df: pd.DataFrame) -> pd.DataFrame:
    ah = df[pd.to_numeric(df["label_A_high"], errors="coerce").fillna(0).eq(1)].copy()
    cols = [
        "trade_date",
        "stock_code",
        "stock_name",
        "label_A_high",
        "path_source",
        "score_total",
        "score_platform_axis_single",
        "score_industry_axis_single",
        "f_chip_winner_rate",
        "f_platform_compress_ratio",
        "rank_global_after_merge",
        "window",
        "ts_code",
    ]
    for c in cols:
        if c not in ah.columns:
            ah[c] = pd.NA
    return ah[cols].copy()


def _build_recall_audit(ah: pd.DataFrame, masks: dict[str, pd.Series]) -> pd.DataFrame:
    rows: list[dict] = []
    windows = ["all", "main", "confirm"]
    for w in windows:
        if w == "all":
            base = ah
        else:
            base = ah[ah["window"].astype(str) == w]
        n = len(base)
        for layer, mask_all in masks.items():
            if w == "all":
                m = mask_all.loc[base.index]
            else:
                m = mask_all.loc[base.index]
            c = int(m.sum())
            rows.append(
                {
                    "window": w,
                    "layer": layer,
                    "total_ahigh_n": int(n),
                    "recall_count": c,
                    "recall_rate": float(c / n) if n else np.nan,
                    "miss_count": int(n - c),
                    "miss_rate": float((n - c) / n) if n else np.nan,
                }
            )
    return pd.DataFrame(rows)


def _build_miss_reason(ah: pd.DataFrame, masks: dict[str, pd.Series]) -> pd.DataFrame:
    core = masks["core_pool"].loc[ah.index]
    prio = masks["priority_tag_1"].loc[ah.index]
    strict = masks["strict_pool"].loc[ah.index]
    f3 = masks["F3"].loc[ah.index]
    path_a = ah["path_source"].astype(str).eq("A")

    # Exclusive funnel reasons.
    reason = np.full(len(ah), "", dtype=object)
    reason[~path_a] = "not_in_path_A"
    reason[path_a & ~core] = "not_in_core_pool"
    reason[path_a & core & ~prio] = "no_priority_tag"
    reason[path_a & core & prio & ~strict] = "excluded_by_strict_pool"
    reason[path_a & core & prio & strict & ~f3] = "failed_F3_gate"
    reason[path_a & core & prio & strict & f3] = "captured_by_F3"

    tmp = ah.copy()
    tmp["miss_reason"] = reason

    rows: list[dict] = []
    for w in ["all", "main", "confirm"]:
        sub = tmp if w == "all" else tmp[tmp["window"].astype(str) == w]
        n = len(sub)
        cnt = Counter(sub["miss_reason"].tolist())
        for k in [
            "captured_by_F3",
            "not_in_path_A",
            "not_in_core_pool",
            "no_priority_tag",
            "excluded_by_strict_pool",
            "failed_F3_gate",
        ]:
            c = int(cnt.get(k, 0))
            rows.append(
                {
                    "window": w,
                    "miss_reason": k,
                    "count": c,
                    "ratio_in_ahigh": float(c / n) if n else np.nan,
                }
            )
    return pd.DataFrame(rows)


def _write_review(ah: pd.DataFrame, recall: pd.DataFrame, miss: pd.DataFrame) -> None:
    def _get(layer: str, window: str, col: str) -> float:
        x = recall[(recall["layer"] == layer) & (recall["window"] == window)]
        if x.empty:
            return np.nan
        return float(x.iloc[0][col])

    def _get_miss(reason: str, window: str) -> float:
        x = miss[(miss["miss_reason"] == reason) & (miss["window"] == window)]
        if x.empty:
            return np.nan
        return float(x.iloc[0]["ratio_in_ahigh"])

    total = len(ah)
    f3_recall = _get("F3", "all", "recall_rate")
    core_recall = _get("core_pool", "all", "recall_rate")
    prio_recall = _get("priority_tag_1", "all", "recall_rate")
    strict_recall = _get("strict_pool", "all", "recall_rate")
    largest_miss = _get_miss("not_in_path_A", "all")

    lines = [
        "# A_high 全量召回审计",
        "",
        f"- A_high 总样本数: {total}",
        f"- core_pool 召回率: {core_recall:.2%}",
        f"- priority_tag=1 召回率: {prio_recall:.2%}",
        f"- strict_pool 召回率: {strict_recall:.2%}",
        f"- F3 召回率: {f3_recall:.2%}",
        "",
        "## 最大漏抓源头",
        f"- not_in_path_A 占 A_high 比例: {largest_miss:.2%}",
        "",
        "## 召回优先 candidate 方向（仅方向，不落地）",
        "1. 先提升 Path A 覆盖：当前主漏抓在 path 分流前，优先修复 A_high 到 Path A 的召回。",
        "2. 在 priority_tag 前增加 A_high 召回友好分层：降低对 path A 里中等强度 A_high 的早期漏失。",
        "3. F3 保持高纯定位不动，把“召回扩容”放在 F3 之前的层级完成。",
        "",
        "## 推进判断",
        "- 当前主线必须改成召回优先（先抓到，再纯化）。",
        "- 当前不应继续买点开发，先重建高召回强启动主线。",
    ]
    OUT_REVIEW.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    d = _load()
    ah = _build_all_ahigh(d)
    masks = _layer_masks(d)

    recall = _build_recall_audit(ah, masks)
    miss = _build_miss_reason(ah, masks)

    ah.to_csv(OUT_ALL_AHIGH, index=False, encoding="utf-8-sig")
    recall.to_csv(OUT_RECALL, index=False, encoding="utf-8-sig")
    miss.to_csv(OUT_MISS, index=False, encoding="utf-8-sig")
    _write_review(ah, recall, miss)

    print(f"A_high total={len(ah)}")
    print(str(OUT_ALL_AHIGH))
    print(str(OUT_RECALL))
    print(str(OUT_MISS))
    print(str(OUT_REVIEW))


if __name__ == "__main__":
    main()

