# -*- coding: utf-8 -*-
"""突破选股策略与主流程集成冒烟测试（无交互、不依赖完整行情）"""

import json

import pytest


def test_get_breakout_params_for_backtest_relaxed():
    """放宽预设：选股更宽，买点相关字段与 baseline 一致。"""
    from src.modules.breakout_strategy import get_breakout_params_for_backtest

    b = get_breakout_params_for_backtest("baseline", True)
    r = get_breakout_params_for_backtest("selection_relaxed_v1", True)
    assert b.rs_quantile_min > r.rs_quantile_min
    assert b.min_signal_score > r.min_signal_score
    assert b.top_k < r.top_k
    assert b.breakout_buffer == r.breakout_buffer
    assert b.volume_confirm_ratio == r.volume_confirm_ratio


def test_get_breakout_params_win_rate_priority():
    """胜率优先：选股同 baseline，买点更严。"""
    from src.modules.breakout_strategy import get_breakout_params_for_backtest

    b = get_breakout_params_for_backtest("baseline", True)
    w = get_breakout_params_for_backtest("win_rate_priority", True)
    assert w.rs_quantile_min == b.rs_quantile_min
    assert w.min_signal_score == b.min_signal_score
    assert w.top_k == b.top_k
    assert w.volume_confirm_ratio > b.volume_confirm_ratio
    assert w.volume_normal_ratio > b.volume_normal_ratio
    assert w.breakout_buffer > b.breakout_buffer


def test_get_breakout_params_buy_tuning_v1_stricter_than_win_rate():
    """buy_tuning_v1：选股同 baseline，买点比 win_rate_priority 更严。"""
    from src.modules.breakout_strategy import get_breakout_params_for_backtest

    b = get_breakout_params_for_backtest("baseline", True)
    w = get_breakout_params_for_backtest("win_rate_priority", True)
    t = get_breakout_params_for_backtest("buy_tuning_v1", True)
    assert t.rs_quantile_min == b.rs_quantile_min
    assert t.top_k == b.top_k
    assert t.breakout_buffer >= w.breakout_buffer
    assert t.breakout_max_chase <= w.breakout_max_chase
    assert t.volume_confirm_ratio >= w.volume_confirm_ratio
    assert t.volume_normal_ratio >= w.volume_normal_ratio
    assert t.max_intraday_gain <= w.max_intraday_gain


def test_get_breakout_params_wide_pool_strict_entry_v1():
    """宽池严买点：选股同 relaxed，买点同 win_rate_priority。"""
    from src.modules.breakout_strategy import get_breakout_params_for_backtest

    r = get_breakout_params_for_backtest("selection_relaxed_v1", True)
    w = get_breakout_params_for_backtest("win_rate_priority", True)
    c = get_breakout_params_for_backtest("wide_pool_strict_entry_v1", True)
    assert c.rs_quantile_min == r.rs_quantile_min
    assert c.min_signal_score == r.min_signal_score
    assert c.top_k == r.top_k
    assert c.atr_quantile_max == r.atr_quantile_max
    assert c.box_max_range == r.box_max_range
    assert c.breakout_buffer == w.breakout_buffer
    assert c.breakout_max_chase == w.breakout_max_chase
    assert c.volume_confirm_ratio == w.volume_confirm_ratio
    assert c.volume_normal_ratio == w.volume_normal_ratio
    assert c.max_intraday_gain == w.max_intraday_gain


def test_get_breakout_params_wide_pool_strict_entry_v2():
    """宽池最严买点：选股同 relaxed，买点同 buy_tuning_v1。"""
    from src.modules.breakout_strategy import get_breakout_params_for_backtest

    r = get_breakout_params_for_backtest("selection_relaxed_v1", True)
    t = get_breakout_params_for_backtest("buy_tuning_v1", True)
    c = get_breakout_params_for_backtest("wide_pool_strict_entry_v2", True)
    assert c.rs_quantile_min == r.rs_quantile_min
    assert c.min_signal_score == r.min_signal_score
    assert c.top_k == r.top_k
    assert c.atr_quantile_max == r.atr_quantile_max
    assert c.box_max_range == r.box_max_range
    assert c.breakout_buffer == t.breakout_buffer
    assert c.breakout_max_chase == t.breakout_max_chase
    assert c.volume_confirm_ratio == t.volume_confirm_ratio
    assert c.volume_normal_ratio == t.volume_normal_ratio
    assert c.max_intraday_gain == t.max_intraday_gain


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


