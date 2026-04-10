# -*- coding: utf-8 -*-
"""Real-data tests for the A-share pre-market stock selector."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest

from src.core.config import ConfigManager
from src.modules.stock_selector import StockSelector


MAIN_BOARD_SQL = """
    ts_code LIKE '600%.SH' OR ts_code LIKE '601%.SH' OR ts_code LIKE '603%.SH' OR ts_code LIKE '605%.SH'
    OR ts_code LIKE '000%.SZ' OR ts_code LIKE '001%.SZ' OR ts_code LIKE '002%.SZ' OR ts_code LIKE '003%.SZ'
"""


def _get_db_path() -> Path:
    config = ConfigManager()
    return Path(config.get("database.path", "data/database/quant_system.db"))


@pytest.fixture(scope="module")
def selector() -> StockSelector:
    db_path = _get_db_path()
    if not db_path.exists():
        pytest.skip(f"real market database not found: {db_path}")

    config = ConfigManager()
    config.set("stock_selection.save_factor_values", False, save=False)
    config.set("stock_selection.strategy_profile", "enhanced", save=False)
    return StockSelector(config=config)


def _query_single_value(sql: str, params: tuple = ()) -> str | None:
    db_path = _get_db_path()
    conn = sqlite3.connect(str(db_path))
    try:
        row = conn.execute(sql, params).fetchone()
        return row[0] if row else None
    finally:
        conn.close()


def _latest_trade_date() -> str:
    latest = _query_single_value("SELECT MAX(trade_date) FROM stock_daily")
    if not latest:
        pytest.skip("stock_daily has no rows")
    return str(latest)


def _pick_historical_trade_date(offset_from_latest: int = 260) -> str:
    db_path = _get_db_path()
    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute(
            "SELECT DISTINCT trade_date FROM stock_daily ORDER BY trade_date"
        ).fetchall()
    finally:
        conn.close()

    if len(rows) <= offset_from_latest + 5:
        pytest.skip("not enough history for point-in-time test")
    return str(rows[-offset_from_latest][0])


def _is_main_board(ts_code: str) -> bool:
    if "." not in ts_code:
        return False
    code, market = ts_code.split(".")
    if market == "SH":
        return code.startswith(("600", "601", "603", "605"))
    if market == "SZ":
        return code.startswith(("000", "001", "002", "003"))
    return False


def test_filter_basic_keeps_only_main_board(selector: StockSelector):
    stock_list = selector.get_stock_list()
    filtered = selector.filter_basic(stock_list)

    assert not filtered.empty
    assert filtered["ts_code"].str.endswith((".SH", ".SZ")).all()
    assert filtered["ts_code"].map(_is_main_board).all()


def test_filter_basic_uses_end_date_for_new_stock_rule(selector: StockSelector):
    stock_list = selector.get_stock_list(point_in_time=False)
    if stock_list.empty:
        pytest.skip("stock_basic has no rows")

    end_date = _latest_trade_date()
    end_dt = datetime.strptime(end_date, "%Y%m%d")
    min_list_date = (end_dt - timedelta(days=selector.exclude_new)).strftime("%Y%m%d")

    filtered = selector.filter_basic(stock_list, end_date=end_date)
    filtered_codes = set(filtered["ts_code"].tolist())

    base = stock_list.copy()
    if selector.exclude_st:
        base = base[~base["name"].str.contains("ST|st|退", na=False)]
    base = base[base["ts_code"].map(_is_main_board)]

    normalized_list_date = (
        base["list_date"]
        .astype(str)
        .str.replace("-", "", regex=False)
        .str.slice(0, 8)
    )
    recent_new_mask = normalized_list_date.between(min_list_date, end_date, inclusive="both")
    recent_new_codes = set(base.loc[recent_new_mask, "ts_code"].tolist())
    if not recent_new_codes:
        pytest.skip("no recent listings found for new-stock filter check")

    assert recent_new_codes.isdisjoint(filtered_codes)


def test_get_stock_list_point_in_time_uses_end_date(selector: StockSelector):
    end_date = _pick_historical_trade_date(offset_from_latest=260)
    stock_list = selector.get_stock_list(end_date=end_date, point_in_time=True)
    if stock_list.empty:
        pytest.skip("point-in-time universe is empty")

    assert "latest_trade_date" in stock_list.columns
    latest_dates = stock_list["latest_trade_date"].astype(str)
    assert (latest_dates <= end_date).all()

    cutoff = (
        datetime.strptime(end_date, "%Y%m%d") - timedelta(days=selector.universe_max_stale_days)
    ).strftime("%Y%m%d")
    assert (latest_dates >= cutoff).all()


def test_run_selection_defaults_to_latest_trade_date(selector: StockSelector, monkeypatch):
    latest_trade_date = _latest_trade_date()
    captured = {}

    def fake_get_stock_list(end_date=None, point_in_time=True):
        captured["get_stock_list_end_date"] = end_date
        return pd.DataFrame(
            [
                {
                    "ts_code": "000001.SZ",
                    "name": "平安银行",
                    "industry": "银行",
                    "list_date": "19910403",
                }
            ]
        )

    def fake_filter_basic(stock_list, end_date=None):
        captured["filter_basic_end_date"] = end_date
        return stock_list

    def fake_get_dynamic_industry_strength(end_date=None, top_n=5):
        captured["industry_snapshot_end_date"] = end_date
        return []

    def fake_get_tradeability_thresholds(end_date=None):
        captured["threshold_end_date"] = end_date
        return {
            "source": "dynamic",
            "sample_size": 1000,
            "min_avg_amount_20d": selector.min_avg_amount_20d,
            "max_recent_limit_up_count_20d": selector.max_recent_limit_up_count_20d,
            "max_recent_return_20d": selector.max_recent_return_20d,
            "max_avg_amplitude_10d": selector.max_avg_amplitude_10d,
            "max_latest_pct_chg": selector.max_latest_pct_chg,
            "end_date": latest_trade_date,
        }

    def fake_calculate_stock_score(
        ts_code,
        name,
        industry,
        end_date=None,
        list_date=None,
        dynamic_tradeability_thresholds=None,
    ):
        captured["calculate_stock_score_end_date"] = end_date
        return {
            "ts_code": ts_code,
            "name": name,
            "industry": industry,
            "total_score": 80.0,
            "short_cycle_score": 70.0,
            "tradeability_score": 85.0,
            "level": "推荐",
        }

    monkeypatch.setattr(selector, "get_stock_list", fake_get_stock_list)
    monkeypatch.setattr(selector, "filter_basic", fake_filter_basic)
    monkeypatch.setattr(selector, "get_dynamic_industry_strength", fake_get_dynamic_industry_strength)
    monkeypatch.setattr(selector, "get_tradeability_thresholds", fake_get_tradeability_thresholds)
    monkeypatch.setattr(selector, "calculate_stock_score", fake_calculate_stock_score)

    results = selector.run_selection(end_date=None)
    assert results
    assert captured["get_stock_list_end_date"] == latest_trade_date
    assert captured["filter_basic_end_date"] == latest_trade_date
    assert captured["industry_snapshot_end_date"] == latest_trade_date
    assert captured["threshold_end_date"] == latest_trade_date
    assert captured["calculate_stock_score_end_date"] == latest_trade_date


def test_legacy_profile_bypasses_tradeability_hard_filter(selector: StockSelector, monkeypatch):
    latest_trade_date = _latest_trade_date()
    ts_code = _query_single_value(
        f"""
        SELECT ts_code
        FROM stock_daily
        WHERE trade_date = ? AND ({MAIN_BOARD_SQL})
        ORDER BY amount DESC
        LIMIT 1
        """,
        (latest_trade_date,),
    )
    if not ts_code:
        pytest.skip("no main-board symbol found for legacy profile test")

    stock_row = selector.db.query_one(
        "SELECT ts_code, name, industry, list_date FROM stock_basic WHERE ts_code = ?",
        (ts_code,),
    )
    if not stock_row:
        pytest.skip(f"stock_basic row missing for {ts_code}")

    original_profile = selector.strategy_profile
    selector.strategy_profile = "legacy"

    def _raise_if_called(*_args, **_kwargs):
        raise RuntimeError("assess_tradeability should not be called in legacy profile")

    monkeypatch.setattr(selector, "assess_tradeability", _raise_if_called)
    try:
        result = selector.calculate_stock_score(
            ts_code=stock_row["ts_code"],
            name=stock_row.get("name", ts_code),
            industry=stock_row.get("industry", ""),
            end_date=latest_trade_date,
            list_date=stock_row.get("list_date", ""),
        )
    finally:
        selector.strategy_profile = original_profile

    assert result is not None
    assert result["strategy_profile"] == "legacy"
    assert result["tradeability_penalty"] == 0.0
    assert result["short_cycle_score"] == 50.0
    assert result["score_breakdown"]["short_cycle_adjustment"] == 0.0


def test_legacy_opt_profile_uses_separate_weights_and_bypasses_tradeability(
    selector: StockSelector,
    monkeypatch,
):
    latest_trade_date = _latest_trade_date()
    ts_code = _query_single_value(
        f"""
        SELECT ts_code
        FROM stock_daily
        WHERE trade_date = ? AND ({MAIN_BOARD_SQL})
        ORDER BY amount DESC
        LIMIT 1
        """,
        (latest_trade_date,),
    )
    if not ts_code:
        pytest.skip("no main-board symbol found for legacy_opt profile test")

    stock_row = selector.db.query_one(
        "SELECT ts_code, name, industry, list_date FROM stock_basic WHERE ts_code = ?",
        (ts_code,),
    )
    if not stock_row:
        pytest.skip(f"stock_basic row missing for {ts_code}")

    original_profile = selector.strategy_profile
    original_weights = (
        selector.legacy_opt_trend_weight,
        selector.legacy_opt_momentum_weight,
        selector.legacy_opt_volume_weight,
        selector.legacy_opt_fundamental_weight,
        selector.legacy_opt_pullback_weight,
    )
    selector.strategy_profile = "legacy_opt"
    selector.legacy_opt_trend_weight = 0.41
    selector.legacy_opt_momentum_weight = 0.29
    selector.legacy_opt_volume_weight = 0.06
    selector.legacy_opt_fundamental_weight = 0.04
    selector.legacy_opt_pullback_weight = 0.16

    def _raise_if_called(*_args, **_kwargs):
        raise RuntimeError("assess_tradeability should not be called in legacy_opt profile")

    monkeypatch.setattr(selector, "assess_tradeability", _raise_if_called)
    try:
        result = selector.calculate_stock_score(
            ts_code=stock_row["ts_code"],
            name=stock_row.get("name", ts_code),
            industry=stock_row.get("industry", ""),
            end_date=latest_trade_date,
            list_date=stock_row.get("list_date", ""),
        )
        active_weights = selector._get_active_weights()
    finally:
        selector.strategy_profile = original_profile
        (
            selector.legacy_opt_trend_weight,
            selector.legacy_opt_momentum_weight,
            selector.legacy_opt_volume_weight,
            selector.legacy_opt_fundamental_weight,
            selector.legacy_opt_pullback_weight,
        ) = original_weights

    assert result is not None
    assert result["strategy_profile"] == "legacy_opt"
    assert result["tradeability_penalty"] == 0.0
    assert result["short_cycle_score"] == 50.0
    assert active_weights["trend"] == 0.41
    assert active_weights["momentum"] == 0.29
    assert active_weights["volume"] == 0.06
    assert active_weights["fundamental"] == 0.04
    assert active_weights["pullback"] == 0.16


def test_assess_tradeability_blocks_low_liquidity_symbol(selector: StockSelector):
    sql = f"""
        WITH ranked AS (
            SELECT
                ts_code,
                amount,
                ROW_NUMBER() OVER (PARTITION BY ts_code ORDER BY trade_date DESC) AS rn
            FROM stock_daily
            WHERE {MAIN_BOARD_SQL}
        )
        SELECT ts_code
        FROM (
            SELECT ts_code, AVG(amount) AS avg_amount_20, COUNT(*) AS sample_count
            FROM ranked
            WHERE rn <= 20
            GROUP BY ts_code
        )
        WHERE avg_amount_20 < ? AND sample_count >= 20
        ORDER BY avg_amount_20 ASC
        LIMIT 1
    """
    ts_code = _query_single_value(sql, (selector.min_avg_amount_20d,))
    if not ts_code:
        pytest.skip("no low-liquidity main-board symbol found in real data")

    df = selector.get_stock_daily_data(ts_code, days=60, end_date=_latest_trade_date())
    profile = selector.assess_tradeability(df)

    assert profile["filters"]["liquidity_pass"] is False
    assert profile["is_tradeable"] is False
    assert any(
        marker in profile["blocked_reasons"]
        for marker in ("近20日成交额不足", "杩?0鏃ユ垚浜ら涓嶈冻")
    )


def test_dynamic_tradeability_thresholds_available(selector: StockSelector):
    end_date = _latest_trade_date()
    thresholds = selector.get_tradeability_thresholds(end_date=end_date)

    assert thresholds.get("end_date") == end_date
    assert float(thresholds.get("min_avg_amount_20d", 0.0)) > 0
    assert int(thresholds.get("max_recent_limit_up_count_20d", 0)) >= 1
    assert float(thresholds.get("max_recent_return_20d", 0.0)) > 0
    assert float(thresholds.get("max_avg_amplitude_10d", 0.0)) > 0
    assert float(thresholds.get("max_latest_pct_chg", 0.0)) > 0
    assert thresholds.get("source") in {
        "dynamic",
        "static",
        "static_disabled",
        "static_fallback_no_data",
        "static_fallback_sample_small",
    }


def test_assess_tradeability_includes_applied_thresholds(selector: StockSelector):
    sql = f"""
        WITH ranked AS (
            SELECT
                ts_code,
                amount,
                ROW_NUMBER() OVER (PARTITION BY ts_code ORDER BY trade_date DESC) AS rn
            FROM stock_daily
            WHERE {MAIN_BOARD_SQL}
        )
        SELECT ts_code
        FROM (
            SELECT ts_code, AVG(amount) AS avg_amount_20
            FROM ranked
            WHERE rn <= 20
            GROUP BY ts_code
        )
        WHERE avg_amount_20 >= ?
        ORDER BY avg_amount_20 DESC
        LIMIT 1
    """
    ts_code = _query_single_value(sql, (selector.min_avg_amount_20d,))
    if not ts_code:
        pytest.skip("no main-board symbol found for threshold integration test")

    end_date = _latest_trade_date()
    thresholds = selector.get_tradeability_thresholds(end_date=end_date)
    df = selector.get_stock_daily_data(ts_code, days=60, end_date=end_date)
    profile = selector.assess_tradeability(df, dynamic_thresholds=thresholds)
    applied = profile.get("applied_thresholds", {})

    assert applied
    assert "max_latest_pct_chg" in applied
    assert float(applied["min_avg_amount_20d"]) > 0


def test_assess_tradeability_exposes_new_liquidity_metrics(selector: StockSelector):
    sql = f"""
        WITH ranked AS (
            SELECT
                ts_code,
                amount,
                ROW_NUMBER() OVER (PARTITION BY ts_code ORDER BY trade_date DESC) AS rn
            FROM stock_daily
            WHERE {MAIN_BOARD_SQL}
        )
        SELECT ts_code
        FROM (
            SELECT ts_code, AVG(amount) AS avg_amount_20
            FROM ranked
            WHERE rn <= 20
            GROUP BY ts_code
        )
        WHERE avg_amount_20 >= ?
        ORDER BY avg_amount_20 DESC
        LIMIT 1
    """
    ts_code = _query_single_value(sql, (selector.min_avg_amount_20d,))
    if not ts_code:
        pytest.skip("no main-board symbol found for liquidity metric test")

    end_date = _latest_trade_date()
    thresholds = selector.get_tradeability_thresholds(end_date=end_date)
    df = selector.get_stock_daily_data(ts_code, days=60, end_date=end_date)
    profile = selector.assess_tradeability(df, dynamic_thresholds=thresholds)

    assert "recent_amount_5" in profile
    assert "amount_ratio_5_20" in profile
    assert "down_shock_days_10" in profile
    assert "one_word_limit_up_days_20" in profile
    assert profile["recent_amount_5"] >= 0
    assert profile["amount_ratio_5_20"] >= 0


def test_calculate_stock_score_returns_new_short_cycle_fields(selector: StockSelector):
    sql = f"""
        WITH ranked AS (
            SELECT
                ts_code,
                amount,
                ROW_NUMBER() OVER (PARTITION BY ts_code ORDER BY trade_date DESC) AS rn
            FROM stock_daily
            WHERE {MAIN_BOARD_SQL}
        )
        SELECT ts_code
        FROM (
            SELECT ts_code, AVG(amount) AS avg_amount_20
            FROM ranked
            WHERE rn <= 20
            GROUP BY ts_code
        )
        WHERE avg_amount_20 >= ?
        ORDER BY avg_amount_20 DESC
        LIMIT 80
    """
    db_path = _get_db_path()
    conn = sqlite3.connect(str(db_path))
    try:
        candidate_codes = [row[0] for row in conn.execute(sql, (selector.min_avg_amount_20d * 2,)).fetchall()]
    finally:
        conn.close()

    latest_trade_date = _latest_trade_date()
    result = None
    for ts_code in candidate_codes:
        stock_row = selector.db.query_one(
            "SELECT name, industry FROM stock_basic WHERE ts_code = ?",
            (ts_code,),
        )
        if not stock_row:
            continue
        result = selector.calculate_stock_score(
            ts_code=ts_code,
            name=stock_row.get("name", ts_code),
            industry=stock_row.get("industry", ""),
            end_date=latest_trade_date,
        )
        if result:
            break

    if result is None:
        pytest.skip("no tradeable main-board symbol found for score integration test")

    assert 3 <= result["holding_window_days"] <= 5
    assert "short_cycle_score" in result
    assert "tradeability_score" in result
    assert "tradeability_detail" in result
    assert "tradeability_thresholds" in result
    assert "short_cycle_detail" in result
    assert "short_cycle_adjustment" in result["score_breakdown"]
    assert result["tradeability_score"] >= 60
    assert 0 <= result["total_score"] <= 100


def test_short_cycle_detail_contains_flow_and_slope_metrics(selector: StockSelector):
    sql = f"""
        WITH ranked AS (
            SELECT
                ts_code,
                amount,
                ROW_NUMBER() OVER (PARTITION BY ts_code ORDER BY trade_date DESC) AS rn
            FROM stock_daily
            WHERE {MAIN_BOARD_SQL}
        )
        SELECT ts_code
        FROM (
            SELECT ts_code, AVG(amount) AS avg_amount_20
            FROM ranked
            WHERE rn <= 20
            GROUP BY ts_code
        )
        WHERE avg_amount_20 >= ?
        ORDER BY avg_amount_20 DESC
        LIMIT 60
    """
    db_path = _get_db_path()
    conn = sqlite3.connect(str(db_path))
    try:
        candidate_codes = [row[0] for row in conn.execute(sql, (selector.min_avg_amount_20d * 2,)).fetchall()]
    finally:
        conn.close()

    latest_trade_date = _latest_trade_date()
    result = None
    for ts_code in candidate_codes:
        stock_row = selector.db.query_one(
            "SELECT name, industry FROM stock_basic WHERE ts_code = ?",
            (ts_code,),
        )
        if not stock_row:
            continue
        result = selector.calculate_stock_score(
            ts_code=ts_code,
            name=stock_row.get("name", ts_code),
            industry=stock_row.get("industry", ""),
            end_date=latest_trade_date,
        )
        if result:
            break

    if result is None:
        pytest.skip("no tradeable main-board symbol found for short-cycle detail test")

    detail = result.get("short_cycle_detail", {})
    assert "flow_score" in detail
    assert "return_3" in detail
    assert "amount_ratio_5_20" in detail
    assert "ma5_slope_3" in detail
    assert "ma10_slope_3" in detail


def test_dynamic_industry_strength_snapshot_available(selector: StockSelector):
    latest_trade_date = _latest_trade_date()
    snapshot = selector.get_dynamic_industry_strength(end_date=latest_trade_date, top_n=10)

    assert snapshot
    assert all("industry" in row for row in snapshot)
    assert all("heat_score" in row for row in snapshot)
    assert all(0 <= float(row["heat_score"]) <= 100 for row in snapshot)


def test_fundamental_factor_contains_dynamic_industry_fields(selector: StockSelector):
    latest_trade_date = _latest_trade_date()
    snapshot = selector.get_dynamic_industry_strength(end_date=latest_trade_date, top_n=1)
    if not snapshot:
        pytest.skip("dynamic industry snapshot is empty")

    top_industry = snapshot[0]["industry"]
    stock_row = selector.db.query_one(
        """
        SELECT ts_code, name, industry, list_date
        FROM stock_basic
        WHERE industry = ? AND (
            ts_code LIKE '600%.SH' OR ts_code LIKE '601%.SH' OR ts_code LIKE '603%.SH' OR ts_code LIKE '605%.SH'
            OR ts_code LIKE '000%.SZ' OR ts_code LIKE '001%.SZ' OR ts_code LIKE '002%.SZ' OR ts_code LIKE '003%.SZ'
        )
        LIMIT 1
        """,
        (top_industry,),
    )
    if not stock_row:
        pytest.skip(f"no main-board stock found in industry {top_industry}")

    score, detail = selector.calculate_fundamental_factor(
        ts_code=stock_row["ts_code"],
        end_date=latest_trade_date,
        name=stock_row.get("name"),
        industry=stock_row.get("industry"),
        list_date=stock_row.get("list_date"),
    )

    dynamic = detail.get("industry_dynamic", {})
    assert score >= 0
    assert dynamic.get("enabled") is True
    assert dynamic.get("end_date") == latest_trade_date
    assert "industry_heat_score" in dynamic
    assert "industry_heat_level" in dynamic
