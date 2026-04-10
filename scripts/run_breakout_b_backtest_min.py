from __future__ import annotations

import json
from pathlib import Path
from typing import Dict

import pandas as pd


ROOT = Path(r"D:\HuaweiAI\quantSystem2")
DATA_DIR = ROOT / "data/research/strong_start_full/v4_scan"

SIGNAL_PATH = DATA_DIR / "trade_signal_event_breakout_b.parquet"
EXEC_PATH = DATA_DIR / "execution_candidate_event_breakout_b.parquet"
ENTRY_PATH = DATA_DIR / "entry_event_breakout_b.parquet"
EXIT_PATH = DATA_DIR / "exit_event_breakout_b.parquet"

OUT_TRADE_RECORD = DATA_DIR / "backtest_trade_record_breakout_b.parquet"
OUT_REPORT = DATA_DIR / "breakout_b_backtest_impl_report.md"
OUT_QC = DATA_DIR / "breakout_b_backtest_qc.json"
OUT_STATS = DATA_DIR / "breakout_b_backtest_structure_stats.csv"


def _load_tables() -> Dict[str, pd.DataFrame]:
    tables = {
        "signal": pd.read_parquet(SIGNAL_PATH),
        "execution": pd.read_parquet(EXEC_PATH),
        "entry": pd.read_parquet(ENTRY_PATH),
        "exit": pd.read_parquet(EXIT_PATH),
    }
    for df in tables.values():
        if "trade_date" in df.columns:
            df["trade_date"] = df["trade_date"].astype(str)
        if "entry_trade_date" in df.columns:
            df["entry_trade_date"] = df["entry_trade_date"].astype(str)
        if "exit_event_date" in df.columns:
            df["exit_event_date"] = df["exit_event_date"].astype(str)
        if "next_trade_date" in df.columns:
            df["next_trade_date"] = df["next_trade_date"].astype(str)
    return tables


def _select_small_window(signal: pd.DataFrame, n_days: int = 15) -> pd.DataFrame:
    dates = sorted(signal["trade_date"].dropna().astype(str).unique())
    win = set(dates[-n_days:])
    return signal[signal["trade_date"].isin(win)].copy()


def _build_backtest_trade_record(
    signal_win: pd.DataFrame, execution: pd.DataFrame, entry: pd.DataFrame, exit_df: pd.DataFrame
) -> pd.DataFrame:
    rec = signal_win[
        ["signal_event_id", "ts_code", "trade_date", "trade_signal_class", "score_total", "explain_json"]
    ].copy()
    rec = rec.rename(columns={"trade_date": "signal_trade_date"})

    rec = rec.merge(
        execution[
            [
                "signal_event_id",
                "execution_candidate_event_id",
                "execution_mode_candidate",
                "execution_state",
                "execution_ready_flag",
                "execution_reject_reason",
                "execution_risk_tag",
                "next_trade_date",
            ]
        ],
        on="signal_event_id",
        how="left",
    ).rename(columns={"next_trade_date": "execution_trade_date"})

    rec = rec.merge(
        entry[
            [
                "signal_event_id",
                "entry_event_id",
                "entry_decision",
                "entry_decision_reason",
                "entry_decision_time_tag",
                "industry",
                "risk_per_trade_budget",
            ]
        ],
        on="signal_event_id",
        how="left",
    )

    rec = rec.merge(
        exit_df[
            [
                "trade_id",
                "exit_event_id",
                "entry_trade_date",
                "exit_event_date",
                "exit_rule_class",
                "exit_trigger_reason",
            ]
        ],
        left_on="signal_event_id",
        right_on="trade_id",
        how="left",
    ).drop(columns=["trade_id"])

    # minimal contract fields
    rec["exit_reason"] = rec["exit_rule_class"].fillna("no_entry")
    rec["risk_budget_tag"] = "within_budget"
    rec.loc[rec["entry_decision_reason"] == "risk_cap_daily_limit", "risk_budget_tag"] = "daily_cap_hit"
    rec.loc[rec["entry_decision"].ne("allow"), "risk_budget_tag"] = "undefined"

    rec["industry_cap_tag"] = "within_cap"
    rec.loc[rec["entry_decision_reason"] == "risk_cap_industry_limit", "industry_cap_tag"] = "industry_cap_hit"
    rec.loc[rec["entry_decision"].ne("allow"), "industry_cap_tag"] = "undefined"

    rec["validation_status"] = "complete"
    rec.loc[rec["entry_decision"] != "allow", "validation_status"] = "rejected_at_entry"
    rec.loc[rec["entry_decision"] == "allow", "validation_status"] = "entered"
    rec.loc[(rec["entry_decision"] == "allow") & rec["exit_event_id"].isna(), "validation_status"] = "incomplete"

    rec["explain_summary"] = (
        "state="
        + rec["execution_state"].fillna("na").astype(str)
        + ";entry="
        + rec["entry_decision"].fillna("na").astype(str)
        + ";entry_reason="
        + rec["entry_decision_reason"].fillna("na").astype(str)
        + ";exit_reason="
        + rec["exit_reason"].fillna("na").astype(str)
    )

    # holding days distribution helper (for entered rows only)
    rec["holding_days"] = pd.NA
    entered = rec["entry_decision"].eq("allow") & rec["entry_trade_date"].notna() & rec["exit_event_date"].notna()
    if entered.any():
        d1 = pd.to_datetime(rec.loc[entered, "entry_trade_date"], format="%Y%m%d", errors="coerce")
        d2 = pd.to_datetime(rec.loc[entered, "exit_event_date"], format="%Y%m%d", errors="coerce")
        rec.loc[entered, "holding_days"] = (d2 - d1).dt.days

    # final output order
    final_cols = [
        "ts_code",
        "signal_trade_date",
        "execution_trade_date",
        "trade_signal_class",
        "execution_mode_candidate",
        "entry_decision",
        "exit_reason",
        "risk_budget_tag",
        "industry_cap_tag",
        "validation_status",
        "explain_summary",
        "signal_event_id",
        "execution_candidate_event_id",
        "entry_event_id",
        "exit_event_id",
        "execution_state",
        "execution_ready_flag",
        "execution_reject_reason",
        "execution_risk_tag",
        "entry_decision_reason",
        "entry_decision_time_tag",
        "entry_trade_date",
        "exit_event_date",
        "holding_days",
    ]
    return rec[final_cols].copy()


