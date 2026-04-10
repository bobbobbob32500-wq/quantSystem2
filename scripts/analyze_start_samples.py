# -*- coding: utf-8 -*-
"""Analyze strong-start event samples and export threshold hints."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.modules.strong_start_sample_mining import SampleMiningConfig, make_miner  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze strong-start event sample features.")
    parser.add_argument("--events-path", default="data/research/strong_start/event_features.parquet")
    parser.add_argument("--output-dir", default="data/research/strong_start")
    args = parser.parse_args()

    path = Path(args.events_path)
    if not path.exists():
        raise FileNotFoundError(f"event features not found: {path}")

    feats = pd.read_parquet(path)
    miner = make_miner(SampleMiningConfig(output_dir=args.output_dir))
    summary, thresholds, report = miner.analyze_features(feats)
    outputs = miner.save_feature_outputs(
        event_features=feats,
        summary=summary,
        thresholds=thresholds,
        report=report,
        out_dir=args.output_dir,
    )

    print("=" * 70)
    print("strong-start sample analysis done")
    print("=" * 70)
    print(f"input_rows={len(feats)} summary_rows={len(summary)}")
    for key, out in outputs.items():
        print(f"{key}={out}")


if __name__ == "__main__":
    main()

