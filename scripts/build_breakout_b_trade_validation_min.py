from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple

import pandas as pd
import sqlite3


ROOT = Path(r"D:\HuaweiAI\quantSystem2")
SCAN_PATH = ROOT / "data/research/strong_start_full/v4_scan/v4_tune1_scan_multiday_neutral.parquet"
EXEC_PATH = ROOT / "data/research/strong_start_full/v4_scan/trade_execution_assumption_table_breakout_b_sample_refined.csv"
DB_PATH = ROOT / "data/database/quant_system.db"
OUT_DIR = ROOT / "data/research/strong_start_full/v4_scan"


@dataclass(frozen=True)
class RiskConfig:
    risk_per_trade_budget: float = 0.01
    max_new_entries_per_day: int = 3
    max_entries_per_industry_per_day: int = 2
    structural_stop_pct: float = 0.02
    max_hold_days: int = 3
    momentum_decay_consecutive_down_days: int = 2


def _load_scan() -> pd.DataFrame:
    df = pd.read_parquet(SCAN_PATH)
    df["trade_date"] = df["trade_date"].astype(str)
    return df


def _load_exec() -> pd.DataFrame:
    df = pd.read_csv(EXEC_PATH, dtype={"ts_code": str, "trade_date": str})
    # backward compatibility: old file may use execution_ready_flag as tri-state string
    if "execution_state" not in df.columns:
        if df["execution_ready_flag"].dtype == object:
            tri = df["execution_ready_flag"].astype(str).str.lower()
            df["execution_state"] = tri
            df["execution_ready_flag"] = tri.eq("ready")
        else:
            # fallback: bool flag only, infer unknown as risk
            df["execution_state"] = df["execution_ready_flag"].map({True: "ready", False: "risk"})
    else:
        # normalize bool ready flag from state
        df["execution_state"] = df["execution_state"].astype(str).str.lower()
        if df["execution_ready_flag"].dtype != bool:
            df["execution_ready_flag"] = df["execution_state"].eq("ready")
    return df


def _load_daily() -> pd.DataFrame:
    conn = sqlite3.connect(DB_PATH)
    try:
        daily = pd.read_sql_query(
            "select ts_code, trade_date, open, high, low, close, pct_chg from stock_daily",
            conn,
        )
    finally:
        conn.close()
    daily["trade_date"] = daily["trade_date"].astype(str)
    daily = daily.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)
    return daily


def _prepare_signal_event(scan: pd.DataFrame, exec_df: pd.DataFrame) -> pd.DataFrame:
    cols = [
        "trade_date",
        "ts_code",
        "name",
        "industry",
        "is_candidate_after_filters",
        "score_total",
        "trigger_status",
        "trigger_breakout_pass",
        "trigger_momentum_pass",
        "trigger_quality_pass",
        "trigger_groups_passed",
        "filter_reject_reasons",
        "score_details",
        "trigger_details",
        "explain_json",
    ]
    key = exec_df[["trade_date", "ts_code"]].drop_duplicates()
    signal = key.merge(scan[cols], on=["trade_date", "ts_code"], how="left")
    signal["signal_event_id"] = signal["ts_code"] + "_" + signal["trade_date"]
    signal["trade_signal_class"] = "breakout"
    signal["signal_confirm_time_tag"] = "T_close"
    signal["signal_stage_note"] = "breakout_b_trade_validation_min"
    return signal


def _prepare_execution_candidate(
    signal: pd.DataFrame, exec_df: pd.DataFrame, daily: pd.DataFrame
) -> pd.DataFrame:
    next_daily = daily[["ts_code", "trade_date"]].copy()
    next_daily["next_trade_date"] = next_daily.groupby("ts_code")["trade_date"].shift(-1)
    next_daily = next_daily.rename(columns={"trade_date": "signal_trade_date"})

    execution = signal.merge(
        exec_df[
            [
                "ts_code",
                "trade_date",
                "trade_signal_class",
                "execution_mode_candidate",
                "execution_state",
                "execution_ready_flag",
                "execution_risk_tag",
                "execution_reject_reason",
                "execution_assumption_note",
                "key_reason_1",
                "key_reason_2",
                "key_reason_3",
            ]
        ],
        on=["ts_code", "trade_date", "trade_signal_class"],
        how="left",
    )
    execution = execution.merge(
        next_daily,
        left_on=["ts_code", "trade_date"],
        right_on=["ts_code", "signal_trade_date"],
        how="left",
    ).drop(columns=["signal_trade_date"])
    execution["execution_candidate_event_id"] = execution["signal_event_id"] + "_EXEC"
    execution["execution_judgment_time_tag"] = "T1_intraday_window"
    return execution


