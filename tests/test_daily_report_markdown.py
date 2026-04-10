# -*- coding: utf-8 -*-
"""Formatting tests for daily report markdown output."""

from __future__ import annotations

from src.modules.daily_report import DailyReportGenerator


def _build_generator() -> DailyReportGenerator:
    return DailyReportGenerator.__new__(DailyReportGenerator)


def test_markdown_contains_dynamic_thresholds_and_top_stocks():
    generator = _build_generator()
    result = {
        "report_date": "2026-03-28",
        "report_time": "2026-03-28 09:00:00",
        "market_analysis": {
            "total_score": 67.5,
            "trend_score": 68.0,
            "width_score": 62.0,
            "volume_score": 59.0,
            "suggestion": "轻仓试错，优先强势行业",
        },
        "stock_selection": [
            {
                "ts_code": "000001.SZ",
                "name": "平安银行",
                "total_score": 78.3,
                "level": "推荐",
                "industry": "银行",
                "short_cycle_score": 71.5,
                "tradeability_score": 84.1,
            }
        ],
        "stock_selection_meta": {
            "selection_end_date": "20260327",
            "tradeability_thresholds": {
                "source": "dynamic",
                "sample_size": 4200,
                "min_avg_amount_20d": 120000.0,
                "max_recent_limit_up_count_20d": 2,
                "max_recent_return_20d": 24.5,
                "max_avg_amplitude_10d": 6.2,
                "max_latest_pct_chg": 8.1,
            },
            "industry_snapshot": [
                {"industry": "电力", "heat_score": 76.3},
                {"industry": "有色金属", "heat_score": 72.4},
                {"industry": "机械设备", "heat_score": 69.8},
            ],
        },
        "hold_analysis": {
            "hold_count": 1,
            "total_profit": 1234.5,
            "holds": [],
        },
    }

    markdown = generator.format_markdown_report(result)
    assert "盘前选股TOP10" in markdown
    assert "盘前动态门槛" in markdown
    assert "20日均成交额" in markdown
    assert "000001.SZ 平安银行" in markdown
    assert "行业热度TOP3" in markdown


def test_markdown_has_empty_stock_fallback():
    generator = _build_generator()
    result = {
        "report_date": "2026-03-28",
        "report_time": "2026-03-28 09:00:00",
        "market_analysis": {"total_score": 39.0, "suggestion": "谨慎观望"},
        "stock_selection": [],
        "stock_selection_meta": {
            "selection_end_date": "20260327",
            "tradeability_thresholds": {
                "source": "static_fallback_sample_small",
                "sample_size": 50,
                "min_avg_amount_20d": 100000.0,
                "max_recent_limit_up_count_20d": 2,
                "max_recent_return_20d": 25.0,
                "max_avg_amplitude_10d": 6.5,
                "max_latest_pct_chg": 8.5,
            },
        },
        "hold_analysis": {"hold_count": 0, "total_profit": 0},
    }

    markdown = generator.format_markdown_report(result)
    assert "盘前选股TOP10" in markdown
    assert "当日未筛选出满足门槛的标的" in markdown
    assert "门槛来源" in markdown


def test_markdown_includes_feedback_snapshot_section():
    generator = _build_generator()
    result = {
        "report_date": "2026-03-28",
        "report_time": "2026-03-28 09:00:00",
        "market_analysis": {},
        "stock_selection": [],
        "stock_selection_meta": {},
        "hold_analysis": {"hold_count": 0, "total_profit": 0},
        "feedback_summary": {
            "start_date": "20260201",
            "end_date": "20260327",
            "recommendation_detail_count": 200,
            "signal_detail_count": 80,
            "pre_market_best": {
                "horizon": 2,
                "win_rate": 0.52,
                "mean_net_return": 0.008,
            },
        },
    }

    markdown = generator.format_markdown_report(result)
    assert "信号闭环摘要" in markdown
    assert "20260201" in markdown
    assert "盘前最佳窗口" in markdown


def test_markdown_includes_secondary_launch_intraday_review():
    generator = _build_generator()
    result = {
        "report_date": "2026-04-01",
        "report_time": "2026-04-01 15:10:00",
        "market_analysis": {},
        "stock_selection": [],
        "stock_selection_meta": {},
        "secondary_launch_selection": [
            {"ts_code": "600468.SH", "name": "百利电气", "rs20": 0.92, "drawdown_from_peak": 0.06}
        ],
        "secondary_launch_meta": {},
        "secondary_launch_intraday_review": [
            {
                "ts_code": "600468.SH",
                "name": "百利电气",
                "has_buy_signal": True,
                "signal_type": "secondary_launch_pullback",
                "trigger_time": "10:16:00",
                "push_reason": "回踩不破VWAP/开盘价后回拉",
                "confidence": 0.82,
            },
            {
                "ts_code": "001258.SZ",
                "name": "立新能源",
                "has_buy_signal": False,
                "not_pushed_reason": "二次启动突破条件未满足",
                "blocker_tag": "near_high_supply",
                "blocker_label": "前高抛压",
                "blocker_detail": "距离近30分钟前高过近，但量能未明显放大",
                "confidence": 0.41,
            },
        ],
        "hold_analysis": {"hold_count": 0, "total_profit": 0},
    }

    markdown = generator.format_markdown_report(result)
    assert "二次启动盘中复盘" in markdown
    assert "600468.SH 百利电气" in markdown
    assert "买点 `是`" in markdown
    assert "回踩不破VWAP/开盘价后回拉" in markdown
    assert "001258.SZ 立新能源" in markdown
    assert "买点 `否`" in markdown
    assert "二次启动突破条件未满足" in markdown
    assert "前高抛压" in markdown
    assert "量能未明显放大" in markdown