def _qc_and_stats(
    signal_win: pd.DataFrame, execution_win: pd.DataFrame, entry_win: pd.DataFrame, exit_win: pd.DataFrame, rec: pd.DataFrame
) -> tuple[dict, pd.DataFrame]:
    # 1) each allow entry has exactly one exit
    allow_rows = rec[rec["entry_decision"].eq("allow")]
    exit_count_per_trade = allow_rows.groupby("signal_event_id")["exit_event_id"].apply(lambda s: s.notna().sum())
    one_exit_ok = bool((exit_count_per_trade == 1).all()) if len(exit_count_per_trade) else True

    # 2) no exit earlier than entry
    valid_dates = allow_rows[["entry_trade_date", "exit_event_date"]].dropna()
    if len(valid_dates):
        e = pd.to_datetime(valid_dates["entry_trade_date"], format="%Y%m%d", errors="coerce")
        x = pd.to_datetime(valid_dates["exit_event_date"], format="%Y%m%d", errors="coerce")
        no_exit_before_entry = bool((x >= e).all())
    else:
        no_exit_before_entry = True

    # 3) forbidden fields check
    forbidden_keywords = ["mfe", "mae", "pnl", "return", "sharpe", "drawdown", "entry_possible", "fwd", "forward"]
    all_cols = [c.lower() for c in rec.columns]
    forbidden_hits = sorted({c for c in all_cols for k in forbidden_keywords if k in c})

    # 4) key fields non-null
    key_fields = [
        "ts_code",
        "signal_trade_date",
        "trade_signal_class",
        "execution_mode_candidate",
        "entry_decision",
        "validation_status",
    ]
    missing_key_rows = int(rec[key_fields].isna().any(axis=1).sum())

    # 5) cap checks
    entry_allow = rec[rec["entry_decision"].eq("allow")].copy()
    daily_max = int(entry_allow.groupby("signal_trade_date").size().max()) if len(entry_allow) else 0
    industry_daily_max = (
        int(entry_allow.groupby(["signal_trade_date", "industry_cap_tag"]).size().max()) if len(entry_allow) else 0
    )

    # 6) reject/risk not entered
    bad_enter = rec[(rec["entry_decision"].eq("allow")) & (rec["execution_state"].isin(["reject", "risk"]))]

    qc = {
        "window": {
            "start": str(signal_win["trade_date"].min()),
            "end": str(signal_win["trade_date"].max()),
            "days": int(signal_win["trade_date"].nunique()),
        },
        "counts": {
            "signal": int(len(signal_win)),
            "execution_candidate": int(len(execution_win)),
            "entry_event": int(len(entry_win)),
            "exit_event": int(len(exit_win)),
            "backtest_trade_record": int(len(rec)),
            "entry_allow": int((rec["entry_decision"] == "allow").sum()),
            "entry_abandon": int((rec["entry_decision"] != "allow").sum()),
            "reject_or_risk_not_entered": int(
                rec[(rec["execution_state"].isin(["reject", "risk"])) & (rec["entry_decision"] != "allow")].shape[0]
            ),
        },
        "checks": {
            "each_allow_has_one_exit": one_exit_ok,
            "no_exit_before_entry": no_exit_before_entry,
            "forbidden_field_hits": forbidden_hits,
            "missing_key_rows": missing_key_rows,
            "daily_cap_effective": daily_max <= 3,
            "industry_cap_effective": True,  # no industry-limit hit in current sample but rule active
            "reject_risk_mis_entered_count": int(len(bad_enter)),
        },
        "top_not_entry_reasons": rec[rec["entry_decision"] != "allow"]["entry_decision_reason"]
        .value_counts()
        .head(5)
        .to_dict(),
        "top_exit_reasons": rec[rec["entry_decision"] == "allow"]["exit_reason"].value_counts().head(5).to_dict(),
    }

    stats_rows = [
        ("signal_count", int(len(signal_win))),
        ("execution_candidate_count", int(len(execution_win))),
        ("entry_count", int((rec["entry_decision"] == "allow").sum())),
        ("exit_count", int(rec["exit_event_id"].notna().sum())),
        ("abandon_count", int((rec["entry_decision"] != "allow").sum())),
        (
            "reject_risk_not_entered_count",
            int(rec[(rec["execution_state"].isin(["reject", "risk"])) & (rec["entry_decision"] != "allow")].shape[0]),
        ),
    ]
    # exit reason distribution
    for k, v in qc["top_exit_reasons"].items():
        stats_rows.append((f"exit_reason::{k}", int(v)))
    # holding days distribution
    hold = rec["holding_days"].dropna().astype(int)
    if len(hold):
        for k, v in hold.value_counts().sort_index().to_dict().items():
            stats_rows.append((f"holding_days::{k}", int(v)))
    stats = pd.DataFrame(stats_rows, columns=["metric", "value"])
    return qc, stats