def _build_entry_event(execution: pd.DataFrame, cfg: RiskConfig) -> pd.DataFrame:
    entry = execution.copy()
    entry["entry_event_id"] = entry["execution_candidate_event_id"] + "_ENTRY"
    entry["entry_decision"] = "abandon"
    entry["entry_decision_reason"] = "not_ready_state"
    entry["entry_decision_time_tag"] = "T1_intraday_window"
    entry["risk_per_trade_budget"] = cfg.risk_per_trade_budget

    ready_mask = entry["execution_state"].eq("ready") & entry["execution_ready_flag"].fillna(False)
    entry.loc[ready_mask, "entry_decision"] = "allow_candidate"
    entry.loc[ready_mask, "entry_decision_reason"] = "state_ready_pre_risk_control"

    # Risk control pruning on ready candidates only
    ready = entry[ready_mask].copy()
    ready["score_total"] = pd.to_numeric(ready["score_total"], errors="coerce").fillna(-1e9)
    ready["trigger_groups_passed"] = pd.to_numeric(ready["trigger_groups_passed"], errors="coerce").fillna(0)
    ready = ready.sort_values(
        ["trade_date", "score_total", "trigger_groups_passed", "ts_code"],
        ascending=[True, False, False, True],
    )

    selected_ids: List[str] = []
    dropped_reason: Dict[str, str] = {}
    for d, g in ready.groupby("trade_date", sort=True):
        day_count = 0
        ind_count: Dict[str, int] = {}
        for _, row in g.iterrows():
            sid = row["signal_event_id"]
            industry = row.get("industry")
            industry = "UNKNOWN" if pd.isna(industry) or str(industry).strip() == "" else str(industry)
            if day_count >= cfg.max_new_entries_per_day:
                dropped_reason[sid] = "risk_cap_daily_limit"
                continue
            if ind_count.get(industry, 0) >= cfg.max_entries_per_industry_per_day:
                dropped_reason[sid] = "risk_cap_industry_limit"
                continue
            selected_ids.append(sid)
            day_count += 1
            ind_count[industry] = ind_count.get(industry, 0) + 1

    allow_final = set(selected_ids)
    ready_all = entry["entry_decision"].eq("allow_candidate")
    entry.loc[ready_all, "entry_decision"] = "abandon"
    entry.loc[ready_all, "entry_decision_reason"] = "risk_control_not_selected"
    entry.loc[entry["signal_event_id"].isin(allow_final), "entry_decision"] = "allow"
    entry.loc[entry["signal_event_id"].isin(allow_final), "entry_decision_reason"] = "allow_after_risk_control"

    for sid, rsn in dropped_reason.items():
        mask = entry["signal_event_id"].eq(sid) & entry["entry_decision"].ne("allow")
        entry.loc[mask, "entry_decision_reason"] = rsn

    return entry


