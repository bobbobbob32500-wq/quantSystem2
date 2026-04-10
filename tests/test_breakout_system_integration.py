# -*- coding: utf-8 -*-
"""突破选股策略与主流程集成冒烟测试（无交互、不依赖完整行情）"""

import json

import pytest


def test_breakout_strategy_core_api():
    from src.modules.breakout_strategy import (
        BreakoutParams,
        BreakoutStrategy,
        WatchItem,
    )
    from src.core.config import ConfigManager
    from src.core.database import DatabaseManager

    p = BreakoutParams()
    assert p.min_amt_ma20 == 8e4
    assert p.volume_confirm_ratio == 1.2
    assert abs(p.breakout_buffer - 0.002) < 1e-9

    db = DatabaseManager(ConfigManager())
    st = BreakoutStrategy(db=db, params=p)
    assert st.params is p

    # bars_dict_for_trade_date 对空表不报错
    import pandas as pd

    empty = pd.DataFrame({"trade_date": [], "ts_code": []})
    assert st.bars_dict_for_trade_date(empty, "20200101") == {}


def test_breakout_confirm_daily_contract():
    """确认日线接口：观察池 + 下一日截面 → 信号列表"""
    from src.modules.breakout_strategy import BreakoutParams, WatchItem, BreakoutStrategy
    from src.core.config import ConfigManager
    from src.core.database import DatabaseManager
    import pandas as pd

    p = BreakoutParams()
    st = BreakoutStrategy(db=DatabaseManager(ConfigManager()), params=p)
    item = WatchItem(
        ts_code="000001.SZ",
        name="测试",
        watch_date="20240101",
        close=10.0,
        pivot=10.0,
        trigger_price=10.02,
        stop_loss=9.0,
        atr14=0.2,
        rs20=5.0,
        rs20_xsec_q=0.85,
        atr_ratio_q60=0.3,
        box_range=5.0,
        ma20=10.0,
        ma60=9.5,
        ma120=9.0,
        signal_score=70.0,
        score_detail="",
    )
    trigger = 10.0 * (1 + p.breakout_buffer)
    row = pd.Series(
        {
            "ts_code": "000001.SZ",
            "trade_date": pd.Timestamp("2024-01-02"),
            "open": 9.9,
            "high": max(trigger, 9.95) + 0.05,
            "low": 9.8,
            "close": 10.1,
            "vol": 1_000_000.0,
            "vol_ma20": 500_000.0,
        }
    )
    sigs = st.confirm_breakout_daily([item], {"000001.SZ": row})
    assert len(sigs) == 1
    assert sigs[0].signal_grade == "A"
    assert sigs[0].volume_ratio >= p.volume_confirm_ratio


def test_src_modules_exports_breakout():
    import src.modules as m

    assert m.BreakoutStrategy is not None
    assert m.BreakoutParams is not None
    assert m.breakout_selector_menu is not None


def test_backtest_menu_has_breakout_runner():
    from src.modules.backtest_menu import BacktestMenu
    from pathlib import Path

    assert hasattr(BacktestMenu, "_run_breakout_strategy_backtest")
    root = Path(__file__).resolve().parents[1]
    assert (root / "scripts" / "run_breakout_backtest.py").is_file()


def test_merge_breakout_candidate_cache_preserves_other_strategies(tmp_path):
    """突破写入候选池时保留非 breakout 条目。"""
    from src.modules.breakout_selector_menu import merge_breakout_watchlist_to_candidate_cache
    from src.modules.breakout_strategy import WatchItem

    cache_dir = tmp_path / "data" / "cache"
    cache_dir.mkdir(parents=True)
    pool_path = cache_dir / "candidate_pool.json"
    pool_path.write_text(
        json.dumps(
            {
                "date": "20240101",
                "candidates": [
                    {
                        "symbol": "999999",
                        "ts_code": "999999.SH",
                        "name": "保留股",
                        "score": 50.0,
                        "strategy_profile": "secondary_launch",
                    },
                    {
                        "symbol": "888888",
                        "strategy_profile": "breakout",
                        "score": 40.0,
                    },
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    item = WatchItem(
        ts_code="000001.SZ",
        name="新建",
        watch_date="20240103",
        close=10.0,
        pivot=9.9,
        trigger_price=10.0,
        stop_loss=9.0,
        atr14=0.1,
        rs20=1.0,
        rs20_xsec_q=0.9,
        atr_ratio_q60=0.2,
        box_range=3.0,
        ma20=10.0,
        ma60=9.0,
        ma120=8.0,
        signal_score=72.0,
        score_detail="",
        industry="银行",
    )
    n = merge_breakout_watchlist_to_candidate_cache([item], "20240103", project_root=tmp_path)
    assert n == 1
    data = json.loads(pool_path.read_text(encoding="utf-8"))
    cands = data["candidates"]
    profiles = {x.get("strategy_profile") for x in cands}
    assert "secondary_launch" in profiles
    assert "breakout" in profiles
    assert sum(1 for x in cands if x.get("strategy_profile") == "breakout") == 1
    assert any(x.get("name") == "保留股" for x in cands)
