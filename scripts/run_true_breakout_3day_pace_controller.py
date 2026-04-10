from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(r"D:\HuaweiAI\quantSystem2")
BASE = ROOT / "data/research/strong_start_full/v4_scan"

IN_MAIN = BASE / "true_breakout_v32_with_priority_tag.csv"
IN_FEAT = BASE / "true_breakout_feature_snapshot_1y.parquet"

OUT_TIER_POOL = BASE / "true_breakout_tiered_input_pool.csv"
OUT_DAILY = BASE / "true_breakout_3day_pace_controller_daily.csv"
OUT_SUMMARY = BASE / "true_breakout_3day_pace_controller_summary.csv"
OUT_QUALITY = BASE / "true_breakout_3day_pace_controller_quality_review.csv"
OUT_REVIEW = BASE / "true_breakout_3day_pace_controller_review.md"
OUT_JSON = BASE / "true_breakout_3day_pace_controller_summary.json"


@dataclass
class PaceConfig:
    pace_days: int = 3
    max_new_per_day: int = 1

    # F2_only supplementary gate (stricter than raw F2_only)
    f2_rank_max: int = 2
    f2_score_total_min: float = 0.68
    f2_platform_axis_max: float = 0.68
    f2_industry_axis_max: float = 0.86
    f2_compress_min: float = 0.33


def _load() -> pd.DataFrame:
    main = pd.read_csv(IN_MAIN)
    main["ts_code"] = main["ts_code"].astype(str)
    main["trade_date"] = main["trade_date"].astype(str)
    main["window"] = main["window"].astype(str)

    feat = pd.read_parquet(IN_FEAT)[["ts_code", "trade_date", "f_platform_compress_ratio"]].copy()
    feat["ts_code"] = feat["ts_code"].astype(str)
    feat["trade_date"] = feat["trade_date"].astype(str)

    d = main.merge(feat, on=["ts_code", "trade_date"], how="left")
    d = d[d["window"].isin(["main", "confirm"])].copy()
    return d


def _build_tiers(d: pd.DataFrame) -> pd.DataFrame:
    d = d.copy()
    d["in_f3"] = (
        (d["priority_tag"] == 1)
        & (d["path_source"] == "A")
        & (d["score_platform_axis_single"] <= 0.64)
        & (d["score_industry_axis_single"] <= 0.90)
        & (d["f_platform_compress_ratio"] >= 0.33)
    )

    d["in_f2_only"] = (
        (d["priority_tag"] == 1)
        & (d["path_source"] == "A")
        & (d["score_industry_axis_single"] <= 0.90)
        & ~(
            (d["score_platform_axis_single"] <= 0.64)
            & (d["f_platform_compress_ratio"] >= 0.33)
        )
    )

    d["input_tier"] = np.select([d["in_f3"], d["in_f2_only"]], ["F3", "F2_only"], default="none")
    return d


def _pick_top1(df: pd.DataFrame) -> pd.Series:
    # Lower global rank first, then higher score_total.
    s = (
        df.assign(_rank_sort=pd.to_numeric(df["rank_global_after_merge"], errors="coerce").fillna(9999))
        .sort_values(["_rank_sort", "score_total"], ascending=[True, False])
        .head(1)
    )
    return s.iloc[0]


def _f2_gate(df: pd.DataFrame, cfg: PaceConfig) -> pd.DataFrame:
    return df[
        (pd.to_numeric(df["rank_global_after_merge"], errors="coerce") <= cfg.f2_rank_max)
        & (pd.to_numeric(df["score_total"], errors="coerce") >= cfg.f2_score_total_min)
        & (pd.to_numeric(df["score_platform_axis_single"], errors="coerce") <= cfg.f2_platform_axis_max)
        & (pd.to_numeric(df["score_industry_axis_single"], errors="coerce") <= cfg.f2_industry_axis_max)
        & (pd.to_numeric(df["f_platform_compress_ratio"], errors="coerce") >= cfg.f2_compress_min)
    ].copy()