def _build_exit_event(entry: pd.DataFrame, daily: pd.DataFrame, cfg: RiskConfig) -> pd.DataFrame:
    # sequence helper
    daily_seq = daily[["ts_code", "trade_date", "open", "high", "low", "close", "pct_chg"]].copy()
    daily_seq["row_idx"] = daily_seq.groupby("ts_code").cumcount()

    # map signal(T) -> entry(T+1)
    key_map = daily_seq[["ts_code", "trade_date", "row_idx"]].copy()
    key_map["entry_trade_date"] = key_map.groupby("ts_code")["trade_date"].shift(-1)
    key_map["entry_row_idx"] = key_map.groupby("ts_code")["row_idx"].shift(-1)
    key_map = key_map.rename(columns={"trade_date": "signal_trade_date"})

    allowed = entry[entry["entry_decision"].eq("allow")].copy()
    allowed = allowed.merge(
        key_map[["ts_code", "signal_trade_date", "entry_trade_date", "entry_row_idx"]],
        left_on=["ts_code", "trade_date"],
        right_on=["ts_code", "signal_trade_date"],
        how="left",
    ).drop(columns=["signal_trade_date"])

    # get entry reference price from entry day open
    entry_price_map = daily_seq[["ts_code", "trade_date", "open", "close", "row_idx"]].rename(
        columns={"trade_date": "entry_trade_date", "open": "entry_open", "close": "entry_close"}
    )
    allowed = allowed.merge(
        entry_price_map[["ts_code", "entry_trade_date", "entry_open", "entry_close", "row_idx"]],
        on=["ts_code", "entry_trade_date"],
        how="left",
    )
    allowed = allowed.rename(columns={"row_idx": "entry_row_idx_confirm"})

    events: List[Dict] = []
    for _, r in allowed.iterrows():
        ts = r["ts_code"]
        if pd.isna(r.get("entry_trade_date")):
            events.append(
                {
                    "trade_id": r["signal_event_id"],
                    "ts_code": ts,
                    "entry_trade_date": r.get("entry_trade_date"),
                    "exit_event_date": pd.NA,
                    "exit_rule_class": "no_exit_event",
                    "exit_trigger_flag": False,
                    "exit_trigger_reason": "missing_entry_trade_date",
                    "exit_decision_note": "entry_date_not_found",
                }
            )
            continue

        entry_date = str(r["entry_trade_date"])
        entry_open = r.get("entry_open")
        if pd.isna(entry_open):
            events.append(
                {
                    "trade_id": r["signal_event_id"],
                    "ts_code": ts,
                    "entry_trade_date": entry_date,
                    "exit_event_date": pd.NA,
                    "exit_rule_class": "no_exit_event",
                    "exit_trigger_flag": False,
                    "exit_trigger_reason": "missing_entry_open",
                    "exit_decision_note": "entry_open_not_found",
                }
            )
            continue

        seq = daily_seq[daily_seq["ts_code"].eq(ts)].reset_index(drop=True)
        try:
            start_idx = int(seq.index[seq["trade_date"].eq(entry_date)][0])
        except Exception:
            events.append(
                {
                    "trade_id": r["signal_event_id"],
                    "ts_code": ts,
                    "entry_trade_date": entry_date,
                    "exit_event_date": pd.NA,
                    "exit_rule_class": "no_exit_event",
                    "exit_trigger_flag": False,
                    "exit_trigger_reason": "entry_idx_not_found",
                    "exit_decision_note": "entry_idx_missing",
                }
            )
            continue

        end_idx = min(start_idx + cfg.max_hold_days - 1, len(seq) - 1)
        window = seq.iloc[start_idx : end_idx + 1].copy()
        stop_line = float(entry_open) * (1 - cfg.structural_stop_pct)

        # 1) structural stop
        hit_stop = window[window["low"] <= stop_line]
        if not hit_stop.empty:
            ex = hit_stop.iloc[0]
            events.append(
                {
                    "trade_id": r["signal_event_id"],
                    "ts_code": ts,
                    "entry_trade_date": entry_date,
                    "exit_event_date": ex["trade_date"],
                    "exit_rule_class": "structural_stop",
                    "exit_trigger_flag": True,
                    "exit_trigger_reason": "low_break_structural_stop_line",
                    "exit_decision_note": f"stop_line={stop_line:.4f}",
                }
            )
            continue

        # 2) momentum decay: consecutive down closes
        closes = window["close"].tolist()
        decay_hit_idx = None
        down_count = 0
        for i in range(1, len(closes)):
            if closes[i] < closes[i - 1]:
                down_count += 1
                if down_count >= cfg.momentum_decay_consecutive_down_days:
                    decay_hit_idx = i
                    break
            else:
                down_count = 0
        if decay_hit_idx is not None:
            ex = window.iloc[decay_hit_idx]
            events.append(
                {
                    "trade_id": r["signal_event_id"],
                    "ts_code": ts,
                    "entry_trade_date": entry_date,
                    "exit_event_date": ex["trade_date"],
                    "exit_rule_class": "max_hold_or_momentum_decay",
                    "exit_trigger_flag": True,
                    "exit_trigger_reason": "momentum_decay_consecutive_down_closes",
                    "exit_decision_note": f"down_days={cfg.momentum_decay_consecutive_down_days}",
                }
            )
            continue

        # 3) time stop fallback
        ex = window.iloc[-1]
        events.append(
            {
                "trade_id": r["signal_event_id"],
                "ts_code": ts,
                "entry_trade_date": entry_date,
                "exit_event_date": ex["trade_date"],
                "exit_rule_class": "time_stop",
                "exit_trigger_flag": True,
                "exit_trigger_reason": "max_hold_days_reached",
                "exit_decision_note": f"max_hold_days={cfg.max_hold_days}",
            }
        )

    exit_df = pd.DataFrame(events)
    if exit_df.empty:
        exit_df = pd.DataFrame(
            columns=[
                "trade_id",
                "ts_code",
                "entry_trade_date",
                "exit_event_date",
                "exit_rule_class",
                "exit_trigger_flag",
                "exit_trigger_reason",
                "exit_decision_note",
            ]
        )
    exit_df["exit_event_id"] = exit_df["trade_id"].astype(str) + "_EXIT"
    return exit_df


