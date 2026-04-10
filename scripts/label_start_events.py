# -*- coding: utf-8 -*-
"""Label strong-start event candidates into A/B/C classes."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.modules.strong_start_sample_mining import SampleMiningConfig, make_miner  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Label strong-start event candidates.")
    parser.add_argument("--events-path", default="data/research/strong_start/candidate_events.parquet")
    parser.add_argument("--output-dir", default="data/research/strong_start")
    parser.add_argument("--hold-days", type=int, default=5)
    parser.add_argument("--entry-max-gap-pct", type=float, default=0.06)
    parser.add_argument("--label-a-mfe-min", type=float, default=0.10)
    parser.add_argument("--label-a-mae-max", type=float, default=0.05)
    parser.add_argument("--label-b-mfe-min", type=float, default=0.06)
    parser.add_argument("--label-b-mae-max", type=float, default=0.06)
    args = parser.parse_args()

    path = Path(args.events_path)
    if not path.exists():
        raise FileNotFoundError(f"candidate events not found: {path}")

    events = pd.read_parquet(path)
    cfg = SampleMiningConfig(
        output_dir=args.output_dir,
        hold_days=max(int(args.hold_days), 1),
        entry_max_gap_pct=float(args.entry_max_gap_pct),
        label_a_mfe_min=float(args.label_a_mfe_min),
        label_a_mae_max=float(args.label_a_mae_max),
        label_b_mfe_min=float(args.label_b_mfe_min),
        label_b_mae_max=float(args.label_b_mae_max),
    )
    miner = make_miner(cfg)
    labeled = miner.label_candidates(events)
    outputs = miner.save_labeled_outputs(labeled, args.output_dir)

    print("=" * 70)
    print("strong-start labels done")
    print("=" * 70)
    print(f"input_rows={len(events)} output_rows={len(labeled)}")
    for key, out in outputs.items():
        print(f"{key}={out}")


if __name__ == "__main__":
    main()

