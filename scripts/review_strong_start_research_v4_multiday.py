# -*- coding: utf-8 -*-
"""Multiday structural review for strong_start_research_v4 (no backtest, no PnL).

Outputs:
- v4_scan_multiday_loose.parquet
- v4_scan_multiday_neutral.parquet
- v4_scan_multiday_strict.parquet
- v4_scan_funnel_summary.csv
- v4_filter_reason_summary.csv
- v4_trigger_fail_summary.csv
- v4_score_distribution_summary.csv
- v4_explain_sample_review.csv
- v4_structure_scan_review_report.md
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core.database import DatabaseManager
from src.modules.strong_start_research_v4 import StrongStartResearchV4


def _chunked(items: List[str], size: int) -> Iterable[List[str]]:
    for i in range(0, len(items), size):
        yield items[i : i + size]


def _safe_json_loads(raw: Any, default: Any) -> Any:
    if raw is None:
        return default
    txt = str(raw)
    if not txt:
        return default
    try:
        return json.loads(txt)
    except Exception:
        return default


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def _parse_min_score(cfg: Dict[str, Any], profile: str) -> float:
    node = (cfg.get("scoring", {}) or {}).get("min_total_score", {}) or {}
    v = node.get(profile)
    try:
        return float(v)
    except Exception:
        return 50.0


def _fetch_basic(db: DatabaseManager) -> pd.DataFrame:
    sql = "SELECT ts_code, name, industry, list_date FROM stock_basic"
    df = db.query_to_dataframe(sql)
    if df.empty:
        return pd.DataFrame(columns=["ts_code", "name", "industry", "list_date"])
    df["list_date"] = pd.to_datetime(df["list_date"].astype(str), format="%Y%m%d", errors="coerce")
    df["industry"] = df["industry"].fillna("UNKNOWN").replace("", "UNKNOWN")
    return df


def _fetch_daily(
    db: DatabaseManager,
    ts_codes: List[str],
    start_date: str,
    end_date: str,
) -> pd.DataFrame:
    if not ts_codes:
        return pd.DataFrame(columns=["ts_code", "trade_date", "close", "amount", "amount_ma20"])

    frames: List[pd.DataFrame] = []
    for block in _chunked(sorted(set(ts_codes)), 400):
        placeholders = ",".join("?" for _ in block)
        sql = f"""
            SELECT ts_code, trade_date, close, amount
            FROM stock_daily
            WHERE ts_code IN ({placeholders})
              AND trade_date >= ? AND trade_date <= ?
            ORDER BY ts_code ASC, trade_date ASC
        """
        params = tuple(block) + (start_date, end_date)
        chunk = db.query_to_dataframe(sql, params)
        if not chunk.empty:
            frames.append(chunk)

    if not frames:
        return pd.DataFrame(columns=["ts_code", "trade_date", "close", "amount", "amount_ma20"])

    daily = pd.concat(frames, ignore_index=True)
    daily["close"] = pd.to_numeric(daily["close"], errors="coerce")
    daily["amount"] = pd.to_numeric(daily["amount"], errors="coerce")
    daily = daily.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)
    daily["amount_ma20"] = daily.groupby("ts_code")["amount"].transform(
        lambda s: s.rolling(20, min_periods=10).mean()
    )
    return daily


def _prepare_base_frame(
    snapshot_path: Path,
    lookback_days: int,
    start_date: str,
    end_date: str,
) -> Tuple[pd.DataFrame, str, str, int]:
    snap = pd.read_parquet(snapshot_path)
    snap["trade_date"] = snap["trade_date"].astype(str)

    all_dates = sorted(snap["trade_date"].unique().tolist())
    if not all_dates:
        raise ValueError("snapshot has no trade_date")

    if start_date and end_date:
        selected = [d for d in all_dates if start_date <= d <= end_date]
    else:
        selected = all_dates[-lookback_days:]

    if not selected:
        raise ValueError("no dates selected for review window")

    start = selected[0]
    end = selected[-1]
    base = snap[snap["trade_date"].isin(selected)].copy()
    base = base.sort_values(["trade_date", "ts_code"]).reset_index(drop=True)
    return base, start, end, len(selected)


def _enrich_for_strategy(base: pd.DataFrame, db: DatabaseManager, start: str, end: str) -> pd.DataFrame:
    ts_codes = sorted(base["ts_code"].astype(str).unique().tolist())
    basic = _fetch_basic(db)
    start_buffer = (
        pd.to_datetime(start, format="%Y%m%d", errors="coerce") - pd.Timedelta(days=80)
    ).strftime("%Y%m%d")
    daily = _fetch_daily(db, ts_codes, start_buffer, end)

    out = base.merge(
        basic[["ts_code", "name", "industry", "list_date"]],
        on="ts_code",
        how="left",
        suffixes=("", "_basic"),
    )
    if "name_basic" in out.columns:
        out["name"] = out["name"].fillna(out["name_basic"]).fillna("")
        out = out.drop(columns=["name_basic"])
    else:
        out["name"] = out["name"].fillna("")

    if "industry_basic" in out.columns:
        out["industry"] = out["industry"].fillna(out["industry_basic"]).fillna("UNKNOWN")
        out = out.drop(columns=["industry_basic"])
    else:
        out["industry"] = out["industry"].fillna("UNKNOWN")
    out["industry"] = out["industry"].replace("", "UNKNOWN")

    if not daily.empty:
        out = out.merge(
            daily[["ts_code", "trade_date", "close", "amount_ma20"]],
            on=["ts_code", "trade_date"],
            how="left",
            suffixes=("", "_daily"),
        )
        if "close_daily" in out.columns:
            out["close"] = pd.to_numeric(out["close"], errors="coerce").fillna(
                pd.to_numeric(out["close_daily"], errors="coerce")
            )
            out = out.drop(columns=["close_daily"])
    else:
        if "amount_ma20" not in out.columns:
            out["amount_ma20"] = np.nan
        if "close" not in out.columns:
            out["close"] = np.nan

    trade_dt = pd.to_datetime(out["trade_date"], format="%Y%m%d", errors="coerce")
    out["list_days"] = (trade_dt - pd.to_datetime(out["list_date"], errors="coerce")).dt.days
    return out


def _daily_funnel(df: pd.DataFrame, profile: str, min_score: float) -> pd.DataFrame:
    work = df.copy()
    work["score_gate_pass"] = (
        work["is_candidate_after_filters"].fillna(False)
        & (pd.to_numeric(work["score_total"], errors="coerce") >= float(min_score))
    )
    g = (
        work.groupby("trade_date")
        .agg(
            universe_n=("ts_code", "count"),
            after_filter_n=("is_candidate_after_filters", "sum"),
            score_gate_n=("score_gate_pass", "sum"),
            breakout_pass_n=("trigger_breakout_pass", "sum"),
            momentum_pass_n=("trigger_momentum_pass", "sum"),
            quality_pass_n=("trigger_quality_pass", "sum"),
            trigger_pass_n=("trigger_status", "sum"),
            signal_ready_n=("signal_ready", "sum"),
            score_total_median=("score_total", "median"),
            score_total_p75=("score_total", lambda s: s.quantile(0.75)),
            score_total_p90=("score_total", lambda s: s.quantile(0.90)),
        )
        .reset_index()
    )
    g["profile"] = profile
    for col in [
        "after_filter_n",
        "score_gate_n",
        "breakout_pass_n",
        "momentum_pass_n",
        "quality_pass_n",
        "trigger_pass_n",
        "signal_ready_n",
    ]:
        g[f"{col}_rate"] = g[col] / g["universe_n"].replace(0, np.nan)
    return g


def _period_funnel_row(daily_df: pd.DataFrame, profile: str) -> pd.DataFrame:
    row = {
        "profile": profile,
        "trade_date": "ALL",
        "universe_n": int(daily_df["universe_n"].sum()),
        "after_filter_n": int(daily_df["after_filter_n"].sum()),
        "score_gate_n": int(daily_df["score_gate_n"].sum()),
        "breakout_pass_n": int(daily_df["breakout_pass_n"].sum()),
        "momentum_pass_n": int(daily_df["momentum_pass_n"].sum()),
        "quality_pass_n": int(daily_df["quality_pass_n"].sum()),
        "trigger_pass_n": int(daily_df["trigger_pass_n"].sum()),
        "signal_ready_n": int(daily_df["signal_ready_n"].sum()),
        "score_total_median": float(daily_df["score_total_median"].median()),
        "score_total_p75": float(daily_df["score_total_p75"].median()),
        "score_total_p90": float(daily_df["score_total_p90"].median()),
    }
    uni = row["universe_n"] or 1
    for col in [
        "after_filter_n",
        "score_gate_n",
        "breakout_pass_n",
        "momentum_pass_n",
        "quality_pass_n",
        "trigger_pass_n",
        "signal_ready_n",
    ]:
        row[f"{col}_rate"] = float(row[col]) / float(uni)
    return pd.DataFrame([row])


def _collect_filter_reason(df: pd.DataFrame, profile: str) -> pd.DataFrame:
    rows: List[Dict[str, Any]] = []
    failed_events = int((~df["is_candidate_after_filters"].fillna(False)).sum())
    for raw in df["filter_reject_reasons"].fillna("[]").astype(str):
        reasons = _safe_json_loads(raw, [])
        if not isinstance(reasons, list):
            continue
        for r in reasons:
            rows.append({"profile": profile, "reason": str(r)})
    if not rows:
        return pd.DataFrame(columns=["profile", "reason", "hit_count", "failed_events", "hit_ratio_among_failed"])
    out = pd.DataFrame(rows).groupby(["profile", "reason"]).size().reset_index(name="hit_count")
    out["failed_events"] = failed_events
    out["hit_ratio_among_failed"] = out["hit_count"] / max(failed_events, 1)
    out = out.sort_values(["profile", "hit_count"], ascending=[True, False]).reset_index(drop=True)
    return out


def _collect_trigger_fail(df: pd.DataFrame, profile: str) -> pd.DataFrame:
    rows: List[Dict[str, Any]] = []
    after_filter_events = int(df["is_candidate_after_filters"].fillna(False).sum())
    ref = df[df["is_candidate_after_filters"].fillna(False)].copy()
    for raw in ref["trigger_details"].fillna("{}").astype(str):
        obj = _safe_json_loads(raw, {})
        if not isinstance(obj, dict):
            continue
        for group_name, payload in obj.items():
            if not isinstance(payload, dict):
                continue
            for rid in payload.get("failed_rules", []) or []:
                rows.append(
                    {
                        "profile": profile,
                        "trigger_group": str(group_name),
                        "rule_id": str(rid),
                    }
                )
    if not rows:
        return pd.DataFrame(
            columns=[
                "profile",
                "trigger_group",
                "rule_id",
                "fail_count",
                "after_filter_events",
                "fail_ratio_after_filter",
            ]
        )
    out = (
        pd.DataFrame(rows)
        .groupby(["profile", "trigger_group", "rule_id"])
        .size()
        .reset_index(name="fail_count")
    )
    out["after_filter_events"] = after_filter_events
    out["fail_ratio_after_filter"] = out["fail_count"] / max(after_filter_events, 1)
    out = out.sort_values(["profile", "fail_count"], ascending=[True, False]).reset_index(drop=True)
    return out


def _collect_score_distribution(df: pd.DataFrame, profile: str) -> pd.DataFrame:
    metrics = ["score_total", "score_axis_strength", "score_axis_industry", "score_axis_chip"]
    rows: List[Dict[str, Any]] = []
    for m in metrics:
        s = pd.to_numeric(df[m], errors="coerce").dropna()
        if s.empty:
            continue
        rows.append(
            {
                "profile": profile,
                "metric": m,
                "count": int(s.shape[0]),
                "mean": float(s.mean()),
                "std": float(s.std(ddof=0)),
                "min": float(s.min()),
                "p10": float(s.quantile(0.10)),
                "p25": float(s.quantile(0.25)),
                "median": float(s.median()),
                "p75": float(s.quantile(0.75)),
                "p90": float(s.quantile(0.90)),
                "max": float(s.max()),
            }
        )

    score = pd.to_numeric(df["score_total"], errors="coerce")
    for axis in ["score_axis_strength", "score_axis_industry", "score_axis_chip"]:
        a = pd.to_numeric(df[axis], errors="coerce")
        mask = score > 0
        share = (a[mask] / score[mask]).replace([np.inf, -np.inf], np.nan).dropna()
        if share.empty:
            continue
        rows.append(
            {
                "profile": profile,
                "metric": f"{axis}_share_of_total",
                "count": int(share.shape[0]),
                "mean": float(share.mean()),
                "std": float(share.std(ddof=0)),
                "min": float(share.min()),
                "p10": float(share.quantile(0.10)),
                "p25": float(share.quantile(0.25)),
                "median": float(share.median()),
                "p75": float(share.quantile(0.75)),
                "p90": float(share.quantile(0.90)),
                "max": float(share.max()),
            }
        )
    return pd.DataFrame(rows)


def _top_score_reasons(score_details_raw: Any, topn: int = 3) -> List[str]:
    obj = _safe_json_loads(score_details_raw, {})
    if not isinstance(obj, dict):
        return []
    pairs: List[Tuple[str, float]] = []
    for _, axis_payload in obj.items():
        if not isinstance(axis_payload, dict):
            continue
        feats = axis_payload.get("features", {})
        if not isinstance(feats, dict):
            continue
        for feat, payload in feats.items():
            if not isinstance(payload, dict):
                continue
            c = payload.get("contribution")
            try:
                val = float(c)
            except Exception:
                continue
            pairs.append((str(feat), val))
    pairs.sort(key=lambda x: x[1], reverse=True)
    return [f"score:{k}" for k, _ in pairs[:topn]]


def _top_trigger_fail_reasons(trigger_details_raw: Any, topn: int = 3) -> List[str]:
    obj = _safe_json_loads(trigger_details_raw, {})
    if not isinstance(obj, dict):
        return []
    out: List[str] = []
    for group, payload in obj.items():
        if not isinstance(payload, dict):
            continue
        failed = payload.get("failed_rules", []) or []
        for rid in failed:
            out.append(f"trigger:{group}:{rid}")
            if len(out) >= topn:
                return out
    return out[:topn]


def _top_filter_reasons(filter_reject_raw: Any, topn: int = 3) -> List[str]:
    arr = _safe_json_loads(filter_reject_raw, [])
    if not isinstance(arr, list):
        return []
    return [f"filter:{str(x)}" for x in arr[:topn]]


def _extract_reason3(row: pd.Series) -> List[str]:
    passed_filter = bool(row.get("is_candidate_after_filters", False))
    trigger_ok = bool(row.get("trigger_status", False))
    if not passed_filter:
        reasons = _top_filter_reasons(row.get("filter_reject_reasons"), 3)
    elif not trigger_ok:
        reasons = _top_trigger_fail_reasons(row.get("trigger_details"), 3)
    else:
        reasons = _top_score_reasons(row.get("score_details"), 3)
    while len(reasons) < 3:
        reasons.append("")
    return reasons[:3]


def _sample_bucket(
    df: pd.DataFrame,
    bucket: str,
    k: int,
    used_idx: set[int],
    min_score: float,
    loose_rs20: float,
    loose_ma20_gap: float,
) -> pd.DataFrame:
    work = df.copy()
    if bucket == "filter_reject_but_strong_looking":
        cond = (
            (~work["is_candidate_after_filters"].fillna(False))
            & (pd.to_numeric(work["f_strength_rs20_xsec_q"], errors="coerce") >= loose_rs20)
            & (pd.to_numeric(work["f_trend_close_ma20_gap"], errors="coerce") >= loose_ma20_gap)
        )
        sub = work[cond].sort_values(["f_strength_rs20_xsec_q", "score_total"], ascending=[False, False])
    elif bucket == "high_score_trigger_fail":
        base = work[work["is_candidate_after_filters"].fillna(False)].copy()
        p75 = float(pd.to_numeric(base["score_total"], errors="coerce").quantile(0.75)) if not base.empty else min_score
        cond = (
            work["is_candidate_after_filters"].fillna(False)
            & (~work["trigger_status"].fillna(False))
            & (pd.to_numeric(work["score_total"], errors="coerce") >= p75)
        )
        sub = work[cond].sort_values(["score_total", "trade_date"], ascending=[False, False])
    elif bucket == "signal_ready_true":
        sub = work[work["signal_ready"].fillna(False)].sort_values(["score_total", "trade_date"], ascending=[False, False])
    elif bucket == "score_threshold_gray_zone":
        score = pd.to_numeric(work["score_total"], errors="coerce")
        base_cond = work["is_candidate_after_filters"].fillna(False)
        abs_gap = (score - min_score).abs()
        cond = base_cond & (abs_gap <= 3.0)
        sub = work[cond].assign(_abs_gap=abs_gap[cond])
        if sub.shape[0] < k:
            cond = base_cond & (abs_gap <= 5.0)
            sub = work[cond].assign(_abs_gap=abs_gap[cond])
        if sub.shape[0] < k:
            cond = base_cond & (abs_gap <= 8.0)
            sub = work[cond].assign(_abs_gap=abs_gap[cond])
        if sub.shape[0] < k:
            cond = base_cond
            sub = work[cond].assign(_abs_gap=abs_gap[cond])
        sub = sub.sort_values(["_abs_gap", "trade_date"], ascending=[True, False]).drop(columns=["_abs_gap"])
    else:
        sub = work.iloc[0:0]

    if sub.empty:
        return sub
    sub = sub.loc[[i for i in sub.index if i not in used_idx]]
    sub = sub.head(k)
    return sub


def _build_sample_review(
    neutral_df: pd.DataFrame,
    min_score: float,
    loose_rs20: float,
    loose_ma20_gap: float,
    per_bucket: int = 8,
) -> pd.DataFrame:
    buckets = [
        "filter_reject_but_strong_looking",
        "high_score_trigger_fail",
        "signal_ready_true",
        "score_threshold_gray_zone",
    ]
    used: set[int] = set()
    frames: List[pd.DataFrame] = []
    for b in buckets:
        sampled = _sample_bucket(
            neutral_df,
            b,
            k=per_bucket,
            used_idx=used,
            min_score=min_score,
            loose_rs20=loose_rs20,
            loose_ma20_gap=loose_ma20_gap,
        )
        if sampled.empty:
            continue
        used.update(sampled.index.tolist())
        sampled = sampled.copy()
        sampled["sample_bucket"] = b
        reasons = sampled.apply(_extract_reason3, axis=1, result_type="expand")
        sampled["key_reason_1"] = reasons[0]
        sampled["key_reason_2"] = reasons[1]
        sampled["key_reason_3"] = reasons[2]
        frames.append(sampled)
    if not frames:
        return pd.DataFrame()

    out = pd.concat(frames, axis=0).reset_index(drop=True)
    keep_cols = [
        "trade_date",
        "ts_code",
        "name",
        "industry",
        "sample_bucket",
        "is_candidate_after_filters",
        "score_total",
        "score_axis_strength",
        "score_axis_industry",
        "score_axis_chip",
        "trigger_breakout_pass",
        "trigger_momentum_pass",
        "trigger_quality_pass",
        "trigger_status",
        "signal_ready",
        "key_reason_1",
        "key_reason_2",
        "key_reason_3",
    ]
    return out[keep_cols]


def _build_report_md(
    report_path: Path,
    start_date: str,
    end_date: str,
    days_count: int,
    funnel: pd.DataFrame,
    filter_reason: pd.DataFrame,
    trigger_fail: pd.DataFrame,
    score_dist: pd.DataFrame,
    sample_df: pd.DataFrame,
) -> None:
    period = funnel[funnel["trade_date"] == "ALL"].copy().sort_values("profile")
    def _line(row: pd.Series) -> str:
        return (
            f"- {row['profile']}: universe={int(row['universe_n'])}, "
            f"after_filter={int(row['after_filter_n'])} ({row['after_filter_n_rate']:.2%}), "
            f"trigger_pass={int(row['trigger_pass_n'])} ({row['trigger_pass_n_rate']:.2%}), "
            f"ready={int(row['signal_ready_n'])} ({row['signal_ready_n_rate']:.2%})"
        )

    lines: List[str] = []
    lines.append("# v4 Structure Scan Review (Multiday, No Backtest)")
    lines.append("")
    lines.append(f"- Window: `{start_date}` to `{end_date}`")
    lines.append(f"- Trading days scanned: `{days_count}`")
    lines.append("- Scope: structure-only diagnostics (filters/scoring/trigger/explainability)")
    lines.append("")
    lines.append("## Profile Gradient Snapshot")
    for _, r in period.iterrows():
        lines.append(_line(r))
    lines.append("")
    lines.append("## Top Filter Reasons (per profile)")
    for p in ["loose", "neutral", "strict"]:
        sub = filter_reason[filter_reason["profile"] == p].head(5)
        lines.append(f"- {p}:")
        if sub.empty:
            lines.append("  - (no filter reject)")
        else:
            for _, rr in sub.iterrows():
                lines.append(f"  - {rr['reason']}: {int(rr['hit_count'])}")
    lines.append("")
    lines.append("## Top Trigger Fails (per profile)")
    for p in ["loose", "neutral", "strict"]:
        sub = trigger_fail[trigger_fail["profile"] == p].head(5)
        lines.append(f"- {p}:")
        if sub.empty:
            lines.append("  - (no trigger fail)")
        else:
            for _, rr in sub.iterrows():
                lines.append(f"  - {rr['trigger_group']}:{rr['rule_id']}: {int(rr['fail_count'])}")
    lines.append("")
    lines.append("## Score Distribution (median)")
    for p in ["loose", "neutral", "strict"]:
        sub = score_dist[(score_dist["profile"] == p) & (score_dist["metric"].isin(
            ["score_total", "score_axis_strength", "score_axis_industry", "score_axis_chip"]
        ))]
        lines.append(f"- {p}:")
        if sub.empty:
            lines.append("  - (no score stats)")
        else:
            for _, rr in sub.iterrows():
                lines.append(f"  - {rr['metric']}: median={rr['median']:.4f}, p75={rr['p75']:.4f}, p90={rr['p90']:.4f}")
    lines.append("")
    lines.append("## Explainability Sample Review")
    if sample_df.empty:
        lines.append("- No sampled rows.")
    else:
        bucket_counts = sample_df.groupby("sample_bucket").size().to_dict()
        for b, c in bucket_counts.items():
            lines.append(f"- {b}: {int(c)} samples")
    lines.append("")
    lines.append("## Notes")
    lines.append("- This report does not include any return, win-rate, or drawdown metrics.")
    lines.append("- Purpose is only structural sanity and interpretability review.")
    report_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Multiday structural review for strong_start_research_v4.")
    parser.add_argument(
        "--snapshot",
        type=str,
        default="data/research/strong_start_full/event_feature_snapshot_batch4.parquet",
    )
    parser.add_argument("--config", type=str, default="config/strong_start_research_v4_config.yaml")
    parser.add_argument("--lookback-days", type=int, default=30)
    parser.add_argument("--start-date", type=str, default="")
    parser.add_argument("--end-date", type=str, default="")
    parser.add_argument("--output-dir", type=str, default="data/research/strong_start_full/v4_scan")
    args = parser.parse_args()

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    snapshot_path = Path(args.snapshot)
    if not snapshot_path.exists():
        raise FileNotFoundError(f"snapshot not found: {snapshot_path}")

    db = DatabaseManager()
    base, start_date, end_date, days_count = _prepare_base_frame(
        snapshot_path=snapshot_path,
        lookback_days=int(args.lookback_days),
        start_date=str(args.start_date or ""),
        end_date=str(args.end_date or ""),
    )
    enriched = _enrich_for_strategy(base, db, start_date, end_date)

    strategy = StrongStartResearchV4(config_path=args.config)
    profiles = ["loose", "neutral", "strict"]

    all_funnels: List[pd.DataFrame] = []
    all_filter_reason: List[pd.DataFrame] = []
    all_trigger_fail: List[pd.DataFrame] = []
    all_score_dist: List[pd.DataFrame] = []
    result_by_profile: Dict[str, pd.DataFrame] = {}

    for p in profiles:
        res = strategy.run_on_dataframe(enriched, profile=p).copy()
        result_by_profile[p] = res

        p_out = out_dir / f"v4_scan_multiday_{p}.parquet"
        res.to_parquet(p_out, index=False)

        min_score = _parse_min_score(strategy.config, p)
        day_funnel = _daily_funnel(res, p, min_score=min_score)
        all_funnels.append(day_funnel)
        all_funnels.append(_period_funnel_row(day_funnel, p))

        all_filter_reason.append(_collect_filter_reason(res, p))
        all_trigger_fail.append(_collect_trigger_fail(res, p))
        all_score_dist.append(_collect_score_distribution(res, p))

    funnel = pd.concat(all_funnels, ignore_index=True) if all_funnels else pd.DataFrame()
    filter_reason = pd.concat(all_filter_reason, ignore_index=True) if all_filter_reason else pd.DataFrame()
    trigger_fail = pd.concat(all_trigger_fail, ignore_index=True) if all_trigger_fail else pd.DataFrame()
    score_dist = pd.concat(all_score_dist, ignore_index=True) if all_score_dist else pd.DataFrame()

    neutral = result_by_profile.get("neutral", pd.DataFrame())
    loose_rs20 = float(
        strategy.config["hard_filters"]["rules"][1]["thresholds"]["loose"]  # strength_rs20_xsec_q
    )
    loose_ma20_gap = float(
        strategy.config["hard_filters"]["rules"][0]["thresholds"]["loose"]  # trend_close_ma20_gap
    )
    neutral_min_score = _parse_min_score(strategy.config, "neutral")
    sample = _build_sample_review(
        neutral_df=neutral,
        min_score=neutral_min_score,
        loose_rs20=loose_rs20,
        loose_ma20_gap=loose_ma20_gap,
        per_bucket=8,
    )

    funnel_path = out_dir / "v4_scan_funnel_summary.csv"
    filter_path = out_dir / "v4_filter_reason_summary.csv"
    trigger_path = out_dir / "v4_trigger_fail_summary.csv"
    score_path = out_dir / "v4_score_distribution_summary.csv"
    sample_path = out_dir / "v4_explain_sample_review.csv"
    report_path = out_dir / "v4_structure_scan_review_report.md"

    funnel.to_csv(funnel_path, index=False, encoding="utf-8-sig")
    filter_reason.to_csv(filter_path, index=False, encoding="utf-8-sig")
    trigger_fail.to_csv(trigger_path, index=False, encoding="utf-8-sig")
    score_dist.to_csv(score_path, index=False, encoding="utf-8-sig")
    sample.to_csv(sample_path, index=False, encoding="utf-8-sig")

    _build_report_md(
        report_path=report_path,
        start_date=start_date,
        end_date=end_date,
        days_count=days_count,
        funnel=funnel,
        filter_reason=filter_reason,
        trigger_fail=trigger_fail,
        score_dist=score_dist,
        sample_df=sample,
    )

    summary = {
        "window": {"start_date": start_date, "end_date": end_date, "days": days_count},
        "profiles": profiles,
        "outputs": {
            "loose": str(out_dir / "v4_scan_multiday_loose.parquet"),
            "neutral": str(out_dir / "v4_scan_multiday_neutral.parquet"),
            "strict": str(out_dir / "v4_scan_multiday_strict.parquet"),
            "funnel": str(funnel_path),
            "filter_reason": str(filter_path),
            "trigger_fail": str(trigger_path),
            "score_distribution": str(score_path),
            "sample_review": str(sample_path),
            "report": str(report_path),
        },
    }
    summary_path = out_dir / "v4_scan_multiday_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print("=" * 72)
    print("strong_start_research_v4 multiday structural review complete")
    print("=" * 72)
    print(f"window={start_date}..{end_date} ({days_count} trade days)")
    print(f"summary={summary_path}")


if __name__ == "__main__":
    main()
