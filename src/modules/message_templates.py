# -*- coding: utf-8 -*-
"""
消息模板构建层。
负责把结构化业务数据转换为企业微信 Markdown 文本。
"""

from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional

from src.modules.secondary_launch_intraday import blocker_tag_to_label


def _safe_float(value, default: float = 0.0) -> float:
    try:
        return float(value or 0.0)
    except Exception:
        return default


def _safe_int(value, default: int = 0) -> int:
    try:
        return int(value or 0)
    except Exception:
        return default


def build_daily_report_markdown(report_data: Dict) -> str:
    report_date = report_data.get("report_date", datetime.now().strftime("%Y-%m-%d"))
    report_time = report_data.get("report_time", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    market = report_data.get("market_analysis", {}) if isinstance(report_data.get("market_analysis"), dict) else {}
    stocks = report_data.get("stock_selection", []) if isinstance(report_data.get("stock_selection"), list) else []
    hold = report_data.get("hold_analysis", {}) if isinstance(report_data.get("hold_analysis"), dict) else {}
    selection_meta = report_data.get("stock_selection_meta", {}) if isinstance(report_data.get("stock_selection_meta"), dict) else {}
    thresholds = selection_meta.get("tradeability_thresholds", {}) if isinstance(selection_meta.get("tradeability_thresholds"), dict) else {}
    secondary_intraday_review = (
        report_data.get("secondary_launch_intraday_review", [])
        if isinstance(report_data.get("secondary_launch_intraday_review"), list)
        else []
    )

    content_lines = [
        "## 📊 A股量化交易辅助日报",
        f"**日期**: {report_date}",
        f"**时间**: {report_time}",
        f"**概览**: 选股 `{len(stocks)}` 只 | 持仓 `{hold.get('hold_count', 0)}` 只",
        "",
        "---",
        "",
    ]

    if market and "error" not in market:
        score = float(market.get("total_score", 0))
        status = "强势" if score >= 80 else "偏强" if score >= 60 else "震荡" if score >= 40 else "偏弱"
        color = "warning" if score >= 75 else "info" if score >= 50 else "comment"
        content_lines.extend([
            "### 🧭 市场状态",
            f"**综合评分**: <font color=\"{color}\">{score:.1f}分</font> ({status})",
            f"- 建议: {market.get('suggestion', '')}",
            "",
        ])

    if thresholds:
        content_lines.extend([
            "### ⚙️ 盘前动态门槛",
            f"- 截止交易日: `{selection_meta.get('selection_end_date', '-')}`",
            f"- 20日均成交额 ≥ `{float(thresholds.get('min_avg_amount_20d', 0)):.0f}`",
            f"- 20日涨停次数 ≤ `{int(thresholds.get('max_recent_limit_up_count_20d', 0))}`",
            f"- 20日涨幅 ≤ `{float(thresholds.get('max_recent_return_20d', 0)):.1f}%`",
            f"- 10日均振幅 ≤ `{float(thresholds.get('max_avg_amplitude_10d', 0)):.1f}%`",
            "",
        ])

    if stocks:
        content_lines.extend(["### 🎯 盘前选股TOP10", ""])
        for i, stock in enumerate(stocks[:10], 1):
            content_lines.append(
                f"{i}. **{stock.get('ts_code', '')} {stock.get('name', '')}** - "
                f"{float(stock.get('total_score', 0)):.1f}分 ({stock.get('level', '观望')})"
            )
            content_lines.append(
                f"- 行业: {stock.get('industry', '未知')} | "
                f"短周期: {float(stock.get('short_cycle_score', 0)):.1f} | "
                f"可交易: {float(stock.get('tradeability_score', 0)):.1f}"
            )
        content_lines.append("")

    if hold and "error" not in hold:
        content_lines.extend([
            "### 📦 持仓状态",
            f"- 持仓数量: {hold.get('hold_count', 0)}只",
            f"- 总盈亏: {hold.get('total_profit', 0)}元",
            "",
        ])

    if secondary_intraday_review:
        blocked_rows = [row for row in secondary_intraday_review if not row.get("has_buy_signal")]
        triggered_rows = [row for row in secondary_intraday_review if row.get("has_buy_signal")]
        content_lines.extend([
            "### 🕒 二次启动盘中复盘",
            f"- 已触发买点: `{len(triggered_rows)}` 只",
            f"- 主动放弃: `{len(blocked_rows)}` 只",
            "",
        ])
        if blocked_rows:
            content_lines.append("#### 今日主动放弃")
            for row in blocked_rows[:5]:
                blocker_label = blocker_tag_to_label(row.get("blocker_tag")) or str(row.get("blocker_label", "") or "未分类阻断")
                content_lines.append(
                    f"- **{row.get('ts_code', '')} {row.get('name', '')}** | "
                    f"`{blocker_label}` | {row.get('not_pushed_reason', '未触发有效买点')}"
                )
                detail = str(row.get("blocker_detail", "") or "").strip()
                if detail:
                    content_lines.append(f"  - 说明: {detail}")
            content_lines.append("")

    content_lines.extend(["---", "*由量化交易辅助系统自动生成*"])
    return "\n".join(content_lines)


def build_pre_market_selection_markdown(report_data: Dict) -> str:
    report_date = report_data.get("report_date", datetime.now().strftime("%Y-%m-%d"))
    report_time = report_data.get("report_time", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    market = report_data.get("market_analysis", {}) if isinstance(report_data.get("market_analysis"), dict) else {}
    stocks = report_data.get("stock_selection", []) if isinstance(report_data.get("stock_selection"), list) else []
    selection_meta = report_data.get("stock_selection_meta", {}) if isinstance(report_data.get("stock_selection_meta"), dict) else {}
    thresholds = selection_meta.get("tradeability_thresholds", {}) if isinstance(selection_meta.get("tradeability_thresholds"), dict) else {}
    strategy_label = str(report_data.get("strategy_label", "默认策略"))
    feedback = report_data.get("feedback_summary", {}) if isinstance(report_data.get("feedback_summary"), dict) else {}

    lines = [
        "## 盘前计划",
        f"**日期**: {report_date}",
        f"**时间**: {report_time}",
        f"**主策略**: {strategy_label}",
        "",
    ]

    if market and "error" not in market:
        target_position = float(market.get("target_position", 0.3))
        market_state = str(market.get("market_regime", "NEUTRAL") or "NEUTRAL")
        risk_state = str(market.get("risk_state", "MEDIUM") or "MEDIUM")
        plan_status = "可交易"
        if len(stocks) == 0:
            plan_status = "休息"
        elif risk_state in {"HIGH", "DEFENSIVE"}:
            plan_status = "谨慎"
        lines.extend(
            [
                "### 今日结论",
                f"- 今日建议: `{plan_status}`",
                f"- 市场状态: `{market_state}` | 风险状态: `{risk_state}`",
                f"- 建议仓位: `{target_position*100:.0f}%`",
                f"- 当前动作: {'一键开始盘中盯盘' if stocks else '今天不开新仓'}",
                f"- 结论一句话: {market.get('strategy_suggestion', '按纪律执行')}",
                "",
            ]
        )

    if stocks:
        lines.extend(["### 今日只看这几只", ""])
        for i, stock in enumerate(stocks[:3], 1):
            score = _safe_float(stock.get("total_score", 0))
            level = str(stock.get("level", "观察") or "观察")
            attention = "优先盯盘" if i == 1 else ("保留观察" if i == 2 else "备选")
            lines.append(
                f"{i}. **{stock.get('ts_code', '')} {stock.get('name', '')}** | "
                f"级别 `{level}` | 评分 `{score:.1f}`"
            )
            lines.append(
                f"- 今日动作: {attention}"
            )
            lines.append(
                f"- 一句话: 先观察，不直接追涨；只在盘中信号触发后执行。"
            )
            lines.append(
                f"- 风险提示: 高开过多不追，弱于VWAP放弃。"
            )
        lines.append("")
    else:
        lines.extend([
            "### 今日不做理由",
            "- 当前没有满足条件的候选标的。",
            "- 建议今天以观察为主，不主动开新仓。",
            "",
        ])

    if feedback and "error" not in feedback:
        lines.extend(["### 最近复盘结论", ""])
        pre_best = feedback.get("pre_market_best")
        if pre_best:
            lines.append(
                f"- 盘前最佳窗口: `T+{_safe_int(pre_best.get('horizon', 0))}` | "
                f"胜率 `{_safe_float(pre_best.get('win_rate', 0)):.2%}` | "
                f"均值净收益 `{_safe_float(pre_best.get('mean_net_return', 0)):.2%}`"
            )
        buy_best = feedback.get("intraday_buy_best")
        if buy_best:
            lines.append(
                f"- 盘中买点最佳窗口: `T+{_safe_int(buy_best.get('horizon', 0))}` | "
                f"胜率 `{_safe_float(buy_best.get('win_rate', 0)):.2%}` | "
                f"方向收益均值 `{_safe_float(buy_best.get('mean_net_return', 0)):.2%}`"
            )
        lines.append("")

    lines.extend(
        [
            "### 执行纪律",
            "- 盘前计划只负责缩圈，不负责直接下单。",
            "- 盘中只处理真正触发的买卖点信号。",
            "- 如果盘中风险转防守，以盘中风控为准。",
            "",
            "---",
            "*仅供交易决策参考*",
        ]
    )
    return "\n".join(lines)


def build_trade_signals_markdown(
    signals: List[Dict],
    now: Optional[datetime] = None,
    filtered_count: int = 0,
    side: str = "buy",
) -> str:
    signal_list = signals or []
    ts = now or datetime.now()
    if side == "buy":
        action_label = "买点信号"
    elif side == "sell":
        action_label = "卖点信号"
    else:
        action_label = "买卖点信号"

    lines = [
        f"## 盘中{action_label}",
        f"**时间**: {ts.strftime('%Y-%m-%d %H:%M:%S')}",
        f"**触发数量**: {len(signal_list)}",
        "",
    ]

    for i, signal in enumerate(signal_list, 1):
        action = str(signal.get("action", "BUY" if side == "buy" else "SELL")).upper()
        total_score = float(signal.get("total_score", 0) or 0)
        suggest_position_pct = float(signal.get("suggest_position_pct", 0.0) or 0.0)
        strategy_label = str(
            signal.get("strategy_label", signal.get("strategy_profile", "legacy")) or "legacy"
        )
        buy_route_label = str(
            signal.get("buy_route_label", signal.get("buy_template_source", "unknown")) or "unknown"
        )
        buy_template_source = str(signal.get("buy_template_source", "unknown") or "unknown")
        signal_type = str(signal.get("signal_type", "unknown") or "unknown")
        signal_subtype = str(signal.get("signal_subtype", "") or "").strip()
        position_note = str(signal.get("position_note", "") or "").strip()

        lines.append(f"### 信号{i}: {signal.get('symbol', '')} {signal.get('name', '')}")
        lines.append(f"- 当前动作: `{action}` | 价格 `{float(signal.get('price', 0) or 0):.2f}`")
        lines.append(f"- 策略: `{strategy_label}` | 类型 `{signal_type}`")
        if signal_subtype and signal_subtype != signal_type:
            lines.append(f"- 子类型标签: `{signal_subtype}`")
        lines.append(f"- 建议仓位: `{suggest_position_pct:.2f}%` | 信号强度 `{total_score:.1f}`")
        if position_note:
            lines.append(f"- 仓位说明: {position_note}")

        industry_confirm = signal.get("industry_confirm") or {}
        if industry_confirm:
            lines.append(
                f"- 行业确认: `{industry_confirm.get('industry', '未知')}` / `{industry_confirm.get('level', 'neutral')}`"
            )

        signal_details = signal.get("signal_details") or {}
        entry_trigger = str(signal_details.get("entry_trigger", "") or "").strip()
        invalid_below = signal_details.get("invalid_below")
        expiry_hint = str(signal_details.get("expiry_hint", "") or "").strip()
        if entry_trigger:
            lines.append(f"- 触发机制: {entry_trigger}")
        if invalid_below is not None:
            lines.append(f"- 失效价位: `{float(invalid_below):.2f}`")
        if expiry_hint:
            lines.append(f"- 失效说明: {expiry_hint}")
        lines.append(f"- 模板: `{buy_route_label}` / `{buy_template_source}`")
        lines.append("")

    lines.extend(
        [
            "### 执行纪律",
            "- 只处理真正触发的信号，不主观追单。",
            "- 执行优先级：盘中风控 > 信号本身 > 盘前候选顺序。",
            "",
            "---",
            "*仅供交易决策参考*",
        ]
    )
    return "\n".join(lines)


def build_position_events_markdown(
    events: List[Dict],
    now: Optional[datetime] = None,
) -> str:
    event_list = events or []
    ts = now or datetime.now()
    lines = [
        "## 📦 持仓管理事件",
        "**Template**: `position_event_v2`",
        f"**时间**: {ts.strftime('%Y-%m-%d %H:%M:%S')}",
        f"**事件数量**: {len(event_list)}",
        "",
    ]

    for i, event in enumerate(event_list, 1):
        action = str(event.get("action", "REVIEW")).upper()
        ts_code = str(event.get("ts_code", "") or "")
        name = str(event.get("name", "") or "")
        signal_type = str(event.get("signal_type", "unknown") or "unknown")
        severity = str(event.get("severity", "medium") or "medium")
        hold_num = float(event.get("hold_num", 0) or 0)
        hold_price = float(event.get("hold_price", 0) or 0)
        current_price = float(event.get("current_price", 0) or 0)
        profit = float(event.get("profit", 0) or 0)
        reconcile_status = str(event.get("reconcile_status", "CONFIRMED") or "CONFIRMED")
        is_real_position = bool(event.get("is_real_position", True))
        reason = str(event.get("reason", "") or "").strip()
        suggestion = str(event.get("suggestion", "") or "").strip()

        lines.append(f"### 事件{i}: {ts_code} {name}")
        lines.append(f"- 动作/标的: `{action}` / `{ts_code} {name}`")
        lines.append(f"- 信号摘要: `{signal_type}` | 风险 `{severity}`")
        lines.append(f"- 持仓概览: `{hold_num:.0f}股` / 成本 `{hold_price:.2f}`")
        lines.append(f"- 当前表现: 现价 `{current_price:.2f}` | 盈亏 `{profit:+.2f}%`")
        lines.append(f"- 对账状态: `{reconcile_status}` | 真实持仓 `{is_real_position}`")
        if reason:
            lines.append(f"- 触发原因: {reason}")
        if suggestion:
            lines.append(f"- 操作说明: {suggestion}")
        lines.append(f"- 事件ID: `{event.get('event_id', '')}`")
        lines.append("")

    lines.extend(
        [
            "### 执行纪律",
            "- 持仓事件以你的真实持仓为准，非持仓标的不发出卖出建议。",
            "- 本消息仅供交易决策辅助，最终执行请以你的交易终端为准。",
            "",
            "---",
            "*仅供交易决策参考*",
        ]
    )
    return "\n".join(lines)


def build_feedback_digest_markdown(
    feedback_data: Dict,
    now: Optional[datetime] = None,
) -> str:
    payload = feedback_data or {}
    ts = now or datetime.now()

    pre_best = payload.get("pre_market_best") if isinstance(payload.get("pre_market_best"), dict) else None
    buy_best = payload.get("intraday_buy_best") if isinstance(payload.get("intraday_buy_best"), dict) else None
    sell_best = payload.get("intraday_sell_best") if isinstance(payload.get("intraday_sell_best"), dict) else None
    files = payload.get("files", {}) if isinstance(payload.get("files"), dict) else {}

    lines = [
        "## 盘后复盘摘要",
        f"**时间**: {ts.strftime('%Y-%m-%d %H:%M:%S')}",
        f"**评估区间**: `{payload.get('start_date', '-')}` ~ `{payload.get('end_date', '-')}`",
        "",
        "### 今日结论",
        f"- 盘前样本: `{_safe_int(payload.get('recommendation_detail_count', 0))}`",
        f"- 盘中样本: `{_safe_int(payload.get('signal_detail_count', 0))}`",
    ]

    if pre_best:
        lines.append(
            f"- 盘前最佳窗口: `T+{_safe_int(pre_best.get('horizon', 0))}` | "
            f"胜率 `{_safe_float(pre_best.get('win_rate', 0)):.2%}` | "
            f"均值净收益 `{_safe_float(pre_best.get('mean_net_return', 0)):.2%}`"
        )
    else:
        lines.append("- 盘前最佳窗口: 暂无有效统计")

    if buy_best:
        lines.append(
            f"- 盘中买点最佳窗口: `T+{_safe_int(buy_best.get('horizon', 0))}` | "
            f"胜率 `{_safe_float(buy_best.get('win_rate', 0)):.2%}` | "
            f"方向收益均值 `{_safe_float(buy_best.get('mean_net_return', 0)):.2%}`"
        )
    else:
        lines.append("- 盘中买点最佳窗口: 暂无有效统计")

    if sell_best:
        lines.append(
            f"- 盘中卖点最佳窗口: `T+{_safe_int(sell_best.get('horizon', 0))}` | "
            f"胜率 `{_safe_float(sell_best.get('win_rate', 0)):.2%}` | "
            f"方向收益均值 `{_safe_float(sell_best.get('mean_net_return', 0)):.2%}`"
        )
    else:
        lines.append("- 盘中卖点最佳窗口: 暂无有效统计")

    if files:
        lines.extend(
            [
                "",
                "### 查看详情",
                f"- Markdown: `{files.get('markdown', '-')}`",
                f"- JSON: `{files.get('json', '-')}`",
            ]
        )

    lines.extend(
        [
            "",
            "### 明日动作",
            "- 盘后复盘只给方向，不替代次日盘中信号。",
            "- 次日继续按盘前计划缩圈、按盘中信号执行。",
            "",
            "---",
            "*仅供交易决策参考*",
        ]
    )
    return "\n".join(lines)