def test_breakout_high_score_weak_confirm_guard_default_off():
    """默认关闭灰度保护：高分但弱确认仍按原逻辑输出 B 级。"""
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
        signal_score=82.0,
        score_detail="",
    )
    row = pd.Series(
        {
            "ts_code": "000001.SZ",
            "trade_date": pd.Timestamp("2024-01-02"),
            "open": 9.9,
            "high": 10.1,
            "low": 9.8,
            "close": 10.1,
            "vol": 1_100_000.0,
            "vol_ma20": 1_000_000.0,
        }
    )
    sigs = st.confirm_breakout_daily([item], {"000001.SZ": row})
    assert len(sigs) == 1
    assert sigs[0].signal_grade == "B"


def test_breakout_high_score_weak_confirm_guard_filters_daily():
    """开启灰度保护：高分但量能弱于阈值时过滤。"""
    from src.modules.breakout_strategy import BreakoutParams, WatchItem, BreakoutStrategy
    from src.core.config import ConfigManager
    from src.core.database import DatabaseManager
    import pandas as pd

    p = BreakoutParams(
        enable_high_score_weak_confirm_guard=True,
        high_score_weak_confirm_score_min=80.0,
        high_score_weak_confirm_volume_min=1.35,
    )
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
        signal_score=82.0,
        score_detail="",
    )
    row = pd.Series(
        {
            "ts_code": "000001.SZ",
            "trade_date": pd.Timestamp("2024-01-02"),
            "open": 9.9,
            "high": 10.1,
            "low": 9.8,
            "close": 10.1,
            "vol": 1_100_000.0,
            "vol_ma20": 1_000_000.0,
        }
    )
    assert st.confirm_breakout_daily([item], {"000001.SZ": row}) == []


def test_breakout_high_score_weak_confirm_guard_keeps_strong_volume():
    """开启灰度保护：高分且真实放量的 A 级仍保留。"""
    from src.modules.breakout_strategy import BreakoutParams, WatchItem, BreakoutStrategy
    from src.core.config import ConfigManager
    from src.core.database import DatabaseManager
    import pandas as pd

    p = BreakoutParams(
        enable_high_score_weak_confirm_guard=True,
        high_score_weak_confirm_score_min=80.0,
        high_score_weak_confirm_volume_min=1.35,
    )
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
        signal_score=82.0,
        score_detail="",
    )
    row = pd.Series(
        {
            "ts_code": "000001.SZ",
            "trade_date": pd.Timestamp("2024-01-02"),
            "open": 9.9,
            "high": 10.1,
            "low": 9.8,
            "close": 10.1,
            "vol": 1_500_000.0,
            "vol_ma20": 1_000_000.0,
        }
    )
    sigs = st.confirm_breakout_daily([item], {"000001.SZ": row})
    assert len(sigs) == 1
    assert sigs[0].signal_grade == "A"


def test_breakout_market_ret5_median_guard_falls_back_without_index_data():
    """指数缺失时，开启市场弱势保护会使用全市场5日中位收益兜底禁开。"""
    from src.modules.breakout_strategy import BreakoutParams, BreakoutStrategy
    from src.core.config import ConfigManager
    from src.core.database import DatabaseManager
    import pandas as pd

    trade_date = pd.Timestamp("2024-01-02")
    features = pd.DataFrame(
        {
            "ts_code": [f"600{i:03d}.SH" for i in range(80)],
            "trade_date": [trade_date] * 80,
            "ret_1d": [0.01] * 80,
            "ret5": [-0.02] * 80,
        }
    )

    disabled = BreakoutStrategy(
        db=DatabaseManager(ConfigManager()),
        params=BreakoutParams(enable_market_ret5_median_guard=False),
    )
    assert disabled._market_gate(features, "20240102") == (
        disabled.params.min_signal_score,
        disabled.params.top_k,
    )

    enabled = BreakoutStrategy(
        db=DatabaseManager(ConfigManager()),
        params=BreakoutParams(
            enable_market_ret5_median_guard=True,
            market_ret5_median_stop=-0.01,
        ),
    )
    assert enabled._market_gate(features, "20240102") == (999.0, 0)