def _run_pace_controller(tiered: pd.DataFrame, cfg: PaceConfig) -> tuple[pd.DataFrame, pd.DataFrame]:
    trading_days = sorted(tiered["trade_date"].unique().tolist())
    selected_idx: list[int] = []
    selected_rows: list[dict] = []
    daily_rows: list[dict] = []

    for i, day in enumerate(trading_days):
        day_df = tiered[tiered["trade_date"] == day].copy()
        f3_df = day_df[day_df["in_f3"]].copy()
        f2_df = day_df[day_df["in_f2_only"]].copy()
        f2_pass = _f2_gate(f2_df, cfg)

        recent_has_trade = any(j >= i - cfg.pace_days for j in selected_idx)
        selected_flag = 0
        selected_tier = "none"
        reason = "blank_day"
        picked = None

        # F3 always first.
        if not f3_df.empty:
            picked = _pick_top1(f3_df)
            selected_flag = 1
            selected_tier = "F3"
            reason = "f3_priority_pick"
            selected_idx.append(i)
        else:
            # Fallback only if no selection in recent 3 trading days.
            if (not recent_has_trade) and (not f2_pass.empty):
                picked = _pick_top1(f2_pass)
                selected_flag = 1
                selected_tier = "F2_only"
                reason = "f2_fallback_after_3day_blank"
                selected_idx.append(i)
            elif recent_has_trade:
                reason = "recent_3day_has_trade_no_fallback"
            else:
                reason = "f2_fallback_not_pass_gate"

        row = {
            "trade_date": day,
            "has_f3_candidates": int(not f3_df.empty),
            "has_f2_only_candidates": int(not f2_df.empty),
            "has_f2_only_pass_gate": int(not f2_pass.empty),
            "selected_flag": selected_flag,
            "selected_tier": selected_tier,
            "selected_reason": reason,
            "selected_stock_code": "",
            "selected_stock_name": "",
            "selected_ts_code": "",
            "selected_path_source": "",
            "selected_priority_tag": np.nan,
            "selected_rank_global_after_merge": np.nan,
            "selected_score_total": np.nan,
            "ret_t1_close": np.nan,
            "ret_t2_close": np.nan,
            "ret_t3_close": np.nan,
            "label_A_high": np.nan,
            "label_A_mid": np.nan,
            "label_A_low": np.nan,
            "label_C": np.nan,
            "label_G": np.nan,
        }

        if picked is not None:
            row.update(
                {
                    "selected_stock_code": picked.get("stock_code", ""),
                    "selected_stock_name": picked.get("stock_name", ""),
                    "selected_ts_code": picked.get("ts_code", ""),
                    "selected_path_source": picked.get("path_source", ""),
                    "selected_priority_tag": picked.get("priority_tag", np.nan),
                    "selected_rank_global_after_merge": picked.get("rank_global_after_merge", np.nan),
                    "selected_score_total": picked.get("score_total", np.nan),
                    "ret_t1_close": picked.get("ret_t1_close", np.nan),
                    "ret_t2_close": picked.get("ret_t2_close", np.nan),
                    "ret_t3_close": picked.get("ret_t3_close", np.nan),
                    "label_A_high": picked.get("label_A_high", np.nan),
                    "label_A_mid": picked.get("label_A_mid", np.nan),
                    "label_A_low": picked.get("label_A_low", np.nan),
                    "label_C": picked.get("label_C", np.nan),
                    "label_G": picked.get("label_G", np.nan),
                }
            )
            selected_rows.append(picked.to_dict())

        daily_rows.append(row)

    daily = pd.DataFrame(daily_rows)
    selected = daily[daily["selected_flag"] == 1].copy()
    return daily, selected


def _group_quality(df: pd.DataFrame, name: str) -> dict:
    row: dict[str, str | int | float] = {"group": name, "sample_n": int(len(df))}
    for l in ["label_A_high", "label_A_mid", "label_A_low", "label_C", "label_G"]:
        row[f"share_{l}"] = float(pd.to_numeric(df[l], errors="coerce").mean()) if len(df) else np.nan
    a = float(pd.to_numeric(df["label_A_high"], errors="coerce").sum()) if len(df) else 0.0
    c = float(pd.to_numeric(df["label_C"], errors="coerce").sum()) if len(df) else 0.0
    row["Ahigh_C_ratio"] = float(a / c) if c > 0 else np.nan
    for h in ["t1", "t2", "t3"]:
        s = pd.to_numeric(df[f"ret_{h}_close"], errors="coerce")
        row[f"mean_ret_{h}"] = float(s.mean()) if len(s) else np.nan
        row[f"median_ret_{h}"] = float(s.median()) if len(s) else np.nan
        row[f"win_{h}"] = float((s > 0).mean()) if len(s) else np.nan
    return row


