from __future__ import annotations

from pathlib import Path
import json
import numpy as np
import pandas as pd


ROOT = Path(r"D:\HuaweiAI\quantSystem2")
BASE = ROOT / "data/research/strong_start_full/v4_scan"
IN_SELECTED = BASE / "true_breakout_selected_quality_layers.csv"
SNAPSHOT = BASE / "true_breakout_feature_snapshot_1y.parquet"

OUT_DIFF = BASE / "true_breakout_Ahigh_target_diff.csv"
OUT_FACTORS = BASE / "true_breakout_Ahigh_factor_candidates.md"
OUT_C_FIREWALL = BASE / "true_breakout_selectedC_firewall_notes.md"
OUT_G_DEMOTE = BASE / "true_breakout_selectedG_demotion_notes.md"
OUT_DRAFT = BASE / "true_breakout_selector_ahigh_refine_draft.md"


def _safe_median(s: pd.Series) -> float:
    x = pd.to_numeric(s, errors="coerce")
    return float(x.median()) if x.notna().any() else np.nan


def _safe_mean(s: pd.Series) -> float:
    x = pd.to_numeric(s, errors="coerce")
    return float(x.mean()) if x.notna().any() else np.nan


def _cliffs_delta(a: pd.Series, b: pd.Series) -> float:
    xa = pd.to_numeric(a, errors="coerce").dropna().values
    xb = pd.to_numeric(b, errors="coerce").dropna().values
    if len(xa) == 0 or len(xb) == 0:
        return np.nan
    # lightweight exact computation for current sample size
    gt = 0
    lt = 0
    for v in xa:
        gt += np.sum(v > xb)
        lt += np.sum(v < xb)
    return float((gt - lt) / (len(xa) * len(xb)))


