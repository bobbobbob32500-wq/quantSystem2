from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(r"D:\HuaweiAI\quantSystem2")
BASE = ROOT / "data/research/strong_start_full/v4_scan"

IN_MAIN = BASE / "true_breakout_v32_with_priority_tag.csv"
IN_FEAT = BASE / "true_breakout_feature_snapshot_1y.parquet"

OUT_POOL = BASE / "true_breakout_f3_2_pool.csv"
OUT_SUMMARY = BASE / "true_breakout_f3_2_summary.csv"
OUT_JSON = BASE / "true_breakout_f3_2_summary.json"
OUT_MD = BASE / "true_breakout_f3_2_review.md"


def _load() -> pd.DataFrame:
    m = pd.read_csv(IN_MAIN)
    m["ts_code"] = m["ts_code"].astype(str)
    m["trade_date"] = m["trade_date"].astype(str)
    m["window"] = m["window"].fillna("all").astype(str)

    f = pd.read_parquet(IN_FEAT)[["ts_code", "trade_date", "f_platform_compress_ratio"]].copy()
    f["ts_code"] = f["ts_code"].astype(str)
    f["trade_date"] = f["trade_date"].astype(str)

    return m.merge(f, on=["ts_code", "trade_date"], how="left")


def _daily_top1(df: pd.DataFrame) -> pd.DataFrame:
    return (
        df.sort_values(["trade_date", "score_total"], ascending=[True, False])
        .groupby("trade_date", as_index=False)
        .head(1)
        .copy()
    )


def _strict_f3(core: pd.DataFrame) -> pd.DataFrame:
    strict = core.query(
        "(priority_tag == 1) and (path_source == 'A') and "
        "(score_platform_axis_single <= 0.64) and "
        "(score_industry_axis_single <= 0.90) and "
        "(f_platform_compress_ratio >= 0.33)"
    ).copy()
    strict["f32_tier"] = "strict_f3"
    return _daily_top1(strict)


def _supplement(core: pd.DataFrame, strict_days: set[str]) -> pd.DataFrame:
    # Minimal, path-preserving frequency supplement:
    # only fill days where strict has no signal.
    supp = core.query(
        "(rank_global_after_merge <= 2) and "
        "(score_total >= 0.68) and "
        "(score_platform_axis_single <= 0.68) and "
        "(score_industry_axis_single <= 0.86) and "
        "(f_platform_compress_ratio >= 0.33)"
    ).copy()
    supp = supp[~supp["trade_date"].isin(strict_days)].copy()
    supp = _daily_top1(supp)
    supp["f32_tier"] = "supplement"
    return supp


def _stats(df: pd.DataFrame, group: str, window: str, trading_days: int) -> dict:
    row: dict[str, str | int | float] = {
        "group": group,
        "window": window,
        "sample_n": int(len(df)),
        "signal_days": int(df["trade_date"].nunique()) if len(df) else 0,
        "signal_day_ratio": float(df["trade_date"].nunique() / trading_days) if trading_days else np.nan,
        "blank_day_ratio": float(1 - df["trade_date"].nunique() / trading_days) if trading_days else np.nan,
    }
    for l in ["label_A_high", "label_A_mid", "label_A_low", "label_C", "label_G"]:
        row[f"share_{l}"] = float(df[l].mean()) if len(df) else np.nan
    for h in ["t1", "t2", "t3"]:
        s = pd.to_numeric(df[f"ret_{h}_close"], errors="coerce")
        row[f"mean_ret_{h}"] = float(s.mean()) if len(s) else np.nan
        row[f"median_ret_{h}"] = float(s.median()) if len(s) else np.nan
        row[f"win_{h}"] = float((s > 0).mean()) if len(s) else np.nan
    row["pathA_share"] = float((df["path_source"] == "A").mean()) if len(df) else np.nan
    row["priority_share"] = float(df["priority_tag"].mean()) if len(df) else np.nan
    return row


