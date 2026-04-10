# -*- coding: utf-8 -*-
"""
终端首页仪表盘数据与渲染。
"""

from __future__ import annotations

import json
from pathlib import Path

from src.services.dashboard_service import DashboardDataService


class TerminalDashboard:
    """为终端首页提供统一状态快照和文本渲染。"""

    def __init__(self, config, db, position_controller):
        self.config = config
        self.db = db
        self.position_controller = position_controller
        self.project_root = Path(__file__).resolve().parents[2]
        self.dashboard_service = DashboardDataService(
            project_root=self.project_root,
            config=config,
        )

    def build_home_context(self) -> dict:
        # 使用轻量快照，避免整页看板聚合 + Windows tasklist 导致首屏长时间卡顿
        snapshot = self.dashboard_service.build_terminal_home_snapshot()
        market = self._safe_market_snapshot()
        secondary = self._load_secondary_launch_status()
        return {
            "snapshot": snapshot,
            "market": market,
            "secondary": secondary,
        }

    def render_home(self) -> str:
        context = self.build_home_context()
        snapshot = context["snapshot"]
        market = context["market"]
        secondary = context["secondary"]
        meta = snapshot.get("meta", {})
        holdings = snapshot.get("holdings", {})
        signals = snapshot.get("signals", {})
        health = snapshot.get("health", {})
        virtual_stats = (snapshot.get("virtual_trades") or {}).get("stats", {})
        candidate_pool = snapshot.get("candidate_pool", {})
        market_session = meta.get("market_session", {}) or {}
        todos = self._build_todos(
            market_session=market_session,
            market=market,
            holdings=holdings,
            secondary=secondary,
            candidate_pool=candidate_pool,
            health=health,
        )

        lines = [
            "",
            "    ================================================================",
            f"    {meta.get('app_name', '量化交易辅助系统')}  终端指挥台",
            "    ================================================================",
            f"    生成时间: {meta.get('generated_label', '-')}"
            f"   交易阶段: {market_session.get('phase', '-')}"
            f"   最新交易日: {self.db.get_latest_trade_date('stock_daily') or '-'}",
            "    ---------------------------------------------------------------",
            "    核心状态",
            f"    市场状态: {market.get('market_regime', '未知')}"
            f"   目标仓位: {market.get('target_position_pct', '-')}"
            f"   风险状态: {market.get('risk_state', '未知')}",
            f"    当前持仓: {holdings.get('count', 0)}只"
            f"   总浮盈: {holdings.get('total_unrealized_pct', 0):.2f}%"
            f"   监控健康: {health.get('status_label', '未知')}",
            f"    近两周信号: {signals.get('recent_count', 0)}条"
            f"   最近信号: {signals.get('latest_signal_label', '暂无最近信号')}",
            "    ---------------------------------------------------------------",
            "    绩效速览",
            f"    胜率: {virtual_stats.get('win_rate_pct', 0):.2f}%"
            f"   盈亏比: {self._format_ratio(virtual_stats.get('profit_loss_ratio'))}"
            f"   最大回撤: {self._format_percent(virtual_stats.get('max_drawdown_pct'))}",
            f"    候选池: {candidate_pool.get('count', 0)}只"
            f"   平均评分: {candidate_pool.get('avg_score', 0):.2f}"
            f"   虚拟持仓: {(snapshot.get('virtual_trades') or {}).get('open_count', 0)}笔",
            "    ---------------------------------------------------------------",
            "    二次启动策略",
            f"    最近状态: {secondary.get('status_label', '暂无跟踪结果')}"
            f"   信号数: {secondary.get('signal_count', 0)}"
            f"   连续空窗: {secondary.get('latest_empty_trade_days', 0)}天",
            f"    跟踪胜率: {self._format_percent(secondary.get('completed_win_rate'))}"
            f"   平均收益: {self._format_percent(secondary.get('completed_avg_return'))}"
            f"   报表: {secondary.get('report_name', '-')}",
            "    ---------------------------------------------------------------",
            "    突破选股（选强→等突破→量能确认）",
            "    入口: 交易执行→3  |  策略研究→2→1  |  数据管理→3  |  回测: 策略研究→1",
        ]
        lines.extend(
            [
                "    ---------------------------------------------------------------",
                "    今日待办建议",
            ]
        )
        for idx, todo in enumerate(todos, 1):
            lines.append(f"    {idx}. {todo}")
        lines.append("    ================================================================")
        return "\n".join(lines)

    def _build_todos(
        self,
        market_session: dict,
        market: dict,
        holdings: dict,
        secondary: dict,
        candidate_pool: dict,
        health: dict,
    ) -> list[str]:
        todos: list[str] = []
        phase = market_session.get("phase", "")
        risk_state = str(market.get("risk_state", "未知")).upper()
        holding_count = int(holdings.get("count", 0) or 0)
        signal_count = int(secondary.get("signal_count", 0) or 0)
        latest_empty_days = int(secondary.get("latest_empty_trade_days", 0) or 0)
        candidate_count = int(candidate_pool.get("count", 0) or 0)

        if phase == "盘前":
            if candidate_count > 0:
                todos.append("先查看候选池与今日选股，确认盘前计划和推送内容。")
            else:
                todos.append("盘前先执行今日选股，确认候选池和交易计划已生成。")
        elif phase in {"上午盘", "下午盘"}:
            todos.append("盘中优先关注实时监控与风控检测，避免偏离计划交易。")
        elif phase == "盘后":
            todos.append("盘后优先执行一键日报和盘后作业，沉淀当天复盘结果。")
        else:
            todos.append("先刷新首页并检查最新数据日期，确认系统状态正常。")

        if risk_state in {"HIGH", "ELEVATED"}:
            todos.append("当前风险偏高，优先查看市场与仓位，必要时降低执行节奏。")
        else:
            todos.append("当前风险可控，可按计划执行高频动作并跟踪信号质量。")

        if holding_count > 0:
            todos.append(f"当前有 {holding_count} 只持仓，建议先看持仓管理与风控检测。")
        else:
            todos.append("当前无真实持仓，可优先关注候选股质量与信号稳定性。")

        if signal_count > 0:
            todos.append("二次启动策略近期有信号，建议查看近日报表与 T+ 分布。")
        elif latest_empty_days >= 20:
            todos.append("二次启动策略连续空窗较久，建议复核参数窗口与市场适配性。")
        else:
            todos.append("二次启动策略近期无明显异常，可继续观察信号恢复情况。")

        if health.get("status") != "healthy":
            todos.append("运行健康存在告警，建议进入系统运维检查监控与自动推送状态。")

        return todos[:5]

    def _safe_market_snapshot(self) -> dict:
        try:
            result = self.position_controller.analyze_market()
            return {
                "market_regime": result.get("market_regime", "未知"),
                "target_position_pct": f"{float(result.get('target_position', 0.0)) * 100:.0f}%",
                "risk_state": result.get("risk_state", "未知"),
                "strategy_suggestion": result.get("strategy_suggestion", ""),
            }
        except Exception:
            return {
                "market_regime": "未知",
                "target_position_pct": "-",
                "risk_state": "未知",
                "strategy_suggestion": "",
            }

    def _load_secondary_launch_status(self) -> dict:
        report_files = sorted(
            self.project_root.glob("results/secondary_launch_recent_tracking_*.json"),
            reverse=True,
        )
        if not report_files:
            return {
                "status_label": "暂无报表",
                "signal_count": 0,
                "latest_empty_trade_days": 0,
                "completed_win_rate": 0.0,
                "completed_avg_return": 0.0,
                "report_name": "-",
            }

        path = report_files[0]
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {
                "status_label": "报表读取失败",
                "signal_count": 0,
                "latest_empty_trade_days": 0,
                "completed_win_rate": 0.0,
                "completed_avg_return": 0.0,
                "report_name": path.name,
            }

        empty_stats = data.get("empty_streak_stats", {}) or {}
        signal_count = int(data.get("signal_count", 0) or 0)
        return {
            "status_label": "近期有信号" if signal_count > 0 else "近期无信号",
            "signal_count": signal_count,
            "latest_empty_trade_days": int(empty_stats.get("latest_empty_trade_days", 0) or 0),
            "completed_win_rate": float(data.get("completed_win_rate", 0.0) or 0.0),
            "completed_avg_return": float(data.get("completed_avg_return", 0.0) or 0.0),
            "report_name": path.name,
        }

    def _format_percent(self, value) -> str:
        try:
            numeric = float(value or 0.0)
        except (TypeError, ValueError):
            return "-"
        if abs(numeric) <= 2:
            numeric *= 100
        return f"{numeric:.2f}%"

    def _format_ratio(self, value) -> str:
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return "-"
        return f"{numeric:.2f}"
