from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(r"D:\HuaweiAI\quantSystem2")
BASE = ROOT / "data/research/strong_start_full/v4_scan"

IN_MAIN = BASE / "true_breakout_v32_with_priority_tag.csv"
IN_FEAT = BASE / "true_breakout_feature_snapshot_1y.parquet"

OUT_POOL = BASE / "true_breakout_f3_1_pool.csv"
OUT_SUMMARY = BASE / "true_breakout_f3_1_summary.csv"
OUT_JSON = BASE / "true_breakout_f3_1_summary.json"
OUT_MD = BASE / "true_breakout_f3_1_review.md"


def _load() -> pd.DataFrame:
    m = pd.read_csv(IN_MAIN)
    m["ts_code"] = m["ts_code"].astype(str)
    m["trade_date"] = m["trade_date"].astype(str)
    m["window"] = m["window"].fillna("all").astype(str)

    f = pd.read_parquet(IN_FEAT)[["ts_code", "trade_date", "f_platform_compress_ratio"]].copy()
    f["ts_code"] = f["ts_code"].astype(str)
    f["trade_date"] = f["trade_date"].astype(str)

    return m.merge(f, on=["ts_code", "trade_date"], how="left")


def _strict_pool(d: pd.DataFrame) -> pd.DataFrame:
    return d[(d["is_core_candidate"] == 1) & (d["priority_tag"] == 1) & (d["path_source"] == "A")].copy()


def _build_f31(sp: pd.DataFrame) -> pd.DataFrame:
    # F3 strict (frozen)
    strict = sp.query(
        "(score_platform_axis_single <= 0.64) and "
        "(score_industry_axis_single <= 0.90) and "
        "(f_platform_compress_ratio >= 0.33)"
    ).copy()
    strict["f31_tier"] = "strict"

    # Relaxed fallback (minimal expansion)
    relaxed = sp.query(
        "(score_platform_axis_single <= 0.66) and "
        "(score_industry_axis_single <= 0.90) and "
        "(f_platform_compress_ratio >= 0.30)"
    ).copy()
    relaxed["f31_tier"] = "relaxed"

    # daily top1 in each tier
    strict_top = (
        strict.sort_values(["trade_date", "score_total"], ascending=[True, False])
        .groupby("trade_date", as_index=False)
        .head(1)
        .copy()
    )
    relaxed_extra = relaxed[
        ~relaxed.set_index(["ts_code", "trade_date"]).index.isin(strict.set_index(["ts_code", "trade_date"]).index)
    ].copy()
    relaxed_top = (
        relaxed_extra.sort_values(["trade_date", "score_total"], ascending=[True, False])
        .groupby("trade_date", as_index=False)
        .head(1)
        .copy()
    )

    # fallback logic: only add relaxed when strict has no signal that day
    strict_days = set(strict_top["trade_date"].tolist())
    relaxed_fallback = relaxed_top[~relaxed_top["trade_date"].isin(strict_days)].copy()
    if not relaxed_fallback.empty:
        relaxed_fallback["f31_tier"] = "relaxed_fallback"

    out = pd.concat([strict_top, relaxed_fallback], ignore_index=True)
    out = out.sort_values(["trade_date", "score_total"], ascending=[True, False]).reset_index(drop=True)
    return out


def _stats(df: pd.DataFrame, group: str, window: str) -> dict:
    row: dict[str, str | int | float] = {"group": group, "window": window, "sample_n": int(len(df))}
    for l in ["label_A_high", "label_A_mid", "label_A_low", "label_C", "label_G"]:
        row[f"share_{l}"] = float(df[l].mean()) if len(df) else np.nan
    for h in ["t1", "t2", "t3"]:
        s = pd.to_numeric(df[f"ret_{h}_close"], errors="coerce")
        row[f"mean_ret_{h}"] = float(s.mean()) if len(s) else np.nan
        row[f"median_ret_{h}"] = float(s.median()) if len(s) else np.nan
        row[f"win_{h}"] = float((s > 0).mean()) if len(s) else np.nan
    return row


def main() -> None:
    d = _load()
    sp = _strict_pool(d)

    # frozen baselines for compare
    f3 = sp.query(
        "(score_platform_axis_single <= 0.64) and "
        "(score_industry_axis_single <= 0.90) and "
        "(f_platform_compress_ratio >= 0.33)"
    ).copy()
    f31 = _build_f31(sp)

    keep_cols = [
        "trade_date",
        "window",
        "stock_code",
        "stock_name",
        "ts_code",
        "score_total",
        "score_platform_axis_single",
        "score_industry_axis_single",
        "f_platform_compress_ratio",
        "label_A_high",
        "label_A_mid",
        "label_A_low",
        "label_C",
        "label_G",
        "ret_t1_close",
        "ret_t2_close",
        "ret_t3_close",
        "f31_tier",
    ]
    for c in keep_cols:
        if c not in f31.columns:
            f31[c] = np.nan
    f31_out = f31[keep_cols].copy()
    f31_out.to_csv(OUT_POOL, index=False, encoding="utf-8-sig")

    rows = []
    for w in ["all", "main", "confirm"]:
        if w == "all":
            a, b = f3, f31
        else:
            a, b = f3[f3["window"] == w], f31[f31["window"] == w]
        rows.append(_stats(a, "F3_strict_baseline", w))
        rows.append(_stats(b, "F3.1_strict_plus_relaxed_fallback", w))
    summary = pd.DataFrame(rows)
    summary.to_csv(OUT_SUMMARY, index=False, encoding="utf-8-sig")

    dec = {
        "f3_days": int(f3["trade_date"].nunique()),
        "f31_days": int(f31["trade_date"].nunique()),
        "f3_n": int(len(f3)),
        "f31_n": int(len(f31)),
        "added_days_by_relaxed_fallback": int(f31["trade_date"].nunique() - f3["trade_date"].nunique()),
    }
    OUT_JSON.write_text(
        json.dumps(
            {
                "decision": dec,
                "summary_rows": summary.to_dict("records"),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    md = [
        "# F3.1 Strict+Relaxed Fallback Review",
        "",
        "Goal: increase signal frequency without breaking strong-stock character.",
        "",
        "## Frozen logic",
        "- Base pool: strict_pool = priority_tag=1 & path_source=A",
        "- F3 strict: platform<=0.64 & industry<=0.90 & compress>=0.33",
        "- F3.1: strict first; if day has no strict signal, allow one relaxed fallback:",
        "  - platform<=0.66 & industry<=0.90 & compress>=0.30",
        "",
        "## Headline",
        f"- F3 days: {dec['f3_days']} | F3.1 days: {dec['f31_days']} | added days: {dec['added_days_by_relaxed_fallback']}",
        f"- F3 n: {dec['f3_n']} | F3.1 n: {dec['f31_n']}",
        "",
        "## Outputs",
        f"- pool: {OUT_POOL.name}",
        f"- summary: {OUT_SUMMARY.name}",
    ]
    OUT_MD.write_text("\n".join(md), encoding="utf-8")

    print(json.dumps(dec, ensure_ascii=False, indent=2))
    print(str(OUT_POOL))
    print(str(OUT_SUMMARY))
    print(str(OUT_MD))


if __name__ == "__main__":
    main()

