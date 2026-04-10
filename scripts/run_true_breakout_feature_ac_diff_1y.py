from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Dict, List

import numpy as np
import pandas as pd


ROOT = Path(r"D:\HuaweiAI\quantSystem2")
DB_PATH = ROOT / "data/database/quant_system.db"
LABELED = ROOT / "data/research/strong_start_full/v4_scan/true_breakout_labeled_events_1y.parquet"
OUT_DIR = ROOT / "data/research/strong_start_full/v4_scan"

OUT_SNAPSHOT = OUT_DIR / "true_breakout_feature_snapshot_1y.parquet"
OUT_BOUNDARY = OUT_DIR / "true_breakout_feature_boundary_audit.csv"
OUT_DIFF = OUT_DIR / "true_breakout_ac_diff_summary.csv"
OUT_RANK = OUT_DIR / "true_breakout_feature_rankings.csv"
OUT_FAMILY = OUT_DIR / "true_breakout_feature_family_summary.md"
OUT_GREY = OUT_DIR / "true_breakout_greyzone_observation.md"
OUT_FACTORS = OUT_DIR / "true_breakout_factor_candidates.md"


SPECIAL_K_FEATURES = [
    "f_k_pct_chg",
    "f_k_body_to_atr",
    "f_breakout_vol_ratio20",
    "f_k_upper_shadow_ratio",
    "f_up_down_vol_ratio20",
]


def _main_board(ts: str) -> bool:
    if not isinstance(ts, str) or "." not in ts:
        return False
    code, exch = ts.split(".")
    if exch == "SH":
        return code.startswith(("600", "601", "603", "605"))
    if exch == "SZ":
        return code.startswith(("000", "001", "002", "003"))
    return False


def _cliffs_delta(a: np.ndarray, c: np.ndarray) -> float:
    a = np.asarray(a, dtype=float)
    c = np.asarray(c, dtype=float)
    a = a[~np.isnan(a)]
    c = c[~np.isnan(c)]
    n1, n2 = len(a), len(c)
    if n1 == 0 or n2 == 0:
        return np.nan
    x = np.concatenate([a, c])
    ranks = pd.Series(x).rank(method="average").to_numpy()
    r1 = ranks[:n1].sum()
    u1 = r1 - n1 * (n1 + 1) / 2
    return float(2 * u1 / (n1 * n2) - 1)


def _load_base() -> tuple[pd.DataFrame, pd.DataFrame]:
    lab = pd.read_parquet(LABELED).copy()
    lab["trade_date"] = lab["trade_date"].astype(str)
    event_keys = lab[["ts_code", "trade_date"]].drop_duplicates().copy()
    stocks = event_keys["ts_code"].unique().tolist()

    conn = sqlite3.connect(DB_PATH)
    try:
        q_marks = ",".join(["?"] * len(stocks))
        daily = pd.read_sql_query(
            f"""
            select ts_code, trade_date, open, high, low, close, vol, amount, pct_chg
            from stock_daily
            where ts_code in ({q_marks}) or ts_code='000001.SH'
            """,
            conn,
            params=stocks,
        )
        basic = pd.read_sql_query(
            "select ts_code, name, industry from stock_basic",
            conn,
        )
        chip = pd.read_sql_query(
            """
            select ts_code, trade_date, cost_5pct, cost_15pct, cost_50pct, cost_85pct, cost_95pct, winner_rate
            from stock_chip_perf
            """,
            conn,
        )
        chip_profile = pd.read_sql_query(
            """
            select ts_code, trade_date, profile_key, chip_peak_count_sig, chip_secondary_peak_ratio,
                   chip_peak_dominance, single_peak_dense_score
            from stock_chip_dist_factor_profile
            where profile_key='tradeable_v3_research'
            """,
            conn,
        )
    finally:
        conn.close()

    for df in [daily, chip, chip_profile]:
        df["trade_date"] = df["trade_date"].astype(str)
    for c in ["open", "high", "low", "close", "vol", "amount", "pct_chg"]:
        daily[c] = pd.to_numeric(daily[c], errors="coerce")

    daily = daily.merge(basic, on="ts_code", how="left")
    daily = daily.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)
    return lab, daily.merge(chip, on=["ts_code", "trade_date"], how="left").merge(
        chip_profile.drop(columns=["profile_key"]),
        on=["ts_code", "trade_date"],
        how="left",
    )