def main() -> None:
    cfg = PaceConfig()
    d = _build_tiers(_load())

    tier_cols = [
        "trade_date",
        "stock_code",
        "stock_name",
        "ts_code",
        "in_f3",
        "in_f2_only",
        "input_tier",
        "priority_tag",
        "path_source",
        "score_platform_axis_single",
        "score_industry_axis_single",
        "f_platform_compress_ratio",
        "rank_global_after_merge",
        "selector_explain",
        "score_total",
        "ret_t1_close",
        "ret_t2_close",
        "ret_t3_close",
        "label_A_high",
        "label_A_mid",
        "label_A_low",
        "label_C",
        "label_G",
    ]
    tiered = d[tier_cols].copy()
    tiered.to_csv(OUT_TIER_POOL, index=False, encoding="utf-8-sig")

    daily, selected = _run_pace_controller(d, cfg)
    daily.to_csv(OUT_DAILY, index=False, encoding="utf-8-sig")

    total_days = int(daily["trade_date"].nunique())
    days_with_f3 = int(daily["has_f3_candidates"].sum())
    days_with_f2 = int(daily["has_f2_only_candidates"].sum())
    selected_days = int(daily["selected_flag"].sum())
    blank_days = total_days - selected_days
    avg_days_per_trade = float(total_days / selected_days) if selected_days > 0 else np.nan

    f3_sel_days = int((daily["selected_tier"] == "F3").sum())
    f2_sel_days = int((daily["selected_tier"] == "F2_only").sum())

    summary = pd.DataFrame(
        [
            {
                "total_trading_days": total_days,
                "days_with_f3_candidates": days_with_f3,
                "days_with_f2_only_candidates": days_with_f2,
                "selected_days": selected_days,
                "blank_days": blank_days,
                "blank_day_ratio": float(blank_days / total_days) if total_days else np.nan,
                "avg_days_per_selected": avg_days_per_trade,
                "f3_selected_days": f3_sel_days,
                "f2_selected_days": f2_sel_days,
                "f3_selected_share": float(f3_sel_days / selected_days) if selected_days else np.nan,
                "f2_selected_share": float(f2_sel_days / selected_days) if selected_days else np.nan,
                "pace_target_days": cfg.pace_days,
            }
        ]
    )
    summary.to_csv(OUT_SUMMARY, index=False, encoding="utf-8-sig")

    quality_rows = []
    quality_rows.append(_group_quality(selected, "controller_selected_all"))
    quality_rows.append(_group_quality(selected[selected["selected_tier"] == "F3"], "controller_selected_f3"))
    quality_rows.append(_group_quality(selected[selected["selected_tier"] == "F2_only"], "controller_selected_f2_only"))
    quality = pd.DataFrame(quality_rows)
    quality.to_csv(OUT_QUALITY, index=False, encoding="utf-8-sig")

    md = [
        "# 3-Day Pace Controller Review",
        "",
        "Frozen selector structure is unchanged.",
        "",
        "## Tier definition",
        "- F3 (high-purity): priority=1 & path=A & platform<=0.64 & industry<=0.90 & compress>=0.33",
        "- F2_only (supplement): priority=1 & path=A & industry<=0.90 & not(F3 platform+compress condition)",
        "",
        "## Controller logic",
        "- F3 first (daily top1 by rank_global_after_merge then score_total)",
        "- If no F3 on a day and no trade in recent 3 trading days, allow F2_only fallback",
        "- F2_only must pass stricter gate:",
        f"  rank<= {cfg.f2_rank_max}, score_total>= {cfg.f2_score_total_min}, platform<= {cfg.f2_platform_axis_max}, "
        f"industry<= {cfg.f2_industry_axis_max}, compress>= {cfg.f2_compress_min}",
        "- max 1 stock/day",
        "",
        "## Headline",
        f"- trading days: {total_days}",
        f"- selected days: {selected_days} (blank ratio {blank_days/total_days:.2%})",
        f"- avg days per selected: {avg_days_per_trade:.2f}",
        f"- selected tier share: F3={f3_sel_days}/{selected_days}, F2_only={f2_sel_days}/{selected_days}",
        "",
        "## Outputs",
        f"- {OUT_TIER_POOL.name}",
        f"- {OUT_DAILY.name}",
        f"- {OUT_SUMMARY.name}",
        f"- {OUT_QUALITY.name}",
    ]
    OUT_REVIEW.write_text("\n".join(md), encoding="utf-8")

    OUT_JSON.write_text(
        json.dumps(
            {
                "summary": summary.iloc[0].to_dict(),
                "quality": quality.to_dict("records"),
                "files": {
                    "tier_pool": str(OUT_TIER_POOL),
                    "daily": str(OUT_DAILY),
                    "summary": str(OUT_SUMMARY),
                    "quality": str(OUT_QUALITY),
                    "review": str(OUT_REVIEW),
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print(summary.to_dict("records")[0])
    print(str(OUT_DAILY))
    print(str(OUT_SUMMARY))
    print(str(OUT_QUALITY))


if __name__ == "__main__":
    main()