def test_src_modules_exports_breakout():
    import src.modules as m

    assert m.BreakoutStrategy is not None
    assert m.BreakoutParams is not None
    assert m.breakout_selector_menu is not None
    assert m.wide_breakout_selector_menu is not None
    assert m.build_breakout_strategy_from_config is not None
    assert m.build_wide_breakout_strategy_from_config is not None
    assert m.resolve_breakout_preset_from_config is not None


def test_resolve_breakout_preset_from_config():
    from src.core.config import ConfigManager
    from src.modules.breakout_strategy import resolve_breakout_preset_from_config

    assert resolve_breakout_preset_from_config(None) == "baseline"

    cm = ConfigManager()
    cm.set("stock_selection.breakout.params_preset", "nope_unknown", save=False)
    assert resolve_breakout_preset_from_config(cm) == "baseline"

    cm.set("stock_selection.breakout.params_preset", "win_rate_priority", save=False)
    assert resolve_breakout_preset_from_config(cm) == "win_rate_priority"

    cm.set("stock_selection.breakout.params_preset", "wide_pool_strict_entry_v1", save=False)
    assert resolve_breakout_preset_from_config(cm) == "wide_pool_strict_entry_v1"

    cm.set("stock_selection.breakout.params_preset", "wide_pool_strict_entry_v2", save=False)
    assert resolve_breakout_preset_from_config(cm) == "wide_pool_strict_entry_v2"


def test_build_breakout_strategy_from_config_reads_high_score_guard():
    from src.core.config import ConfigManager
    from src.core.database import DatabaseManager
    from src.modules.breakout_strategy import build_breakout_strategy_from_config

    cm = ConfigManager()
    cm.set("stock_selection.breakout.params_preset", "win_rate_priority", save=False)
    cm.set("stock_selection.breakout.high_score_weak_confirm_guard.enabled", True, save=False)
    cm.set("stock_selection.breakout.high_score_weak_confirm_guard.score_min", 81.0, save=False)
    cm.set("stock_selection.breakout.high_score_weak_confirm_guard.volume_min", 1.4, save=False)

    st = build_breakout_strategy_from_config(DatabaseManager(cm), cm)
    assert st.params.enable_high_score_weak_confirm_guard is True
    assert st.params.high_score_weak_confirm_score_min == 81.0
    assert st.params.high_score_weak_confirm_volume_min == 1.4


def test_build_breakout_strategy_from_config_reads_market_ret5_guard():
    from src.core.config import ConfigManager
    from src.core.database import DatabaseManager
    from src.modules.breakout_strategy import build_breakout_strategy_from_config

    cm = ConfigManager()
    cm.set("stock_selection.breakout.params_preset", "win_rate_priority", save=False)
    cm.set("stock_selection.breakout.market_ret5_median_guard.enabled", "true", save=False)
    cm.set("stock_selection.breakout.market_ret5_median_guard.stop", -0.012, save=False)

    st = build_breakout_strategy_from_config(DatabaseManager(cm), cm)
    assert st.params.enable_market_ret5_median_guard is True
    assert st.params.market_ret5_median_stop == -0.012


def test_build_breakout_strategy_from_config_reads_exit_guard():
    from src.core.config import ConfigManager
    from src.core.database import DatabaseManager
    from src.modules.breakout_strategy import build_breakout_strategy_from_config

    cm = ConfigManager()
    cm.set("stock_selection.breakout.params_preset", "win_rate_priority", save=False)
    cm.set("stock_selection.breakout.exit_guard.max_hold_days", 3, save=False)
    cm.set("stock_selection.breakout.exit_guard.trailing_enabled", "true", save=False)
    cm.set("stock_selection.breakout.exit_guard.trail_arm_pct", 0.04, save=False)
    cm.set("stock_selection.breakout.exit_guard.trailing_stop_pct", 0.025, save=False)
    cm.set("stock_selection.breakout.exit_guard.fixed_stop_loss_pct", -0.045, save=False)
    cm.set("stock_selection.breakout.exit_guard.use_weakness_rules", False, save=False)
    cm.set("stock_selection.breakout.exit_guard.grade_overrides.A.max_hold_days", 4, save=False)
    cm.set("stock_selection.breakout.exit_guard.grade_overrides.A.trail_arm_pct", 0.045, save=False)

    st = build_breakout_strategy_from_config(DatabaseManager(cm), cm)
    assert st.params.max_hold_days == 3
    assert st.params.enable_trailing_exit_guard is True
    assert st.params.exit_trail_arm_pct == 0.04
    assert st.params.exit_trailing_stop_pct == 0.025
    assert st.params.exit_fixed_stop_loss_pct == -0.045
    assert st.params.exit_use_weakness_rules is False
    assert st.params.exit_grade_overrides["A"]["max_hold_days"] == 4
    assert st.params.exit_grade_overrides["A"]["trail_arm_pct"] == 0.045


