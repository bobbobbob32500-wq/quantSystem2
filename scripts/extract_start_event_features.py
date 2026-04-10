# -*- coding: utf-8 -*-
"""Extract T-day features for labeled strong-start events."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.modules.strong_start_sample_mining import SampleMiningConfig, make_miner  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract strong-start event features.")
    parser.add_argument("--events-path", default="data/research/strong_start/labeled_events.parquet")
    parser.add_argument("--output-dir", default="data/research/strong_start")
    args = parser.parse_args()

    path = Path(args.events_path)
    if not path.exists():
        raise FileNotFoundError(f"labeled events not found: {path}")

    labeled = pd.read_parquet(path)
    miner = make_miner(SampleMiningConfig(output_dir=args.output_dir))
    feats = miner.extract_features(labeled)
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    event_features_path = out_dir / "event_features.parquet"
    feats.to_parquet(event_features_path, index=False)

    print("=" * 70)
    print("strong-start feature extraction done")
    print("=" * 70)
    print(f"input_rows={len(labeled)} feature_rows={len(feats)}")
    print(f"event_features={event_features_path}")


if __name__ == "__main__":
    main()
