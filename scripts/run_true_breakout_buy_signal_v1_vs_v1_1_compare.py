from __future__ import annotations

from pathlib import Path

import pandas as pd


ROOT = Path(r"D:\HuaweiAI\quantSystem2")
BASE = ROOT / "data/research/strong_start_full/v4_scan"
IN_V1 = BASE / "true_breakout_buy_signal_v1.csv"
IN_V11 = BASE / "true_breakout_buy_signal_v1_1.csv"
OUT_COMPARE = BASE / "true_breakout_buy_signal_v1_vs_v1_1_compare.csv"


def _group_masks(df: pd.DataFrame) -> dict[str, pd.Series]:
    return {
        "overall": pd.Series(True, index=df.index),
        "priority_tag_1": df["priority_tag"] == 1,
        "path_source_A": df["path_source"] == "A",
        "path_source_B": df["path_source"] == "B",
        "priority_tag_1_path_A": (df["priority_tag"] == 1) & (df["path_source"] == "A"),
    }


def _stats(df: pd.DataFrame) -> dict[str, float]:
    out = {
        "sample_n": int(len(df)),
        "trigger_n": int((df["signal_triggered"] == 1).sum()),
        "trigger_rate": float((df["signal_triggered"] == 1).mean()) if len(df) else 0.0,
        "pullback_confirm_n": int((df["signal_type"] == "pullback_confirm").sum()),
        "breakout_confirm_n": int((df["signal_type"] == "breakout_confirm").sum()),
        "range_break_confirm_n": int((df["signal_type"] == "range_break_confirm").sum()),
    }
    for h in ["t1", "t2", "t3"]:
        s_all = pd.to_numeric(df[f"ret_{h}_close"], errors="coerce")
        s_trig = pd.to_numeric(df.loc[df["signal_triggered"] == 1, f"ret_{h}_close"], errors="coerce")
        out[f"mean_ret_{h}"] = float(s_all.mean()) if len(s_all) else float("nan")
        out[f"win_{h}"] = float((s_all > 0).mean()) if len(s_all) else float("nan")
        out[f"trig_mean_ret_{h}"] = float(s_trig.mean()) if len(s_trig) else float("nan")
        out[f"trig_win_{h}"] = float((s_trig > 0).mean()) if len(s_trig) else float("nan")
    return out


def _build(name: str, df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for gname, mask in _group_masks(df).items():
        g = df[mask].copy()
        if g.empty:
            continue
        row = {"version": name, "group": gname}
        row.update(_stats(g))
        rows.append(row)
    return pd.DataFrame(rows)


def main() -> None:
    v1 = pd.read_csv(IN_V1)
    v11 = pd.read_csv(IN_V11)
    for d in [v1, v11]:
        d["priority_tag"] = pd.to_numeric(d["priority_tag"], errors="coerce").fillna(0).astype(int)
        d["signal_triggered"] = pd.to_numeric(d["signal_triggered"], errors="coerce").fillna(0).astype(int)
        d["path_source"] = d["path_source"].fillna("").astype(str)
        d["signal_type"] = d["signal_type"].fillna("").astype(str)

    out = pd.concat([_build("v1", v1), _build("v1_1", v11)], ignore_index=True)
    out.to_csv(OUT_COMPARE, index=False, encoding="utf-8-sig")

    print(OUT_COMPARE)


if __name__ == "__main__":
    main()
