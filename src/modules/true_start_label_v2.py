# -*- coding: utf-8 -*-
"""
真实启动标签规范 v2（交易可执行版）—— 平台突破型候选池 + 正反例打标。

说明：
- 仅用于研究打标，不替代实盘选股；标签冻结后可用于反推规则。
- 前瞻收益以 T+1 开盘价入场为基准，与现有 sample_mining 口径一致。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from src.core.database import DatabaseManager
from src.modules.strong_start_sample_mining import SampleMiningConfig, StrongStartSampleMiner, _date_minus, _date_plus


@dataclass
class TrueStartLabelV2Config:
    """v2 阈值（可按质检报告再调，勿在未看分布前卡死）。"""

    label_version: str = "true_start_v2"

    # 候选池：平台突破型
    vol_ratio20_min: float = 1.5
    close_vs_pivot_min: float = 0.98  # close >= pivot_20 * 该值
    body_ratio_min: float = 0.5
    upper_shadow_max: float = 0.35
    pre_10d_ret_max: float = 0.12  # 事件日前一段累计涨幅上限（用 close[t-1]/close[t-11]-1）
    platform_range_10d_max: float = 0.12  # 前10日（不含当日）振幅箱体的相对宽度
    strong_up_days_5_max: int = 2  # 近5日 pct_chg>=3% 的天数上限
    close_to_ma20_max: float = 1.12  # 相对 MA20 不过热
    require_ma_align: bool = True  # MA5>=MA10>=MA20

    # 正例：可交易真实启动
    mfe_t5_min: float = 0.08
    mae_t5_max_abs: float = 0.04  # 最大不利偏移绝对值不超过 4%
    close_above_pivot_days_min: int = 3  # T+1~T+5 内收盘站稳 pivot 的天数
    pivot_buffer: float = 0.99  # 跌破 pivot 判定：low < pivot * buffer
    entry_gap_max: float = 0.045  # 次日开盘跳空上限（相对事件日收盘）
    follow_through_min: float = 0.01  # max(T+1/T+2 日内最高相对入场收益) 下限

    # 反例
    false_pair_weak_ret: float = 0.03
    false_pair_deep_mae: float = 0.06
    false_gap_high: float = 0.05
    false_upper_shadow: float = 0.45

    # 可执行性（沿用 miner 的一字板判定）
    entry_limit_up_pct: float = 0.095


def _fmt_date_series(s: pd.Series) -> pd.Series:
    return pd.to_datetime(s, errors="coerce").dt.strftime("%Y%m%d")


def enrich_v2_columns(df: pd.DataFrame) -> pd.DataFrame:
    """在 miner 面板上补充 v2 所需字段（按股票分组）。"""
    out = df.copy()
    g = out.groupby("ts_code", group_keys=False)
    bar_range = (out["high"] - out["low"]).replace(0, np.nan)
    out["body_ratio"] = (out["close"] - out["open"]).abs() / (bar_range + 1e-12)
    # 前10日（不含当日）箱体：high[t-10..t-1]
    rh = g["high"].transform(lambda s: s.shift(1).rolling(10, min_periods=5).max())
    rl = g["low"].transform(lambda s: s.shift(1).rolling(10, min_periods=5).min())
    out["platform_range_10d"] = (rh - rl) / rh.replace(0, np.nan)
    # 事件日前「已拉升」幅度：close[t-1] 相对 close[t-11]
    out["pre_10d_ret"] = g["close"].shift(1) / g["close"].shift(11).replace(0, np.nan) - 1.0
    # 近5日强势日计数（pct_chg>=3%）
    out["strong_up_flag"] = (out["pct_chg"].fillna(0.0) >= 3.0).astype(float)
    out["strong_up_count_5"] = g["strong_up_flag"].transform(lambda s: s.rolling(5, min_periods=1).sum())
    out["close_to_ma20"] = out["close"] / out["ma20"].replace(0, np.nan)
    out["ma_align"] = (out["ma5"] >= out["ma10"]) & (out["ma10"] >= out["ma20"])
    return out


def candidate_mask_platform_break_v2(df: pd.DataFrame, cfg: TrueStartLabelV2Config, index_code: str = "000001.SH") -> pd.Series:
    """平台突破型候选池（布尔序列，与 df 索引对齐）。"""
    stock = df["ts_code"].astype(str) != str(index_code)
    not_st = ~df["name"].fillna("").astype(str).str.upper().str.contains(r"ST|退", regex=True)
    base = (
        stock
        & not_st
        & df["list_days"].fillna(0).ge(120)
        & df["amount_ma20"].fillna(0).ge(5e4)
        & df["close"].fillna(0).between(4.0, 120.0)
    )
    piv = df["pivot_20"].replace(0, np.nan)
    cond = (
        base
        & df["close"].ge(piv * cfg.close_vs_pivot_min)
        & df["vol_ratio20"].fillna(0).ge(cfg.vol_ratio20_min)
        & (df["close"] > df["open"])
        & df["body_ratio"].fillna(0).ge(cfg.body_ratio_min)
        & df["upper_shadow_ratio"].fillna(1).le(cfg.upper_shadow_max)
        & df["pre_10d_ret"].fillna(np.inf).le(cfg.pre_10d_ret_max)
        & df["platform_range_10d"].fillna(np.inf).le(cfg.platform_range_10d_max)
        & df["strong_up_count_5"].fillna(0).le(cfg.strong_up_days_5_max)
        & df["close_to_ma20"].fillna(np.inf).le(cfg.close_to_ma20_max)
    )
    if cfg.require_ma_align:
        cond = cond & df["ma_align"].fillna(False)
    return cond


def compute_forward_metrics_v2(
    sub: pd.DataFrame,
    cfg: TrueStartLabelV2Config,
) -> pd.DataFrame:
    """计算前瞻收益与结构字段（需已含 open/high/low/close_fwd_1..5、pivot_20、upper_shadow_ratio）。"""
    out = sub.copy()
    hold = 5
    high_cols = [f"high_fwd_{i}" for i in range(1, hold + 1)]
    low_cols = [f"low_fwd_{i}" for i in range(1, hold + 1)]
    close_cols = [f"close_fwd_{i}" for i in range(1, hold + 1)]

    entry = out["open_fwd_1"].replace(0, np.nan)
    out["entry_price_t1_open"] = entry
    out["t1_open_gap"] = out["open_fwd_1"] / out["close"].replace(0, np.nan) - 1.0
    out["has_full_forward_window"] = out[close_cols].notna().all(axis=1)

    out["future_max_ret_t5"] = out[high_cols].max(axis=1, skipna=True) / entry - 1.0
    out["future_max_dd_t5"] = out[low_cols].min(axis=1, skipna=True) / entry - 1.0

    floor = out["pivot_20"].fillna(out["close"])
    above = pd.Series(0, index=out.index, dtype=int)
    for c in close_cols:
        above = above + (out[c] >= floor).fillna(False).astype(int)
    out["close_above_pivot_days_t5"] = above

    brk = np.zeros(len(out), dtype=bool)
    for i in range(1, 4):
        brk |= out[f"low_fwd_{i}"] < floor * cfg.pivot_buffer
    out["break_pivot_within_t3"] = brk

    out["future_ret_t2"] = out["close_fwd_2"] / entry - 1.0
    out["ret_from_t1_open_t3"] = out["close_fwd_3"] / entry - 1.0
    h1 = out["high_fwd_1"] / entry - 1.0
    h2 = out["high_fwd_2"] / entry - 1.0
    out["follow_through_max_t2"] = np.maximum(h1.fillna(-np.inf), h2.fillna(-np.inf))

    one_price = (
        out["pct_chg_fwd_1"].fillna(0.0).ge(cfg.entry_limit_up_pct * 100.0)
        & np.isclose(out["open_fwd_1"], out["high_fwd_1"], equal_nan=False)
        & np.isclose(out["open_fwd_1"], out["low_fwd_1"], equal_nan=False)
        & np.isclose(out["open_fwd_1"], out["close_fwd_1"], equal_nan=False)
    )
    out["limit_up_untradable_flag"] = one_price

    # 正例条件
    pos_core = (
        out["has_full_forward_window"]
        & out["future_max_ret_t5"].fillna(-np.inf).ge(cfg.mfe_t5_min)
        & out["future_max_dd_t5"].fillna(-np.inf).ge(-cfg.mae_t5_max_abs)
        & out["close_above_pivot_days_t5"].fillna(0).ge(cfg.close_above_pivot_days_min)
        & (~out["break_pivot_within_t3"])
        & (~out["limit_up_untradable_flag"])
        & out["t1_open_gap"].fillna(np.inf).le(cfg.entry_gap_max)
        & out["follow_through_max_t2"].fillna(-np.inf).ge(cfg.follow_through_min)
    )

    # 反例条件
    neg_weak_pair = (
        out["future_max_ret_t5"].fillna(np.inf).lt(cfg.false_pair_weak_ret)
        & (out["future_max_dd_t5"].fillna(0) <= -cfg.false_pair_deep_mae)
    )
    neg_break = out["break_pivot_within_t3"]
    neg_shadow = out["upper_shadow_ratio"].fillna(0).gt(cfg.false_upper_shadow) & out["future_ret_t2"].fillna(
        np.inf
    ).lt(0)
    neg_gap_trap = out["t1_open_gap"].fillna(0).gt(cfg.false_gap_high) & out["ret_from_t1_open_t3"].fillna(np.inf).le(0)

    neg_any = neg_weak_pair | neg_break | neg_shadow | neg_gap_trap

    out["false_flag_weak_return_deep_dd"] = neg_weak_pair
    out["false_flag_break_pivot_within_t3"] = neg_break
    out["false_flag_upper_shadow_t2_weak"] = neg_shadow
    out["false_flag_gap_up_fail"] = neg_gap_trap

    # 反例主因（优先级：破位 > 高开骗炮 > 弱双杀 > 上影弱）
    pri = np.full(len(out), "", dtype=object)
    pri[neg_break.fillna(False).to_numpy()] = "break_pivot_within_t3"
    rem = pri == ""
    pri[rem & neg_gap_trap.fillna(False).to_numpy()] = "gap_up_fail"
    rem = pri == ""
    pri[rem & neg_weak_pair.fillna(False).to_numpy()] = "weak_return_and_deep_dd"
    rem = pri == ""
    pri[rem & neg_shadow.fillna(False).to_numpy()] = "upper_shadow_and_t2_weak"
    multi = (
        neg_weak_pair.astype(int)
        + neg_break.astype(int)
        + neg_shadow.astype(int)
        + neg_gap_trap.astype(int)
    ) > 1
    pri = np.where(multi & (pri != ""), "multiple", pri)
    out["false_reason_primary"] = pri

    hf = out["has_full_forward_window"].fillna(False)
    # 正例优先：满足 pos_core 即标真；反例仅在不满足 pos_core 且命中失败模式时标假；其余为中性
    out["label_true_start"] = hf & pos_core
    out["label_false_start"] = hf & (~pos_core) & neg_any
    out["label_neutral"] = ~(out["label_true_start"] | out["label_false_start"])
    out["label_version"] = cfg.label_version

    # 正例路径分型（仅真启动行有意义；其余为 unknown）
    out["path_type"] = "unknown"
    out["true_start_quality_score"] = np.nan
    out["true_start_tier"] = ""

    mfe_all = out["future_max_ret_t5"]
    entry = out["entry_price_t1_open"].replace(0, np.nan)
    hf1 = out["high_fwd_1"] / entry - 1.0
    hf2 = out["high_fwd_2"] / entry - 1.0
    mfe_first2 = np.maximum(hf1.fillna(-np.inf), hf2.fillna(-np.inf))
    h345 = (
        pd.concat(
            [
                (out["high_fwd_3"] / entry - 1.0),
                (out["high_fwd_4"] / entry - 1.0),
                (out["high_fwd_5"] / entry - 1.0),
            ],
            axis=1,
        )
        .max(axis=1)
        .fillna(-np.inf)
    )
    gap = out["t1_open_gap"].fillna(0)
    ft = out["follow_through_max_t2"].fillna(0)

    is_true = out["label_true_start"].fillna(False)
    path = pd.Series("unknown", index=out.index, dtype=object)
    thr_fast = np.maximum(0.03, 0.45 * mfe_all.fillna(0.0))
    cond_gap = is_true & (gap > 0.02) & (ft >= 0.01) & (mfe_first2 >= 0.03)
    path.loc[cond_gap] = "gap_follow_through"
    remain = is_true & (path == "unknown")
    cond_fast = remain & (mfe_first2 >= thr_fast)
    path.loc[cond_fast] = "fast_breakout"
    remain2 = is_true & (path == "unknown")
    cond_late = remain2 & (mfe_first2 < 0.45 * mfe_all.fillna(0.0)) & (h345 >= 0.03)
    path.loc[cond_late] = "late_strength"
    remain3 = is_true & (path == "unknown")
    path.loc[remain3] = "slow_grind_up"

    # 正例内部分层：A=高质量，B=达标（分数仅对真启动计算）
    mae_abs = (-out["future_max_dd_t5"].fillna(-1)).clip(lower=0)
    cap_days = out["close_above_pivot_days_t5"].fillna(0) / 5.0
    score = (
        0.35 * np.clip(mfe_all / 0.15, 0, 1)
        + 0.25 * np.clip((0.04 - mae_abs) / 0.04, 0, 1)
        + 0.15 * cap_days
        + 0.15 * np.clip(out["follow_through_max_t2"].fillna(0) / 0.03, 0, 1)
        + 0.10 * (1.0 - np.clip(gap / 0.05, 0, 1))
    )
    out["true_start_quality_score"] = np.where(is_true, score, np.nan)
    out["true_start_tier"] = np.where(is_true, np.where(score >= 0.72, "A", "B"), "")
    out["path_type"] = path
    return out


def build_research_summaries(df: pd.DataFrame) -> Dict[str, pd.DataFrame]:
    """
    产出研究用五张质检表：月度、行业、反例原因、正例路径、正反例分位数对比。
    """
    if df is None or df.empty:
        return {}

    work = df.copy()
    work["month"] = work["trade_date"].astype(str).str[:6]
    if "industry" not in work.columns:
        work["industry"] = "UNKNOWN"
    work["industry"] = work["industry"].fillna("UNKNOWN").replace("", "UNKNOWN")

    # 1) 月度统计
    monthly_rows: List[Dict[str, Any]] = []
    for month, sub in work.groupby("month"):
        cand = len(sub)
        tc = int(sub["label_true_start"].sum())
        fc = int(sub["label_false_start"].sum())
        nc = int(sub["label_neutral"].sum())
        unt = int(sub["limit_up_untradable_flag"].sum())
        tbin = tc + fc
        true_only = sub[sub["label_true_start"]]
        monthly_rows.append(
            {
                "month": month,
                "candidate_count": cand,
                "true_count": tc,
                "false_count": fc,
                "neutral_count": nc,
                "true_rate_in_candidate": round(tc / cand, 6) if cand else 0.0,
                "true_rate_in_binary": round(tc / tbin, 6) if tbin else 0.0,
                "untradable_rate": round(unt / cand, 6) if cand else 0.0,
                "avg_t1_open_gap_true": float(true_only["t1_open_gap"].mean()) if len(true_only) else np.nan,
                "median_t1_open_gap_true": float(true_only["t1_open_gap"].median()) if len(true_only) else np.nan,
                "true_tier_A_count": int((sub["true_start_tier"] == "A").sum()) if "true_start_tier" in sub.columns else 0,
                "true_tier_B_count": int((sub["true_start_tier"] == "B").sum()) if "true_start_tier" in sub.columns else 0,
            }
        )
    monthly = pd.DataFrame(monthly_rows)

    # 2) 行业转化率
    ind_rows: List[Dict[str, Any]] = []
    for ind, sub in work.groupby("industry"):
        cand = len(sub)
        tc = int(sub["label_true_start"].sum())
        fc = int(sub["label_false_start"].sum())
        nc = int(sub["label_neutral"].sum())
        ind_rows.append(
            {
                "industry": ind,
                "candidate_count": cand,
                "true_count": tc,
                "false_count": fc,
                "neutral_count": nc,
                "true_conversion_rate": round(tc / cand, 6) if cand else 0.0,
                "false_conversion_rate": round(fc / cand, 6) if cand else 0.0,
            }
        )
    industry = pd.DataFrame(ind_rows).sort_values("candidate_count", ascending=False)

    # 3) 反例原因（按月 + 原因）
    false_df = work[work["label_false_start"].fillna(False)].copy()
    if not false_df.empty and "false_reason_primary" in false_df.columns:
        false_reason = (
            false_df.groupby(["month", "false_reason_primary"])
            .size()
            .reset_index(name="count")
        )
        false_reason["ratio_in_month_false"] = false_reason.groupby("month")["count"].transform(
            lambda s: (s / s.sum()).round(6)
        )
    else:
        false_reason = pd.DataFrame(columns=["month", "false_reason_primary", "count", "ratio_in_month_false"])

    # 4) 正例路径分布（按月）
    true_df = work[work["label_true_start"].fillna(False)].copy()
    if not true_df.empty and "path_type" in true_df.columns:
        path_rows: List[Dict[str, Any]] = []
        for (month, ptype), sub in true_df.groupby(["month", "path_type"]):
            path_rows.append(
                {
                    "month": month,
                    "path_type": ptype,
                    "count": len(sub),
                    "avg_mfe_t5": float(sub["future_max_ret_t5"].mean()),
                    "avg_mae_t5": float(sub["future_max_dd_t5"].mean()),
                    "avg_follow_through_t2": float(sub["follow_through_max_t2"].mean()),
                }
            )
        path_month = pd.DataFrame(path_rows)
    else:
        path_month = pd.DataFrame(
            columns=["month", "path_type", "count", "avg_mfe_t5", "avg_mae_t5", "avg_follow_through_t2"]
        )

    # 5) 正反例核心字段分位数
    compare_cols = [
        "pre_10d_ret",
        "platform_range_10d",
        "vol_ratio20",
        "body_ratio",
        "upper_shadow_ratio",
        "close_to_ma20",
        "t1_open_gap",
        "follow_through_max_t2",
        "future_max_ret_t5",
        "future_max_dd_t5",
    ]
    qrows: List[Dict[str, Any]] = []
    tmask = work["label_true_start"].fillna(False)
    fmask = work["label_false_start"].fillna(False)
    for col in compare_cols:
        if col not in work.columns:
            continue
        ts = work.loc[tmask, col]
        fs = work.loc[fmask, col]
        qrows.append(
            {
                "field": col,
                "true_p25": float(ts.quantile(0.25)) if len(ts) else np.nan,
                "true_p50": float(ts.quantile(0.50)) if len(ts) else np.nan,
                "true_p75": float(ts.quantile(0.75)) if len(ts) else np.nan,
                "false_p25": float(fs.quantile(0.25)) if len(fs) else np.nan,
                "false_p50": float(fs.quantile(0.50)) if len(fs) else np.nan,
                "false_p75": float(fs.quantile(0.75)) if len(fs) else np.nan,
                "true_n": int(len(ts)),
                "false_n": int(len(fs)),
            }
        )
    quantile_compare = pd.DataFrame(qrows)

    return {
        "summary_monthly": monthly,
        "summary_industry": industry,
        "summary_false_reason": false_reason,
        "summary_path_by_month": path_month,
        "summary_quantile_compare": quantile_compare,
    }


def build_true_start_labels_v2(
    db: DatabaseManager,
    start_date: str,
    end_date: str,
    cfg: Optional[TrueStartLabelV2Config] = None,
    miner_cfg: Optional[SampleMiningConfig] = None,
) -> Tuple[pd.DataFrame, Dict[str, Any], Dict[str, pd.DataFrame]]:
    """
    全市场扫描：加载面板 -> 候选池 -> 打标。

    返回：带标签的 DataFrame、质检摘要字典、五张研究用质检表。
    """
    cfg = cfg or TrueStartLabelV2Config()
    miner_cfg = miner_cfg or SampleMiningConfig()
    miner_cfg.hold_days = 5

    miner = StrongStartSampleMiner(db, miner_cfg)
    load_start = _date_minus(start_date, 180)
    load_end = _date_plus(end_date, 25)
    panel = miner._load_panel(load_start, load_end, forward_days=5)
    if panel.empty:
        return pd.DataFrame(), {"error": "empty_panel"}, {}

    panel = panel.loc[panel["ts_code"] != miner_cfg.index_code].copy()
    panel = enrich_v2_columns(panel)

    m = candidate_mask_platform_break_v2(panel, cfg, index_code=miner_cfg.index_code)
    snap = panel.loc[m].copy()
    snap = snap.loc[
        (snap["trade_date"] >= pd.Timestamp(start_date)) & (snap["trade_date"] <= pd.Timestamp(end_date))
    ]

    if snap.empty:
        return pd.DataFrame(), {"candidate_rows": 0, "message": "no_candidates_in_window"}, {}

    labeled = compute_forward_metrics_v2(snap, cfg)
    labeled["trade_date"] = _fmt_date_series(labeled["trade_date"])

    tables = build_research_summaries(labeled)
    tier_a = int((labeled["true_start_tier"].astype(str) == "A").sum()) if "true_start_tier" in labeled.columns else 0
    tier_b = int((labeled["true_start_tier"].astype(str) == "B").sum()) if "true_start_tier" in labeled.columns else 0

    summary: Dict[str, Any] = {
        "label_version": cfg.label_version,
        "start_date": start_date,
        "end_date": end_date,
        "candidate_rows": int(len(labeled)),
        "true_start": int(labeled["label_true_start"].sum()),
        "false_start": int(labeled["label_false_start"].sum()),
        "neutral": int(labeled["label_neutral"].sum()),
        "true_start_tier_A": tier_a,
        "true_start_tier_B": tier_b,
        "untradable_flag_count": int(labeled["limit_up_untradable_flag"].sum()),
        "missing_forward_window": int((~labeled["has_full_forward_window"]).sum()),
    }
    return labeled, summary, tables


def save_outputs(
    df: pd.DataFrame,
    summary: Dict[str, Any],
    output_dir: str,
    prefix: str = "true_start_v2",
    tables: Optional[Dict[str, pd.DataFrame]] = None,
) -> Dict[str, str]:
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = pd.Timestamp.now().strftime("%Y%m%d_%H%M%S")
    parquet_path = out_dir / f"{prefix}_labeled_{ts}.parquet"
    csv_path = out_dir / f"{prefix}_labeled_{ts}.csv"
    summary_path = out_dir / f"{prefix}_summary_{ts}.json"

    df.to_parquet(parquet_path, index=False)
    # CSV 便于 Excel 查看；列多时可只打开 parquet
    df.to_csv(csv_path, index=False, encoding="utf-8-sig")

    import json

    table_paths: Dict[str, str] = {}
    if tables:
        for name, tdf in tables.items():
            if tdf is None or tdf.empty:
                continue
            p = out_dir / f"{name}_{ts}.csv"
            tdf.to_csv(p, index=False, encoding="utf-8-sig")
            table_paths[name] = str(p)
        summary = dict(summary)
        summary["research_table_paths"] = table_paths

    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    out = {"parquet": str(parquet_path), "csv": str(csv_path), "summary": str(summary_path)}
    out.update(table_paths)
    return out