def main() -> None:
    df = pd.read_csv(IN_SELECTED)
    # attach raw factor columns needed for Ahigh-vs-C/G audit
    snap = pd.read_parquet(
        SNAPSHOT,
        columns=[
            "ts_code",
            "trade_date",
            "f_strength_rs20_xsec_q",
            "f_platform_compress_ratio",
            "f_chip_winner_rate",
            "f_ind_peer_strong_count",
        ],
    ).copy()
    snap["trade_date"] = snap["trade_date"].astype(str)
    df["trade_date"] = df["trade_date"].astype(str)
    df = df.merge(snap, on=["ts_code", "trade_date"], how="left")

    ah = df[(df["label_true_breakout"] == "A") & (df["a_quality_layer"] == "A_high")].copy()
    am = df[(df["label_true_breakout"] == "A") & (df["a_quality_layer"] == "A_mid")].copy()
    al = df[(df["label_true_breakout"] == "A") & (df["a_quality_layer"] == "A_low")].copy()
    sc = df[df["label_true_breakout"] == "C"].copy()
    sg = df[df["label_true_breakout"] == "G"].copy()

    factors = [
        "score_trend_axis_single",
        "score_platform_axis_single",
        "score_chip_axis_single",
        "score_industry_axis_single",
        "f_strength_rs20_xsec_q",
        "f_platform_compress_ratio",
        "f_chip_winner_rate",
        "f_ind_peer_strong_count",
        "score_total",
    ]

    rows = []
    for f in factors:
        rows.append(
            {
                "factor": f,
                "A_high_n": int(len(ah)),
                "A_high_median": _safe_median(ah[f]),
                "A_high_mean": _safe_mean(ah[f]),
                "selected_C_median": _safe_median(sc[f]),
                "selected_G_median": _safe_median(sg[f]),
                "A_low_median": _safe_median(al[f]),
                "A_mid_median": _safe_median(am[f]),
                "A_high_minus_C": _safe_median(ah[f]) - _safe_median(sc[f]),
                "A_high_minus_G": _safe_median(ah[f]) - _safe_median(sg[f]),
                "A_high_minus_A_low": _safe_median(ah[f]) - _safe_median(al[f]),
                "cliff_Ah_vs_C": _cliffs_delta(ah[f], sc[f]),
                "cliff_Ah_vs_G": _cliffs_delta(ah[f], sg[f]),
                "cliff_Ah_vs_Alow": _cliffs_delta(ah[f], al[f]),
            }
        )
    diff = pd.DataFrame(rows)
    diff["abs_sep_score"] = (
        diff["A_high_minus_C"].abs().fillna(0)
        + diff["A_high_minus_G"].abs().fillna(0)
        + diff["A_high_minus_A_low"].abs().fillna(0)
    )
    diff = diff.sort_values("abs_sep_score", ascending=False)
    diff.to_csv(OUT_DIFF, index=False, encoding="utf-8-sig")

    # C firewall diagnostics
    c_reason = (
        sc.groupby("selected_c_reason")
        .apply(
            lambda g: pd.Series(
                {
                    "sample_n": int(len(g)),
                    "share_in_selected_C": float(len(g) / len(sc)) if len(sc) else np.nan,
                    "mean_ret_t2": _safe_mean(g["ret_t2"]),
                    "win_t2": float((pd.to_numeric(g["ret_t2"], errors="coerce") > 0).mean()),
                    "median_trend_axis": _safe_median(g["score_trend_axis_single"]),
                    "median_industry_axis": _safe_median(g["score_industry_axis_single"]),
                    "median_platform_axis": _safe_median(g["score_platform_axis_single"]),
                    "median_chip_axis": _safe_median(g["score_chip_axis_single"]),
                }
            )
        )
        .reset_index()
        .sort_values("sample_n", ascending=False)
    )

    # G demotion diagnostics
    g_reason = (
        sg.groupby("selected_g_reason")
        .apply(
            lambda g: pd.Series(
                {
                    "sample_n": int(len(g)),
                    "share_in_selected_G": float(len(g) / len(sg)) if len(sg) else np.nan,
                    "mean_ret_t2": _safe_mean(g["ret_t2"]),
                    "win_t2": float((pd.to_numeric(g["ret_t2"], errors="coerce") > 0).mean()),
                }
            )
        )
        .reset_index()
        .sort_values("sample_n", ascending=False)
    )

    # factor layer suggestion (A_high-targeted)
    hard_filter = []
    score_layer = []
    demote_layer = []
    for _, r in diff.iterrows():
        f = r["factor"]
        sep_c = abs(r["A_high_minus_C"])
        sep_al = abs(r["A_high_minus_A_low"])
        cliff_c = abs(r["cliff_Ah_vs_C"]) if pd.notna(r["cliff_Ah_vs_C"]) else 0
        cliff_al = abs(r["cliff_Ah_vs_Alow"]) if pd.notna(r["cliff_Ah_vs_Alow"]) else 0
        # lightweight rule-based layering
        if sep_c >= 0.05 and sep_al >= 0.03 and cliff_c >= 0.25:
            hard_filter.append(f)
        elif (sep_c >= 0.02 or sep_al >= 0.02) and (cliff_c >= 0.10 or cliff_al >= 0.10):
            score_layer.append(f)
        else:
            demote_layer.append(f)

    # force requested key-factor judgments (keep explicit and stable)
    # Promote clear separators observed in this window
    for f in ["f_ind_peer_strong_count", "f_platform_compress_ratio", "score_trend_axis_single"]:
        if f not in hard_filter and f not in score_layer:
            score_layer.append(f)
    # Demote noisy / reverse-direction items
    for f in ["score_industry_axis_single", "score_platform_axis_single", "f_chip_winner_rate"]:
        if f in hard_filter:
            hard_filter.remove(f)
        if f in score_layer:
            score_layer.remove(f)
        if f not in demote_layer:
            demote_layer.append(f)

    # dedupe keep order
    def _dedupe(xs):
        seen = set()
        out = []
        for x in xs:
            if x not in seen:
                out.append(x)
                seen.add(x)
        return out

    hard_filter = _dedupe(hard_filter)
    score_layer = _dedupe(score_layer)
    demote_layer = _dedupe(demote_layer)

    factor_lines = [
        "# true_breakout_Ahigh_factor_candidates",
        "",
        "## Target shift",
        "- old objective: raise A share",
        "- new objective: raise A_high share while suppressing selected_C and demoting selected_G",
        "",
        "## Layer 1: A_high hard-filter candidates",
    ]
    if hard_filter:
        factor_lines.extend([f"- {x}" for x in hard_filter])
    else:
        factor_lines.append("- (none strict enough; keep minimal hard-filter)")
    factor_lines.extend(["", "## Layer 2: A_high continuous-score candidates"])
    if score_layer:
        factor_lines.extend([f"- {x}" for x in score_layer])
    else:
        factor_lines.append("- (none)")
    factor_lines.extend(["", "## Layer 3: demoted / observe"])
    if demote_layer:
        factor_lines.extend([f"- {x}" for x in demote_layer])
    else:
        factor_lines.append("- (none)")
    factor_lines.extend(
        [
            "",
            "## Notes on required factors",
            "- `f_ind_peer_strong_count`: keep, but avoid heat-overweight (better as controlled score).",
            "- `f_platform_compress_ratio`: keep and strengthen as structure-quality anchor.",
            "- `score_trend_axis_single`: keep as core trend-quality expression.",
            "- `f_chip_winner_rate`: demote from core because it can lift C/G pseudo-strong cases in this window.",
            "- `score_industry_axis_single`: demote or cap; current direction over-admits heat C.",
            "- `score_platform_axis_single`: decompose/repair before re-promoting; current aggregate sign is unstable.",
        ]
    )
    OUT_FACTORS.write_text("\n".join(factor_lines), encoding="utf-8")

    OUT_C_FIREWALL.write_text(
        "\n".join(
            [
                "# true_breakout_selectedC_firewall_notes",
                "",
                "## Target C modes",
                "- mixed_pseudo_C",
                "- platform_false_break_C",
                "- industry_heat_C",
                "",
                "## Lightweight firewall directions (T-day only)",
                "1. Heat resonance cap: when trend-axis and industry-axis are both extreme, cap incremental score instead of linear stacking.",
                "2. Platform integrity guard: for weak-platform signatures (false-break profile), require minimum platform-compress quality before entering core pool.",
                "3. Mixed-C dampener: when trend/industry are high but chip/platform quality are non-confirming, route to observe pool instead of core candidate.",
                "",
                "## Why",
                "- selected_C is dominated by mixed + platform-false-break + industry-heat modes, and these modes have weak/negative T+2 behavior.",
                "",
                "## Current reason breakdown",
                c_reason.to_string(index=False) if len(c_reason) else "- no selected_C",
            ]
        ),
        encoding="utf-8",
    )

    OUT_G_DEMOTE.write_text(
        "\n".join(
            [
                "# true_breakout_selectedG_demotion_notes",
                "",
                "## Position",
                "- selected_G should default to observation pool, not core candidate pool.",
                "",
                "## Rationale",
                "- G contains uncertainty/mixed-path and buy-point-sensitive patterns; keeping them in core pool dilutes A_high purity.",
                "",
                "## Suggested handling",
                "1. Default demote all G to observe pool.",
                "2. Keep tracking subtypes: grey_uncertain / path_mixed_unclear / buypoint_sensitive_recovery / early_spike_fade.",
                "3. Only reconsider promotion after dedicated objective/label redesign; do not mix into current core selector target.",
                "",
                "## Current reason breakdown",
                g_reason.to_string(index=False) if len(g_reason) else "- no selected_G",
            ]
        ),
        encoding="utf-8",
    )

    # refine draft (direction only)
    OUT_DRAFT.write_text(
        "\n".join(
            [
                "# true_breakout_selector_ahigh_refine_draft",
                "",
                "## New selector objective",
                "- maximize A_high share (not generic A share)",
                "- suppress selected_C",
                "- demote selected_G by default",
                "",
                "## Keep",
                "- dual-path structure unchanged (this draft only refines objective and layer priority)",
                "- trend-quality + platform-compress as core discriminators",
                "",
                "## Demote / cap",
                "- industry aggregate heat score: keep as auxiliary with cap",
                "- winner-rate standalone boost: demote from core",
                "- unstable platform aggregate score: decompose/repair before core use",
                "",
                "## selected_C firewall (lightweight)",
                "- heat-resonance cap",
                "- platform integrity guard",
                "- mixed-C dampener to observe pool",
                "",
                "## selected_G handling",
                "- default observe pool, not core candidate",
                "",
                "## Next validation focus",
                "- evaluate A_high share uplift",
                "- track selected_C suppression",
                "- ensure selected_G stays mostly outside core output",
            ]
        ),
        encoding="utf-8",
    )

    quick = {
        "selected_A": int(len(df[df["label_true_breakout"] == "A"])),
        "selected_C": int(len(sc)),
        "selected_G": int(len(sg)),
        "A_high": int(len(ah)),
        "A_mid": int(len(am)),
        "A_low": int(len(al)),
        "top_C_reason": c_reason.iloc[0]["selected_c_reason"] if len(c_reason) else None,
        "top_G_reason": g_reason.iloc[0]["selected_g_reason"] if len(g_reason) else None,
    }
    print(json.dumps(quick, ensure_ascii=False))


if __name__ == "__main__":
    main()