def _build_trade_validation_record(
    signal: pd.DataFrame, execution: pd.DataFrame, entry: pd.DataFrame, exit_df: pd.DataFrame
) -> pd.DataFrame:
    rec = signal[
        ["signal_event_id", "ts_code", "trade_date", "trade_signal_class", "score_total", "trigger_status"]
    ].copy()
    rec = rec.merge(
        execution[
            [
                "signal_event_id",
                "execution_candidate_event_id",
                "execution_state",
                "execution_ready_flag",
                "execution_reject_reason",
                "execution_risk_tag",
            ]
        ],
        on="signal_event_id",
        how="left",
    )
    rec = rec.merge(
        entry[
            [
                "signal_event_id",
                "entry_event_id",
                "entry_decision",
                "entry_decision_reason",
                "entry_decision_time_tag",
                "industry",
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
    rec["validation_chain_complete"] = (
        rec["signal_event_id"].notna()
        & rec["execution_candidate_event_id"].notna()
        & rec["entry_event_id"].notna()
    )
    rec["trade_validation_record_id"] = rec["signal_event_id"] + "_VAL"
    return rec


def _write_outputs(
    signal: pd.DataFrame,
    execution: pd.DataFrame,
    entry: pd.DataFrame,
    exit_df: pd.DataFrame,
    record: pd.DataFrame,
    cfg: RiskConfig,
) -> Tuple[Path, Path]:
    files = {
        "trade_signal_event_breakout_b.parquet": signal,
        "execution_candidate_event_breakout_b.parquet": execution,
        "entry_event_breakout_b.parquet": entry,
        "exit_event_breakout_b.parquet": exit_df,
        "trade_validation_record_breakout_b.parquet": record,
    }
    for name, df in files.items():
        df.to_parquet(OUT_DIR / name, index=False)

    # QC JSON
    top_not_entry = (
        entry[entry["entry_decision"].ne("allow")]["entry_decision_reason"].value_counts().head(5).to_dict()
    )
    top_exit = exit_df["exit_rule_class"].value_counts().head(5).to_dict()
    qc = {
        "config": {
            "risk_per_trade_budget": cfg.risk_per_trade_budget,
            "max_new_entries_per_day": cfg.max_new_entries_per_day,
            "max_entries_per_industry_per_day": cfg.max_entries_per_industry_per_day,
            "structural_stop_pct": cfg.structural_stop_pct,
            "max_hold_days": cfg.max_hold_days,
            "momentum_decay_consecutive_down_days": cfg.momentum_decay_consecutive_down_days,
        },
        "row_counts": {k: int(len(v)) for k, v in files.items()},
        "chain_integrity": {
            "signal_to_execution_match": int(record["execution_candidate_event_id"].notna().sum()),
            "execution_to_entry_match": int(record["entry_event_id"].notna().sum()),
            "entry_to_exit_match": int(record["exit_event_id"].notna().sum()),
            "validation_chain_complete": int(record["validation_chain_complete"].sum()),
        },
        "top_not_entry_reasons": top_not_entry,
        "top_exit_rule_types": top_exit,
        "future_field_leakage_check": {
            "contains_mfe": False,
            "contains_mae": False,
            "contains_forward_return": False,
        },
    }
    qc_path = OUT_DIR / "breakout_b_trade_validation_qc.json"
    qc_path.write_text(json.dumps(qc, ensure_ascii=False, indent=2), encoding="utf-8")

    # short report
    report_lines = [
        "# breakout-B trade validation impl report",
        "",
        "## Scope",
        "- breakout-B only",
        "- no backtest / no performance stats / no parameter search",
        "",
        "## Tables generated",
    ]
    for name, df in files.items():
        report_lines.append(f"- {name}: {len(df)} rows")
    report_lines += [
        "",
        "## Minimal field contracts",
        "- trade_signal_event_breakout_b:",
        "  - signal_event_id, ts_code, trade_date, trade_signal_class, score_total, trigger_status, trigger_groups_passed, explain_json",
        "- execution_candidate_event_breakout_b:",
        "  - execution_candidate_event_id, signal_event_id, execution_mode_candidate, execution_state, execution_ready_flag, execution_reject_reason, execution_risk_tag, key_reason_1/2/3",
        "- entry_event_breakout_b:",
        "  - entry_event_id, signal_event_id, entry_decision, entry_decision_reason, entry_decision_time_tag, risk_per_trade_budget",
        "- exit_event_breakout_b:",
        "  - exit_event_id, trade_id, entry_trade_date, exit_event_date, exit_rule_class, exit_trigger_reason",
        "- trade_validation_record_breakout_b:",
        "  - trade_validation_record_id, signal_event_id, execution_candidate_event_id, entry_event_id, exit_event_id, validation_chain_complete",
        "",
        "## Chain integrity",
        f"- signal -> execution matched: {qc['chain_integrity']['signal_to_execution_match']}",
        f"- execution -> entry matched: {qc['chain_integrity']['execution_to_entry_match']}",
        f"- entry -> exit matched: {qc['chain_integrity']['entry_to_exit_match']}",
        f"- complete validation chain rows: {qc['chain_integrity']['validation_chain_complete']}",
        "",
        "## Top not-entry reasons",
    ]
    for k, v in top_not_entry.items():
        report_lines.append(f"- {k}: {v}")
    report_lines += ["", "## Top exit event types"]
    for k, v in top_exit.items():
        report_lines.append(f"- {k}: {v}")
    report_lines += [
        "",
        "## Data leakage guard",
        "- No future performance fields read into signal/execution/entry decisions.",
    ]
    report_path = OUT_DIR / "breakout_b_trade_validation_impl_report.md"
    report_path.write_text("\n".join(report_lines), encoding="utf-8")
    return report_path, qc_path


def main() -> None:
    cfg = RiskConfig()
    scan = _load_scan()
    exec_df = _load_exec()
    daily = _load_daily()

    signal = _prepare_signal_event(scan, exec_df)
    execution = _prepare_execution_candidate(signal, exec_df, daily)
    entry = _build_entry_event(execution, cfg)
    exit_df = _build_exit_event(entry, daily, cfg)
    record = _build_trade_validation_record(signal, execution, entry, exit_df)
    report_path, qc_path = _write_outputs(signal, execution, entry, exit_df, record, cfg)

    print("Generated breakout-B trade validation artifacts:")
    print(" -", (OUT_DIR / "trade_signal_event_breakout_b.parquet"))
    print(" -", (OUT_DIR / "execution_candidate_event_breakout_b.parquet"))
    print(" -", (OUT_DIR / "entry_event_breakout_b.parquet"))
    print(" -", (OUT_DIR / "exit_event_breakout_b.parquet"))
    print(" -", (OUT_DIR / "trade_validation_record_breakout_b.parquet"))
    print(" -", report_path)
    print(" -", qc_path)


if __name__ == "__main__":
    main()