def test_build_wide_breakout_strategy_from_config_reads_dedicated_exit_guard():
    from src.core.config import ConfigManager
    from src.core.database import DatabaseManager
    from src.modules.breakout_strategy import build_wide_breakout_strategy_from_config

    cm = ConfigManager()
    cm.set("stock_selection.breakout.params_preset", "baseline", save=False)
    cm.set("stock_selection.wide_breakout.exit_guard.max_hold_days", 3, save=False)
    cm.set("stock_selection.wide_breakout.exit_guard.trailing_enabled", True, save=False)
    cm.set("stock_selection.wide_breakout.exit_guard.trail_arm_pct", 0.04, save=False)
    cm.set("stock_selection.wide_breakout.exit_guard.trailing_stop_pct", 0.025, save=False)
    cm.set("stock_selection.wide_breakout.exit_guard.fixed_stop_loss_pct", -0.045, save=False)
    cm.set("stock_selection.wide_breakout.exit_guard.use_weakness_rules", False, save=False)
    cm.set("stock_selection.wide_breakout.exit_guard.grade_overrides.A.max_hold_days", 4, save=False)
    cm.set("stock_selection.wide_breakout.exit_guard.grade_overrides.B.max_hold_days", 3, save=False)

    st = build_wide_breakout_strategy_from_config(DatabaseManager(cm), cm)

    assert st.params.rs_quantile_min == 0.78
    assert st.params.min_signal_score == 58.0
    assert st.params.top_k == 28
    assert st.params.breakout_buffer == 0.004
    assert st.params.volume_confirm_ratio == 1.42
    assert st.params.enable_trailing_exit_guard is True
    assert st.params.exit_fixed_stop_loss_pct == -0.045
    assert st.params.exit_use_weakness_rules is False
    assert st.resolve_exit_plan("A")["max_hold_days"] == 4
    assert st.resolve_exit_plan("B")["max_hold_days"] == 3


def test_build_wide_breakout_strategy_from_config_reads_dedicated_entry_guard():
    from src.core.config import ConfigManager
    from src.core.database import DatabaseManager
    from src.modules.breakout_strategy import build_wide_breakout_strategy_from_config

    cm = ConfigManager()
    cm.set("stock_selection.wide_breakout.high_score_weak_confirm_guard.enabled", "true", save=False)
    cm.set("stock_selection.wide_breakout.high_score_weak_confirm_guard.score_min", 82.0, save=False)
    cm.set("stock_selection.wide_breakout.high_score_weak_confirm_guard.volume_min", 1.45, save=False)

    st = build_wide_breakout_strategy_from_config(DatabaseManager(cm), cm)

    assert st.params.enable_high_score_weak_confirm_guard is True
    assert st.params.high_score_weak_confirm_score_min == 82.0
    assert st.params.high_score_weak_confirm_volume_min == 1.45


def test_breakout_check_hold_weakness_trailing_exit_guard():
    from src.modules.breakout_strategy import BreakoutParams, BreakoutStrategy
    from src.core.config import ConfigManager
    from src.core.database import DatabaseManager
    import pandas as pd

    st = BreakoutStrategy(
        db=DatabaseManager(ConfigManager()),
        params=BreakoutParams(
            enable_trailing_exit_guard=True,
            exit_trail_arm_pct=0.04,
            exit_trailing_stop_pct=0.025,
            exit_fixed_stop_loss_pct=-0.045,
            exit_use_weakness_rules=False,
            max_hold_days=3,
        ),
    )
    daily = pd.DataFrame(
        [
            {"close": 10.3, "high": 10.5, "low": 10.1, "ma5": 9.8},
            {"close": 10.2, "high": 10.55, "low": 10.0, "ma5": 9.9},
        ]
    )

    should_exit, reason = st.check_hold_weakness(
        "000001.SZ",
        daily,
        stop_loss=9.5,
        hold_days=2,
        entry_price=10.0,
    )

    assert should_exit is True
    assert "移动止盈触发" in reason