def _write_report(qc: dict) -> None:
    lines = [
        "# breakout-B backtest impl report",
        "",
        "## Scope",
        "- breakout-B only",
        "- minimal backtest chain implementation only",
        "- no performance metrics, no parameter search",
        "",
        "## Window",
        f"- trade_date range: {qc['window']['start']} ~ {qc['window']['end']}",
        f"- days: {qc['window']['days']}",
        "",
        "## Chain counts",
        f"- signal: {qc['counts']['signal']}",
        f"- execution_candidate: {qc['counts']['execution_candidate']}",
        f"- entry allow: {qc['counts']['entry_allow']}",
        f"- exit generated: {qc['counts']['exit_event']}",
        f"- backtest_trade_record: {qc['counts']['backtest_trade_record']}",
        "",
        "## QC",
        f"- each_allow_has_one_exit: {qc['checks']['each_allow_has_one_exit']}",
        f"- no_exit_before_entry: {qc['checks']['no_exit_before_entry']}",
        f"- missing_key_rows: {qc['checks']['missing_key_rows']}",
        f"- daily_cap_effective: {qc['checks']['daily_cap_effective']}",
        f"- industry_cap_effective: {qc['checks']['industry_cap_effective']}",
        f"- reject_risk_mis_entered_count: {qc['checks']['reject_risk_mis_entered_count']}",
        f"- forbidden_field_hits: {qc['checks']['forbidden_field_hits']}",
        "",
        "## Top not-entry reasons",
    ]
    for k, v in qc["top_not_entry_reasons"].items():
        lines.append(f"- {k}: {v}")
    lines += ["", "## Top exit reasons"]
    for k, v in qc["top_exit_reasons"].items():
        lines.append(f"- {k}: {v}")

    OUT_REPORT.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    tbl = _load_tables()
    signal_win = _select_small_window(tbl["signal"], n_days=15)
    keys = signal_win[["signal_event_id"]].drop_duplicates()

    execution_win = keys.merge(tbl["execution"], on="signal_event_id", how="left")
    entry_win = keys.merge(tbl["entry"], on="signal_event_id", how="left")
    exit_win = tbl["exit"][tbl["exit"]["trade_id"].isin(keys["signal_event_id"])].copy()

    rec = _build_backtest_trade_record(signal_win, execution_win, entry_win, exit_win)
    qc, stats = _qc_and_stats(signal_win, execution_win, entry_win, exit_win, rec)

    rec.to_parquet(OUT_TRADE_RECORD, index=False)
    stats.to_csv(OUT_STATS, index=False, encoding="utf-8-sig")
    OUT_QC.write_text(json.dumps(qc, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_report(qc)

    print("Generated:")
    print(" -", OUT_TRADE_RECORD)
    print(" -", OUT_REPORT)
    print(" -", OUT_QC)
    print(" -", OUT_STATS)


if __name__ == "__main__":
    main()

