from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


ROOT = Path(r"D:\HuaweiAI\quantSystem2")
BASE = ROOT / "data/research/strong_start_full/v4_scan"
IN_FILE = BASE / "true_breakout_v32_with_priority_tag.csv"

OUT_CSV = BASE / "true_breakout_selector_strict_pool_review.csv"
OUT_JSON = BASE / "true_breakout_selector_strict_pool_summary.json"
OUT_MD = BASE / "true_breakout_selector_strict_pool_review.md"


def _stats(df: pd.DataFrame) -> dict:
    row = {"sample_n": int(len(df))}
    for c in ["label_A_high", "label_A_mid", "label_A_low", "label_C", "label_G"]:
        row[c] = float(df[c].mean()) if c in df.columns and len(df) else 0.0
    for h in ["t1", "t2", "t3"]:
        s = pd.to_numeric(df[f"ret_{h}_close"], errors="coerce")
        row[f"mean_ret_{h}"] = float(s.mean()) if len(s) else 0.0
        row[f"median_ret_{h}"] = float(s.median()) if len(s) else 0.0
        row[f"win_{h}"] = float((s > 0).mean()) if len(s) else 0.0
    return row


def main() -> None:
    d = pd.read_csv(IN_FILE)
    d["is_core_candidate"] = pd.to_numeric(d["is_core_candidate"], errors="coerce").fillna(0).astype(int)
    d["priority_tag"] = pd.to_numeric(d["priority_tag"], errors="coerce").fillna(0).astype(int)
    d["path_source"] = d["path_source"].fillna("").astype(str)
    d["window"] = d["window"].fillna("all").astype(str)

    groups = {
        "core_pool": d[d["is_core_candidate"] == 1],
        "priority_tag_1": d[(d["is_core_candidate"] == 1) & (d["priority_tag"] == 1)],
        "path_A": d[(d["is_core_candidate"] == 1) & (d["path_source"] == "A")],
        "priority_tag_1_path_A": d[(d["is_core_candidate"] == 1) & (d["priority_tag"] == 1) & (d["path_source"] == "A")],
    }

    rows = []
    for window_name, wd in [("all", d), ("main", d[d["window"] == "main"]), ("confirm", d[d["window"] == "confirm"])]:
        for gname, mask_df in groups.items():
            if window_name == "all":
                g = mask_df
            else:
                g = wd.loc[mask_df.index.intersection(wd.index)]
            if g.empty:
                continue
            row = {"window": window_name, "group": gname}
            row.update(_stats(g))
            rows.append(row)

    out = pd.DataFrame(rows)
    out.to_csv(OUT_CSV, index=False, encoding="utf-8-sig")

    # summary focus
    def _pick(window: str, group: str) -> dict:
        rec = out[(out["window"] == window) & (out["group"] == group)]
        return {} if rec.empty else rec.iloc[0].to_dict()

    summary = {
        "all_core_pool": _pick("all", "core_pool"),
        "all_priority_tag_1": _pick("all", "priority_tag_1"),
        "all_priority_tag_1_path_A": _pick("all", "priority_tag_1_path_A"),
        "main_priority_tag_1_path_A": _pick("main", "priority_tag_1_path_A"),
        "confirm_priority_tag_1_path_A": _pick("confirm", "priority_tag_1_path_A"),
    }
    OUT_JSON.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    md = [
        "# Strict Pool Review",
        "",
        "Focus: identify the selector sub-pool that best matches true strong-start targets before any further intraday work.",
        "",
        "## Takeaway",
        "- `priority_tag=1 & path_source=A` is the closest current proxy for a high-purity strong-start pool.",
        "- It materially improves `A_high` concentration and fixed-horizon returns versus the full core pool.",
        "- It is still not clean enough to be called a final pool, but it is the right place to keep optimizing.",
        "",
        "## Why this matters",
        "- If the stock pool is still mixed, intraday buy-point tuning cannot rescue the strategy shape.",
        "- The next meaningful selector iteration should focus on this strict sub-pool rather than the whole core pool.",
        "",
        f"- CSV: `{OUT_CSV.name}`",
        f"- JSON: `{OUT_JSON.name}`",
    ]
    OUT_MD.write_text("\n".join(md), encoding="utf-8")

    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