def _compute_features(daily: pd.DataFrame) -> pd.DataFrame:
    d = daily.copy()
    g = d.groupby("ts_code", group_keys=False)

    # trend/strength
    d["f_strength_ret20"] = d["close"] / g["close"].shift(20) - 1
    d["f_strength_ret60"] = d["close"] / g["close"].shift(60) - 1
    d["f_strength_rs20_xsec_q"] = d.groupby("trade_date")["f_strength_ret20"].rank(method="average", pct=True)
    d["f_strength_rs60_xsec_q"] = d.groupby("trade_date")["f_strength_ret60"].rank(method="average", pct=True)

    d["ma20"] = g["close"].transform(lambda s: s.rolling(20, min_periods=20).mean())
    d["ma60"] = g["close"].transform(lambda s: s.rolling(60, min_periods=60).mean())
    d["f_trend_close_ma20_gap"] = d["close"] / d["ma20"] - 1
    d["f_trend_close_ma60_gap"] = d["close"] / d["ma60"] - 1
    d["f_trend_ma20_ma60_gap"] = d["ma20"] / d["ma60"] - 1
    d["f_trend_ma20_slope5"] = d["ma20"] / g["ma20"].shift(5) - 1

    # price/platform
    hh20_prev = g["high"].transform(lambda s: s.rolling(20, min_periods=20).max().shift(1))
    ll20_prev = g["low"].transform(lambda s: s.rolling(20, min_periods=20).min().shift(1))
    hh30_prev = g["high"].transform(lambda s: s.rolling(30, min_periods=30).max().shift(1))
    ll30_prev = g["low"].transform(lambda s: s.rolling(30, min_periods=30).min().shift(1))
    d["f_platform_range20"] = (hh20_prev - ll20_prev) / d["close"].replace(0, np.nan)
    d["f_platform_range30"] = (hh30_prev - ll30_prev) / d["close"].replace(0, np.nan)
    d["f_platform_range_best"] = np.minimum(d["f_platform_range20"], d["f_platform_range30"])
    range10_prev = g["high"].transform(lambda s: s.rolling(10, min_periods=10).max().shift(1)) - g["low"].transform(
        lambda s: s.rolling(10, min_periods=10).min().shift(1)
    )
    range30_prev = hh30_prev - ll30_prev
    d["f_platform_compress_ratio"] = range10_prev / range30_prev.replace(0, np.nan)
    d["f_near_pivot20"] = d["close"] / hh20_prev - 1

    # a simple platform length proxy: count of last 20 days with close within prior 30d band
    d["tmp_in_band"] = ((d["close"] <= hh30_prev * 1.02) & (d["close"] >= ll30_prev * 0.98)).astype(float)
    d["f_platform_len"] = g["tmp_in_band"].transform(lambda s: s.rolling(20, min_periods=5).sum())

    # atr
    prev_close = g["close"].shift(1)
    tr = pd.concat(
        [
            (d["high"] - d["low"]).abs(),
            (d["high"] - prev_close).abs(),
            (d["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    d["tmp_tr"] = tr
    d["atr14"] = g["tmp_tr"].transform(lambda s: s.rolling(14, min_periods=14).mean())
    d["atr60"] = g["tmp_tr"].transform(lambda s: s.rolling(60, min_periods=30).mean())
    d["f_atr_ratio"] = d["atr14"] / d["atr60"].replace(0, np.nan)

    # volume
    d["vol20"] = g["vol"].transform(lambda s: s.rolling(20, min_periods=20).mean())
    d["vol60"] = g["vol"].transform(lambda s: s.rolling(60, min_periods=60).mean())
    d["f_vol20_vol60"] = d["vol20"] / d["vol60"].replace(0, np.nan)
    d["f_breakout_vol_ratio20"] = d["vol"] / d["vol20"].replace(0, np.nan)
    d["f_vol_stability20"] = g["vol"].transform(lambda s: s.rolling(20, min_periods=20).std()) / d["vol20"].replace(0, np.nan)
    d["tmp_below60"] = (d["vol"] < d["vol60"]).astype(float)
    d["f_low_vol_days10"] = g["tmp_below60"].transform(lambda s: s.rolling(10, min_periods=5).sum())
    d["tmp_up_vol"] = np.where(d["close"] >= d["open"], d["vol"], 0.0)
    d["tmp_down_vol"] = np.where(d["close"] < d["open"], d["vol"], 0.0)
    d["f_up_down_vol_ratio20"] = (
        g["tmp_up_vol"].transform(lambda s: s.rolling(20, min_periods=10).sum())
        / g["tmp_down_vol"].transform(lambda s: s.rolling(20, min_periods=10).sum()).replace(0, np.nan)
    )

    # k-line research features
    d["f_k_pct_chg"] = d["close"] / prev_close - 1
    body = (d["close"] - d["open"]).abs()
    d["f_k_body_to_atr"] = body / d["atr14"].replace(0, np.nan)
    rng = (d["high"] - d["low"]).replace(0, np.nan)
    upper = d["high"] - d[["open", "close"]].max(axis=1)
    lower = d[["open", "close"]].min(axis=1) - d["low"]
    d["f_k_upper_shadow_ratio"] = upper / rng
    d["f_k_lower_shadow_ratio"] = lower / rng
    d["f_k_close_pos"] = (d["close"] - d["low"]) / rng
    d["f_k_break_pivot20_pct"] = d["close"] / hh20_prev - 1

    # industry features (use same-day industry cross section)
    valid_main = d[d["ts_code"].map(_main_board)].copy()
    ind_day = (
        valid_main.groupby(["trade_date", "industry"], dropna=False)
        .agg(
            ind_ret_today=("f_k_pct_chg", "mean"),
            ind_breadth=("f_k_pct_chg", lambda s: np.nanmean(s > 0)),
            ind_peer_strong_count=("f_k_pct_chg", lambda s: np.nansum(s > 0.02)),
        )
        .reset_index()
    )
    ind_day = ind_day.sort_values(["industry", "trade_date"])
    ind_day["f_ind_strength_today"] = ind_day["ind_ret_today"]
    ind_day["f_ind_strength_3d"] = ind_day.groupby("industry")["ind_ret_today"].transform(
        lambda s: s.rolling(3, min_periods=3).mean()
    )
    ind_day["f_ind_strength_5d"] = ind_day.groupby("industry")["ind_ret_today"].transform(
        lambda s: s.rolling(5, min_periods=5).mean()
    )
    ind_day["f_ind_breadth"] = ind_day["ind_breadth"]
    ind_day["f_ind_peer_strong_count"] = ind_day["ind_peer_strong_count"]
    d = d.merge(
        ind_day[
            [
                "trade_date",
                "industry",
                "f_ind_strength_today",
                "f_ind_strength_3d",
                "f_ind_strength_5d",
                "f_ind_breadth",
                "f_ind_peer_strong_count",
            ]
        ],
        on=["trade_date", "industry"],
        how="left",
    )
    d["f_ind_rank_pctchg"] = d.groupby(["trade_date", "industry"])["f_k_pct_chg"].rank(method="average", pct=True)
    d["f_ind_rank_amount"] = d.groupby(["trade_date", "industry"])["amount"].rank(method="average", pct=True)

    # benchmark relative
    bench = d[d["ts_code"] == "000001.SH"][["trade_date", "f_strength_ret20", "f_strength_ret60"]].rename(
        columns={"f_strength_ret20": "b_ret20", "f_strength_ret60": "b_ret60"}
    )
    d = d.merge(bench, on="trade_date", how="left")
    d["f_strength_vs_index20"] = d["f_strength_ret20"] - d["b_ret20"]
    d["f_strength_vs_index60"] = d["f_strength_ret60"] - d["b_ret60"]

    # chip features
    d["f_chip_concentration"] = (d["cost_95pct"] - d["cost_5pct"]) / (d["cost_95pct"] + d["cost_5pct"]).replace(0, np.nan)
    g_chip = d.groupby("ts_code", group_keys=False)
    d["f_chip_stability_std10"] = g_chip["f_chip_concentration"].transform(lambda s: s.rolling(10, min_periods=5).std())
    low120 = g["low"].transform(lambda s: s.rolling(120, min_periods=60).min())
    high120 = g["high"].transform(lambda s: s.rolling(120, min_periods=60).max())
    d["f_chip_low_position120"] = (d["cost_50pct"] - low120) / (high120 - low120).replace(0, np.nan)
    wr = pd.to_numeric(d["winner_rate"], errors="coerce")
    d["f_chip_winner_rate"] = np.where(wr > 1.0, wr / 100.0, wr)
    d["f_chip_peak_count_sig"] = d["chip_peak_count_sig"]
    d["f_chip_secondary_peak_ratio"] = d["chip_secondary_peak_ratio"]
    d["f_chip_peak_dominance"] = d["chip_peak_dominance"]
    d["f_chip_single_peak_score"] = d["single_peak_dense_score"]

    drop_tmp = [c for c in ["tmp_in_band", "tmp_tr", "tmp_up_vol", "tmp_down_vol", "tmp_below60"] if c in d.columns]
    d = d.drop(columns=drop_tmp)
    return d


def _boundary_audit(snapshot: pd.DataFrame) -> pd.DataFrame:
    rows: List[Dict] = []
    feature_cols = [c for c in snapshot.columns if c.startswith("f_")]
    meta_cols = ["ts_code", "trade_date", "name", "industry", "candidate_event_id", "label_true_breakout"]
    label_cols = [
        "label_reason",
        "has_full_forward_window",
        "forward_window_days",
        "max_up_ret_5",
        "max_dd_ret_3",
        "max_dd_ret_5",
        "close_ret_3",
        "close_ret_5",
        "key_break_3",
    ]
    for c in snapshot.columns:
        if c in feature_cols:
            cls = "feature"
            allow = True
            note = "T-day feature"
            if c in SPECIAL_K_FEATURES:
                note = "research feature only; not entry rule"
        elif c in label_cols or c.endswith("_fwd_1") or "_fwd_" in c:
            cls = "label_only"
            allow = False
            note = "future/label field; forbidden in features"
        elif c in meta_cols:
            cls = "metadata"
            allow = True
            note = "metadata/index"
        else:
            cls = "drop_or_aux"
            allow = False
            note = "not used in main feature diff"
        rows.append({"field": c, "class": cls, "allowed_in_feature_model": allow, "note": note})
    return pd.DataFrame(rows)


def _ac_diff(snapshot: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    ac = snapshot[snapshot["label_true_breakout"].isin(["A", "C"])].copy()
    a = ac[ac["label_true_breakout"] == "A"]
    c = ac[ac["label_true_breakout"] == "C"]
    feats = [x for x in ac.columns if x.startswith("f_")]
    rows = []
    for f in feats:
        av = pd.to_numeric(a[f], errors="coerce")
        cv = pd.to_numeric(c[f], errors="coerce")
        am = av.median(skipna=True)
        cm = cv.median(skipna=True)
        gap = am - cm
        d = _cliffs_delta(av.to_numpy(), cv.to_numpy())
        a_miss = float(av.isna().mean())
        c_miss = float(cv.isna().mean())
        direction = "A_higher" if pd.notna(gap) and gap > 0 else ("A_lower" if pd.notna(gap) and gap < 0 else "flat")
        keep = (pd.notna(d) and abs(d) >= 0.08 and max(a_miss, c_miss) <= 0.35)
        rows.append(
            {
                "feature": f,
                "a_n": int(av.notna().sum()),
                "c_n": int(cv.notna().sum()),
                "a_missing_rate": a_miss,
                "c_missing_rate": c_miss,
                "a_median": float(am) if pd.notna(am) else np.nan,
                "c_median": float(cm) if pd.notna(cm) else np.nan,
                "median_gap_a_minus_c": float(gap) if pd.notna(gap) else np.nan,
                "direction": direction,
                "cliffs_delta": float(d) if pd.notna(d) else np.nan,
                "abs_effect": float(abs(d)) if pd.notna(d) else np.nan,
                "keep_candidate": bool(keep),
            }
        )
    diff = pd.DataFrame(rows).sort_values("abs_effect", ascending=False)

    # family summary data
    def fam(feat: str) -> str:
        if feat.startswith("f_strength_") or feat.startswith("f_trend_"):
            return "trend_strength"
        if feat.startswith("f_ind_"):
            return "industry_leadership"
        if feat.startswith("f_vol") or feat in {"f_breakout_vol_ratio20", "f_up_down_vol_ratio20"}:
            return "volume_rhythm"
        if feat.startswith("f_platform_") or feat.startswith("f_atr_"):
            return "platform_structure"
        if feat.startswith("f_chip_"):
            return "chip_quality"
        if feat.startswith("f_k_"):
            return "kline_research"
        return "other"

    diff["family"] = diff["feature"].map(fam)
    family = (
        diff.groupby("family")
        .agg(
            feature_n=("feature", "size"),
            mean_abs_effect=("abs_effect", "mean"),
            median_abs_effect=("abs_effect", "median"),
            keep_n=("keep_candidate", "sum"),
            high_missing_n=("a_missing_rate", lambda s: np.nan),
        )
        .reset_index()
        .sort_values("mean_abs_effect", ascending=False)
    )

    # redundancy among stronger features
    strong_feats = diff[diff["abs_effect"] >= 0.12]["feature"].head(30).tolist()
    corr_rows = []
    if strong_feats:
        mat = ac[strong_feats].apply(pd.to_numeric, errors="coerce")
        corr = mat.corr(method="spearman", min_periods=200)
        for i, fi in enumerate(strong_feats):
            for fj in strong_feats[i + 1 :]:
                v = corr.loc[fi, fj]
                if pd.notna(v) and abs(v) >= 0.85:
                    corr_rows.append({"feature_a": fi, "feature_b": fj, "spearman_corr": float(v)})
    corr_df = pd.DataFrame(corr_rows).sort_values("spearman_corr", key=lambda s: s.abs(), ascending=False) if corr_rows else pd.DataFrame(columns=["feature_a", "feature_b", "spearman_corr"])
    return diff, family, corr_df


def _grey_obs(snapshot: pd.DataFrame, top_features: List[str]) -> str:
    a = snapshot[snapshot["label_true_breakout"] == "A"]
    c = snapshot[snapshot["label_true_breakout"] == "C"]
    g = snapshot[snapshot["label_true_breakout"] == "G"]
    lines = ["# true_breakout_greyzone_observation", "", "G observed against A/C on top factors:"]
    for f in top_features:
        av = pd.to_numeric(a[f], errors="coerce").median(skipna=True)
        cv = pd.to_numeric(c[f], errors="coerce").median(skipna=True)
        gv = pd.to_numeric(g[f], errors="coerce").median(skipna=True)
        if pd.isna(av) or pd.isna(cv) or pd.isna(gv):
            continue
        da, dc = abs(gv - av), abs(gv - cv)
        closer = "A" if da < dc else "C"
        lines.append(f"- {f}: G median={gv:.4f}, closer_to={closer}")
    lines += [
        "",
        "Conclusion:",
        "- G is mixed and not consistently identical to A or C.",
        "- keep G as greyzone observation group; do not merge into A/C main contrast.",
    ]
    return "\n".join(lines)


def _factor_candidates(diff: pd.DataFrame) -> str:
    # simple tiering rules
    miss_max = diff[["a_missing_rate", "c_missing_rate"]].max(axis=1)
    hard_mask = (diff["abs_effect"] >= 0.08) & (miss_max <= 0.15)
    score_mask = (diff["abs_effect"] >= 0.04) & (diff["abs_effect"] < 0.08) & (miss_max <= 0.35)

    hard = diff[hard_mask]
    score = diff[
        score_mask
    ]
    downgraded = diff[
        ~(hard_mask | score_mask)
    ]

    def fmt(df: pd.DataFrame, n: int = 15) -> List[str]:
        out = []
        for _, r in df.head(n).iterrows():
            out.append(f"- {r['feature']} | effect={r['abs_effect']:.3f} | dir={r['direction']} | miss_max={max(r['a_missing_rate'], r['c_missing_rate']):.2%}")
        return out

    lines = [
        "# true_breakout_factor_candidates",
        "",
        "## Hard-filter candidates",
        *fmt(hard),
        "",
        "## Continuous-scoring candidates",
        *fmt(score),
        "",
        "## Downgraded observation items",
        *fmt(downgraded),
        "",
        "Note: K-line features remain research factors at this stage, not entry rules.",
    ]
    return "\n".join(lines)


def main() -> None:
    labeled, daily = _load_base()
    daily_feat = _compute_features(daily)

    # join labeled events with T-day features only
    feature_cols = [c for c in daily_feat.columns if c.startswith("f_")]
    snapshot = labeled.merge(
        daily_feat[["ts_code", "trade_date", "name", "industry"] + feature_cols],
        on=["ts_code", "trade_date"],
        how="left",
        suffixes=("", "_feat"),
    )
    # normalize name/industry from label side if present
    for c in ["name", "industry"]:
        if f"{c}_feat" in snapshot.columns:
            snapshot[c] = snapshot[c].fillna(snapshot[f"{c}_feat"])
            snapshot = snapshot.drop(columns=[f"{c}_feat"])

    snapshot.to_parquet(OUT_SNAPSHOT, index=False)

    # boundary audit
    audit = _boundary_audit(snapshot)
    audit.to_csv(OUT_BOUNDARY, index=False, encoding="utf-8-sig")

    # main A/C diff
    a_n = int((snapshot["label_true_breakout"] == "A").sum())
    c_n = int((snapshot["label_true_breakout"] == "C").sum())
    g_n = int((snapshot["label_true_breakout"] == "G").sum())
    n_n = int((snapshot["label_true_breakout"] == "N").sum())
    diff, family, corr = _ac_diff(snapshot)
    diff.to_csv(OUT_DIFF, index=False, encoding="utf-8-sig")

    # rankings
    rank = diff.sort_values(["abs_effect", "keep_candidate"], ascending=[False, False]).copy()
    rank["rank"] = np.arange(1, len(rank) + 1)
    rank.to_csv(OUT_RANK, index=False, encoding="utf-8-sig")

    # family summary
    strongest_family = family.iloc[0]["family"] if len(family) else None
    weakest_family = family.iloc[-1]["family"] if len(family) else None
    top5 = rank.head(5)["feature"].tolist()
    weak5 = rank.tail(5)["feature"].tolist()
    fam_lines = [
        "# true_breakout_feature_family_summary",
        "",
        f"- A samples: {a_n}",
        f"- C samples: {c_n}",
        f"- G samples (observation): {g_n}",
        f"- N samples (excluded): {n_n}",
        "",
        "## family strength",
        family.to_string(index=False) if len(family) else "no family stats",
        "",
        f"- strongest family: {strongest_family}",
        f"- weakest family: {weakest_family}",
        "",
        "## strongest features top5",
        *[f"- {x}" for x in top5],
        "",
        "## weakest features",
        *[f"- {x}" for x in weak5],
        "",
        "## redundancy (|spearman| >= 0.85 among stronger factors)",
        corr.head(20).to_string(index=False) if len(corr) else "no strong redundancy pairs",
    ]
    OUT_FAMILY.write_text("\n".join(fam_lines), encoding="utf-8")

    # grey observation
    OUT_GREY.write_text(_grey_obs(snapshot, top5), encoding="utf-8")

    # factor candidates
    OUT_FACTORS.write_text(_factor_candidates(diff), encoding="utf-8")

    print("Generated:")
    print(" -", OUT_SNAPSHOT)
    print(" -", OUT_BOUNDARY)
    print(" -", OUT_DIFF)
    print(" -", OUT_RANK)
    print(" -", OUT_FAMILY)
    print(" -", OUT_GREY)
    print(" -", OUT_FACTORS)


if __name__ == "__main__":
    main()
