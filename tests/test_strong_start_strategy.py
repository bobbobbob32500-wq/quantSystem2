# -*- coding: utf-8 -*-
"""Tests for the strong-start strategy pipeline."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


def _make_temp_db(tmp_path: Path):
    from src.core.database import DatabaseManager

    return DatabaseManager(db_path=str(tmp_path / "quant_test.db"))


def _seed_basic(db) -> None:
    sql = """
        REPLACE INTO stock_basic (ts_code, symbol, name, industry, list_date)
        VALUES (?, ?, ?, ?, ?)
    """
    db.execute_many(
        sql,
        [
            ("000001.SZ", "000001", "启动样本", "电子", "20200101"),
            ("000002.SZ", "000002", "对照样本", "机械", "20200101"),
            ("000001.SH", "000001", "上证指数", "指数", "19901219"),
        ],
    )


def _insert_daily_rows(db, rows) -> None:
    sql = """
        REPLACE INTO stock_daily (ts_code, trade_date, open, close, high, low, vol, amount, pct_chg)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    db.execute_many(sql, rows)


def _insert_chip_rows(db, rows) -> None:
    sql = """
        REPLACE INTO stock_chip_perf (
            ts_code, trade_date, cost_5pct, cost_15pct, cost_50pct,
            cost_85pct, cost_95pct, weight_avg, winner_rate
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    db.execute_many(sql, rows)


def _insert_chip_dist_rows(db, rows) -> None:
    sql = """
        REPLACE INTO stock_chip_dist (
            ts_code, trade_date, price, weight
        )
        VALUES (?, ?, ?, ?)
    """
    db.execute_many(sql, rows)


def _seed_daily_and_chip(db) -> str:
    dates = pd.bdate_range("2025-01-02", periods=140)
    trade_dates = [d.strftime("%Y%m%d") for d in dates]

    rows = []
    prev_close = {}

    def add_row(ts_code: str, trade_date: str, open_p: float, close_p: float, high_p: float, low_p: float, vol: float, amount: float):
        last_close = prev_close.get(ts_code)
        pct_chg = None if last_close is None else round((close_p - last_close) / last_close * 100.0, 2)
        rows.append((ts_code, trade_date, open_p, close_p, high_p, low_p, vol, amount, pct_chg))
        prev_close[ts_code] = close_p

    for idx, trade_date in enumerate(trade_dates):
        # Candidate stock: long mild base -> tight platform -> breakout on the last day.
        if idx < 90:
            close_p = 10.55 + idx * 0.0005 + [0.00, 0.01, -0.01, 0.005, -0.005][idx % 5]
            open_p = close_p - 0.01
            high_p = close_p + 0.03
            low_p = close_p - 0.03
            vol = 900.0
        elif idx < len(trade_dates) - 1:
            close_p = 10.76 + [0.00, -0.02, 0.03, -0.01, 0.02][idx % 5]
            open_p = close_p - 0.01
            high_p = close_p + 0.03
            low_p = close_p - 0.04
            vol = 620.0
        else:
            close_p = 10.96
            open_p = 10.82
            high_p = 11.03
            low_p = 10.80
            vol = 2800.0
        add_row("000001.SZ", trade_date, round(open_p, 2), round(close_p, 2), round(high_p, 2), round(low_p, 2), vol, 150000.0)

        # Control stock: weaker relative strength and poor chip profile.
        close_p = 12.30 - idx * 0.002 + [0.00, 0.01, -0.01, 0.00, -0.02][idx % 5]
        open_p = close_p + 0.01
        high_p = close_p + 0.03
        low_p = close_p - 0.04
        add_row("000002.SZ", trade_date, round(open_p, 2), round(close_p, 2), round(high_p, 2), round(low_p, 2), 950.0, 130000.0)

        # Benchmark index used by the market gate.
        index_close = 3000.0 + idx * 0.6
        add_row(
            "000001.SH",
            trade_date,
            round(index_close - 5.0, 2),
            round(index_close, 2),
            round(index_close + 8.0, 2),
            round(index_close - 8.0, 2),
            1000000.0,
            500000.0,
        )

    _insert_daily_rows(db, rows)

    chip_rows = []
    chip_dist_rows = []
    chip_dates = trade_dates[-30:]
    candidate_dist = [
        (10.66, 0.01),
        (10.69, 0.02),
        (10.72, 0.05),
        (10.75, 0.08),
        (10.78, 0.12),
        (10.80, 0.31),
        (10.82, 0.16),
        (10.84, 0.10),
        (10.87, 0.07),
        (10.90, 0.04),
        (10.93, 0.03),
        (10.96, 0.01),
    ]
    control_dist = [
        (11.70, 0.08),
        (11.80, 0.06),
        (11.90, 0.14),
        (12.00, 0.06),
        (12.10, 0.05),
        (12.20, 0.13),
        (12.30, 0.06),
        (12.40, 0.09),
        (12.50, 0.05),
        (12.60, 0.10),
        (12.70, 0.08),
        (12.80, 0.10),
    ]
    for offset, trade_date in enumerate(chip_dates):
        chip_rows.append(
            (
                "000001.SZ",
                trade_date,
                10.71 + (offset % 3) * 0.002,
                10.74 + (offset % 3) * 0.002,
                10.78 + (offset % 3) * 0.002,
                10.82 + (offset % 3) * 0.002,
                10.85 + (offset % 3) * 0.002,
                10.79 + (offset % 3) * 0.002,
                0.56,
            )
        )
        chip_rows.append(
            (
                "000002.SZ",
                trade_date,
                11.90,
                12.10,
                12.30,
                12.55,
                12.80,
                12.35,
                0.95,
            )
        )
        for price, weight in candidate_dist:
            chip_dist_rows.append(("000001.SZ", trade_date, price, weight))
        for price, weight in control_dist:
            chip_dist_rows.append(("000002.SZ", trade_date, price, weight))
    _insert_chip_rows(db, chip_rows)
    _insert_chip_dist_rows(db, chip_dist_rows)
    return trade_dates[-1]


def test_database_initializes_chip_table(tmp_path):
    db = _make_temp_db(tmp_path)
    perf = db.query_one(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='stock_chip_perf'"
    )
    dist = db.query_one(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='stock_chip_dist'"
    )
    assert perf is not None
    assert dist is not None


def test_merge_strong_start_candidate_cache_preserves_other_strategies(tmp_path):
    from src.modules.strong_start_selector_menu import merge_strong_start_candidates_to_candidate_cache
    from src.modules.strong_start_strategy import StrongStartCandidate

    cache_dir = tmp_path / "data" / "cache"
    cache_dir.mkdir(parents=True)
    pool_path = cache_dir / "candidate_pool.json"
    pool_path.write_text(
        json.dumps(
            {
                "date": "20250101",
                "candidates": [
                    {"symbol": "999999", "strategy_profile": "secondary_launch", "score": 50.0},
                    {"symbol": "000001", "strategy_profile": "strong_start", "score": 40.0},
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    candidate = StrongStartCandidate(
        ts_code="000001.SZ",
        name="启动样本",
        watch_date="20250501",
        setup_type="breakout",
        close=10.96,
        pivot=10.82,
        trigger_price=10.96,
        stop_loss=10.75,
        signal_score=78.0,
        volume_ratio=2.8,
        platform_range=4.5,
        chip_concentration=1.2,
        chip_low_position=48.0,
        rs20=5.0,
        rs20_xsec_q=0.95,
        industry="电子",
        score_detail="test",
    )

    count = merge_strong_start_candidates_to_candidate_cache([candidate], "20250501", project_root=tmp_path)
    assert count == 1

    payload = json.loads(pool_path.read_text(encoding="utf-8"))
    profiles = [row.get("strategy_profile") for row in payload["candidates"]]
    assert "secondary_launch" in profiles
    assert profiles.count("strong_start") == 1


def test_strong_start_strategy_selects_breakout_candidate(tmp_path):
    from src.modules.strong_start_strategy import StrongStartParams, StrongStartStrategy

    db = _make_temp_db(tmp_path)
    _seed_basic(db)
    end_date = _seed_daily_and_chip(db)

    params = StrongStartParams(min_signal_score=50.0, top_k=5)
    strategy = StrongStartStrategy(db=db, params=params)
    candidates = strategy.run(end_date=end_date)

    assert candidates
    first = candidates[0]
    assert first.ts_code == "000001.SZ"
    assert first.setup_type == "breakout"
    assert first.signal_score >= 50.0
    assert first.chip_concentration <= 12.0
    assert first.single_peak_dense_score >= 0.55

    persisted = db.query_one(
        """
        SELECT factor_value
        FROM factor_values
        WHERE ts_code = ? AND trade_date = ? AND factor_name = ?
        """,
        ("000001.SZ", end_date, "strong_start_single_peak_dense_score"),
    )
    assert persisted is not None
    assert float(persisted["factor_value"]) >= 0.55


def test_src_modules_exports_strong_start():
    import src.modules as modules

    assert modules.StrongStartStrategy is not None
    assert modules.StrongStartParams is not None


def test_tradeable_preset_is_relaxed():
    from src.modules.strong_start_strategy import StrongStartParams

    base = StrongStartParams()
    preset = StrongStartParams.tradeable_v1()

    assert preset.min_amt_ma20 < base.min_amt_ma20
    assert preset.rs_quantile_min < base.rs_quantile_min
    assert preset.platform_max_range > base.platform_max_range
    assert preset.breakout_volume_ratio < base.breakout_volume_ratio
    assert preset.min_signal_score < base.min_signal_score


def test_tradeable_v2_preset_is_conservative():
    from src.modules.strong_start_strategy import StrongStartParams

    base = StrongStartParams.tradeable_v1()
    preset = StrongStartParams.tradeable_v2()

    assert preset.platform_max_range < base.platform_max_range
    assert preset.vol_contraction_ratio < base.vol_contraction_ratio
    assert preset.low_vol_days_required > base.low_vol_days_required
    assert preset.chip_concentration_max < base.chip_concentration_max
    assert preset.chip_single_peak_score_min > base.chip_single_peak_score_min
    assert preset.top_k < base.top_k
    assert preset.allow_breakout_setup is False
    assert preset.allow_pullback_setup is True
    assert preset.chip_factor_profile_key == "tradeable_v2"


def test_market_gate_does_not_expand_topk(monkeypatch, tmp_path):
    from src.modules.breakout_strategy import BreakoutStrategy
    from src.modules.strong_start_strategy import StrongStartParams, StrongStartStrategy

    db = _make_temp_db(tmp_path)
    params = StrongStartParams.tradeable_v2()
    params.top_k = 1
    strategy = StrongStartStrategy(db=db, params=params)

    monkeypatch.setattr(BreakoutStrategy, "_market_gate", lambda self, features, end_date: (66.0, 3))
    min_score, top_k = strategy._market_gate(pd.DataFrame(), "20260403")
    assert min_score == 66.0
    assert top_k == 1
