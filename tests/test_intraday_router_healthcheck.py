# -*- coding: utf-8 -*-
"""盘中买点路由与 strategy_profile 归一化测试。"""


def test_normalize_strategy_profile_includes_wide_breakout_and_strong_start():
    from src.modules.enhanced_hybrid_system import EnhancedHybridSystem

    assert EnhancedHybridSystem._normalize_strategy_profile("wide_breakout") == "wide_breakout"
    assert EnhancedHybridSystem._normalize_strategy_profile("strong_start") == "strong_start"
    assert EnhancedHybridSystem._normalize_strategy_profile("unknown_xyz") == "legacy"


def test_run_intraday_buy_router_healthcheck_all_ok():
    from src.modules.enhanced_hybrid_system import EnhancedHybridSystem

    system = EnhancedHybridSystem()
    rows = system.run_intraday_buy_router_healthcheck()
    assert len(rows) == 7
    assert all(r.get("ok") for r in rows), rows
