# -*- coding: utf-8 -*-
"""Build event-level strong-start candidate days."""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.modules.strong_start_sample_mining import SampleMiningConfig, make_miner  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Build strong-start sample-mining candidates.")
    parser.add_argument("--start-date", required=True, help="YYYYMMDD")
    parser.add_argument("--end-date", required=True, help="YYYYMMDD")
    parser.add_argument("--output-dir", default="data/research/strong_start")
    parser.add_argument("--event-cooldown-days", type=int, default=12)
    parser.add_argument("--candidate-min-conditions", type=int, default=3)
    parser.add_argument("--candidate-pct-chg-min", type=float, default=3.0)
    parser.add_argument("--candidate-vol-ratio-min", type=float, default=1.2)
    args = parser.parse_args()

    cfg = SampleMiningConfig(
        output_dir=args.output_dir,
        event_cooldown_days=max(int(args.event_cooldown_days), 1),
        candidate_min_conditions=max(int(args.candidate_min_conditions), 1),
        candidate_pct_chg_min=float(args.candidate_pct_chg_min),
        candidate_vol_ratio_min=float(args.candidate_vol_ratio_min),
    )
    miner = make_miner(cfg)
    events = miner.build_candidates(args.start_date, args.end_date)
    outputs = miner.save_candidate_outputs(events, args.output_dir)

    print("=" * 70)
    print("strong-start candidates done")
    print("=" * 70)
    print(f"window={args.start_date}..{args.end_date}")
    print(f"rows={len(events)}")
    for key, path in outputs.items():
        print(f"{key}={path}")


if __name__ == "__main__":
    main()