def main() -> None:
    d = _load()
    core = d[d["is_core_candidate"] == 1].copy()
    core_eval = core[core["window"].isin(["main", "confirm"])].copy()
    trading_days_eval = int(core_eval["trade_date"].nunique())

    f3 = _strict_f3(core_eval)
    f3_days = set(f3["trade_date"].tolist())
    f32 = pd.concat([f3, _supplement(core_eval, f3_days)], ignore_index=True)
    f32 = _daily_top1(f32).sort_values(["trade_date", "score_total"], ascending=[True, False]).reset_index(drop=True)

    keep_cols = [
        "trade_date",
        "window",
        "stock_code",
        "stock_name",
        "ts_code",
        "path_source",
        "priority_tag",
        "f32_tier",
        "score_total",
        "score_platform_axis_single",
        "score_industry_axis_single",
        "score_chip_axis_single",
        "f_platform_compress_ratio",
        "label_A_high",
        "label_A_mid",
        "label_A_low",
        "label_C",
        "label_G",
        "ret_t1_close",
        "ret_t2_close",
        "ret_t3_close",
    ]
    for c in keep_cols:
        if c not in f32.columns:
            f32[c] = np.nan
    f32_out = f32[keep_cols].copy()
    f32_out.to_csv(OUT_POOL, index=False, encoding="utf-8-sig")

    rows = []
    for w in ["all", "main", "confirm"]:
        if w == "all":
            a, b = f3, f32
            td = trading_days_eval
        else:
            a, b = f3[f3["window"] == w], f32[f32["window"] == w]
            td = int(core_eval[core_eval["window"] == w]["trade_date"].nunique())
        rows.append(_stats(a, "F3_strict_baseline", w, td))
        rows.append(_stats(b, "F3.2_strict_plus_supplement", w, td))
    summary = pd.DataFrame(rows)
    summary.to_csv(OUT_SUMMARY, index=False, encoding="utf-8-sig")

    decision = {
        "f3_days": int(f3["trade_date"].nunique()),
        "f32_days": int(f32["trade_date"].nunique()),
        "f3_n": int(len(f3)),
        "f32_n": int(len(f32)),
        "added_days": int(f32["trade_date"].nunique() - f3["trade_date"].nunique()),
        "trading_days_eval": trading_days_eval,
        "target_min_days_for_1_every_3d": int(np.ceil(trading_days_eval / 3)),
    }
    OUT_JSON.write_text(
        json.dumps(
            {"decision": decision, "summary_rows": summary.to_dict("records")},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    md = [
        "# F3.2 Frequency Boost Review",
        "",
        "Goal: improve signal frequency while keeping strong-stock profile.",
        "",
        "## Logic (frozen selector unchanged)",
        "- strict base: priority_tag=1 & path_source=A & F3 thresholds",
        "- supplement only on strict-empty days:",
        "  - rank_global_after_merge<=2",
        "  - score_total>=0.68",
        "  - score_platform_axis_single<=0.68",
        "  - score_industry_axis_single<=0.86",
        "  - f_platform_compress_ratio>=0.33",
        "- one stock per signal day (daily top1 by score_total)",
        "",
        "## Headline",
        f"- trading days (main+confirm): {decision['trading_days_eval']}",
        f"- target (>=1 stock per 3 days): >= {decision['target_min_days_for_1_every_3d']} days",
        f"- F3 strict days: {decision['f3_days']} | F3.2 days: {decision['f32_days']} | added: {decision['added_days']}",
        f"- F3 strict n: {decision['f3_n']} | F3.2 n: {decision['f32_n']}",
        "",
        "## Outputs",
        f"- pool: {OUT_POOL.name}",
        f"- summary: {OUT_SUMMARY.name}",
    ]
    OUT_MD.write_text("\n".join(md), encoding="utf-8")

    print(json.dumps(decision, ensure_ascii=False, indent=2))
    print(str(OUT_POOL))
    print(str(OUT_SUMMARY))
    print(str(OUT_MD))


if __name__ == "__main__":
    main()
