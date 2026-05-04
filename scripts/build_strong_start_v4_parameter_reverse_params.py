# -*- coding: utf-8 -*-
"""将「参数反推」宽松档预设导出为 YAML，便于与报告、回测脚本对照。"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from dataclasses import asdict
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> None:
    parser = argparse.ArgumentParser(description="Export tradeable_v4_parameter_reverse_loose to YAML.")
    parser.add_argument(
        "--output-path",
        default="data/research/strong_start_full/strong_start_v4_parameter_reverse_loose_params.yaml",
    )
    args = parser.parse_args()

    from src.modules.strong_start_strategy import StrongStartParams

    p = StrongStartParams.tradeable_v4_parameter_reverse_loose()
    out_path = ROOT / str(args.output_path).replace("\\", "/")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        "preset_name": "tradeable_v4_parameter_reverse_loose",
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source_report": "data/research/strong_start_full/parameter_reverse_engineering_report.md",
        "mapping_notes": [
            "宽松档：f_strength_rs20_xsec_q / f_chip_winner_rate / f_breakout_vol_ratio20 / f_k_close_pos → 见 StrongStartParams.tradeable_v4_parameter_reverse_loose 文档字符串",
            "chip_factor_profile_key 沿用 tradeable_v3_research 物化表",
        ],
        "strategy_params": asdict(p),
    }
    out_path.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")
    print(f"written: {out_path}")


if __name__ == "__main__":
    main()
