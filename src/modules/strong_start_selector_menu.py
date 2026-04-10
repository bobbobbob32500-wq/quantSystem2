# -*- coding: utf-8 -*-
"""Helpers for syncing strong-start candidates into the shared candidate cache."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from src.core.logger import get_logger
from src.modules.strong_start_strategy import StrongStartCandidate

logger = get_logger("strong_start_selector_menu")


def merge_strong_start_candidates_to_candidate_cache(
    candidates: List[StrongStartCandidate],
    trade_date: str,
    project_root: Optional[Path] = None,
) -> int:
    root = project_root or Path(__file__).resolve().parents[2]
    cache_path = root / "data" / "cache" / "candidate_pool.json"
    cache_path.parent.mkdir(parents=True, exist_ok=True)

    previous: List[dict] = []
    if cache_path.exists():
        try:
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                raw = payload.get("candidates")
                if isinstance(raw, list):
                    previous = [
                        row
                        for row in raw
                        if isinstance(row, dict) and str(row.get("strategy_profile", "")).lower() != "strong_start"
                    ]
        except Exception as exc:
            logger.warning("Failed to read candidate cache, will overwrite strong_start entries: %s", exc)

    synced: List[dict] = []
    for item in candidates or []:
        symbol = str(item.ts_code or "").strip().split(".", 1)[0]
        if not symbol:
            continue
        synced.append(
            {
                "symbol": symbol,
                "ts_code": str(item.ts_code or ""),
                "name": str(item.name or ""),
                "score": float(item.signal_score or 0.0),
                "level": "强势股刚启动",
                "industry": str(item.industry or "未知"),
                "pool_type": "core",
                "strategy_profile": "strong_start",
                "strategy_name": "strong_start_v1",
                "source": "strong_start_strategy",
                "trade_date": str(trade_date or ""),
                "setup_type": str(item.setup_type or ""),
                "trigger_price": float(item.trigger_price or 0.0),
                "pivot": float(item.pivot or 0.0),
                "stop_loss": float(item.stop_loss or 0.0),
                "volume_ratio": float(item.volume_ratio or 0.0),
                "platform_range": float(item.platform_range or 0.0),
                "chip_concentration": float(item.chip_concentration or 0.0),
                "chip_low_position": float(item.chip_low_position or 0.0),
                "breakout_date": str(item.breakout_date or ""),
                "score_detail": str(item.score_detail or ""),
            }
        )

    merged = previous + synced
    merged = sorted(merged, key=lambda row: float(row.get("score", 0.0) or 0.0), reverse=True)[:30]
    payload = {
        "date": str(trade_date or ""),
        "candidates": merged,
        "created_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "strong_start_synced": len(synced),
    }
    cache_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return len(synced)