def test_breakout_check_hold_weakness_can_disable_ma_weakness_rules():
    from src.modules.breakout_strategy import BreakoutParams, BreakoutStrategy
    from src.core.config import ConfigManager
    from src.core.database import DatabaseManager
    import pandas as pd

    st = BreakoutStrategy(
        db=DatabaseManager(ConfigManager()),
        params=BreakoutParams(
            exit_use_weakness_rules=False,
            exit_fixed_stop_loss_pct=-0.045,
            max_hold_days=3,
        ),
    )
    daily = pd.DataFrame(
        [
            {"close": 10.2, "high": 10.3, "low": 10.1, "ma5": 10.0},
            {"close": 9.9, "high": 10.1, "low": 9.8, "ma5": 10.0},
        ]
    )

    should_exit, reason = st.check_hold_weakness(
        "000001.SZ",
        daily,
        stop_loss=9.0,
        hold_days=2,
        entry_price=10.0,
    )

    assert should_exit is False
    assert reason == ""


def test_breakout_check_hold_weakness_uses_grade_override_max_hold():
    from src.modules.breakout_strategy import BreakoutParams, BreakoutStrategy
    from src.core.config import ConfigManager
    from src.core.database import DatabaseManager
    import pandas as pd

    st = BreakoutStrategy(
        db=DatabaseManager(ConfigManager()),
        params=BreakoutParams(
            enable_trailing_exit_guard=True,
            max_hold_days=3,
            exit_fixed_stop_loss_pct=-0.045,
            exit_use_weakness_rules=False,
            exit_grade_overrides={"A": {"max_hold_days": 4}},
        ),
    )
    daily = pd.DataFrame(
        [
            {"close": 10.1, "high": 10.2, "low": 10.0, "ma5": 9.9},
            {"close": 10.2, "high": 10.3, "low": 10.1, "ma5": 10.0},
            {"close": 10.3, "high": 10.4, "low": 10.2, "ma5": 10.1},
        ]
    )

    should_exit, _ = st.check_hold_weakness(
        "000001.SZ",
        daily,
        stop_loss=9.0,
        hold_days=3,
        entry_price=10.0,
        signal_grade="A",
    )
    assert should_exit is False

    should_exit, reason = st.check_hold_weakness(
        "000001.SZ",
        daily,
        stop_loss=9.0,
        hold_days=3,
        entry_price=10.0,
        signal_grade="B",
    )
    assert should_exit is True
    assert "时间止损" in reason


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
    exit_plan = {"by_grade": {"A": {"max_hold_days": 4}, "B": {"max_hold_days": 3}}}
    n = merge_breakout_watchlist_to_candidate_cache(
        [item], "20240103", project_root=tmp_path, exit_plan=exit_plan
    )
    assert n == 1
    data = json.loads(pool_path.read_text(encoding="utf-8"))
    cands = data["candidates"]
    profiles = {x.get("strategy_profile") for x in cands}
    assert "secondary_launch" in profiles
    assert "breakout" in profiles
    assert sum(1 for x in cands if x.get("strategy_profile") == "breakout") == 1
    assert any(x.get("name") == "保留股" for x in cands)
    breakout = next(x for x in cands if x.get("strategy_profile") == "breakout")
    assert breakout["exit_plan"]["by_grade"]["A"]["max_hold_days"] == 4


def test_merge_wide_breakout_candidate_cache_preserves_breakout(tmp_path):
    """宽进突破写入时保留原 breakout 条目。"""
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
                        "symbol": "600000",
                        "ts_code": "600000.SH",
                        "name": "原突破",
                        "strategy_profile": "breakout",
                        "score": 70.0,
                    },
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    item = WatchItem(
        ts_code="000001.SZ",
        name="宽进",
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
    n = merge_breakout_watchlist_to_candidate_cache(
        [item],
        "20240103",
        project_root=tmp_path,
        strategy_profile="wide_breakout",
        strategy_name="wide_breakout_watchlist",
        level_label="宽进突破观察池",
        source="wide_breakout_strategy",
    )
    assert n == 1
    data = json.loads(pool_path.read_text(encoding="utf-8"))
    cands = data["candidates"]
    profiles = {x.get("strategy_profile") for x in cands}
    assert "breakout" in profiles
    assert "wide_breakout" in profiles
    assert sum(1 for x in cands if x.get("strategy_profile") == "wide_breakout") == 1
