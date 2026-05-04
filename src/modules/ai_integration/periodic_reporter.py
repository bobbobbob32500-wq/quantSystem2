# -*- coding: utf-8 -*-
"""
智能周报/月报
自动生成周期交易报告、收益归因分析、策略对比
"""

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from src.core.logger import get_logger
from src.modules.ai_integration.llm_client import LLMClient

logger = get_logger("periodic_reporter")


class PeriodicReporter:
    """周期报告生成器"""

    def __init__(self, llm_client: Optional[LLMClient] = None):
        self.llm = llm_client

    def generate_weekly_report(
        self,
        week_trades: List[Dict[str, Any]],
        week_signals: List[Dict[str, Any]],
        holdings: List[Dict[str, Any]],
        strategy_performances: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """生成周报"""
        # 基础统计
        total_trades = len(week_trades)
        profitable = [t for t in week_trades if t.get("pnl_pct", 0) > 0]
        losing = [t for t in week_trades if t.get("pnl_pct", 0) <= 0]
        win_rate = len(profitable) / total_trades if total_trades > 0 else 0

        total_pnl = sum(t.get("pnl_pct", 0) for t in week_trades)
        avg_pnl = total_pnl / total_trades if total_trades > 0 else 0
        max_win = max((t.get("pnl_pct", 0) for t in week_trades), default=0)
        max_loss = min((t.get("pnl_pct", 0) for t in week_trades), default=0)

        # 收益归因
        attribution = self._compute_attribution(week_trades, strategy_performances)

        # 最佳/最差交易
        best_trades = sorted(week_trades, key=lambda t: t.get("pnl_pct", 0), reverse=True)[:3]
        worst_trades = sorted(week_trades, key=lambda t: t.get("pnl_pct", 0))[:3]

        # 教训总结
        lessons = self._extract_lessons(week_trades)

        report = {
            "type": "weekly",
            "period": {
                "start": (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d"),
                "end": datetime.now().strftime("%Y-%m-%d"),
            },
            "summary": {
                "total_trades": total_trades,
                "win_count": len(profitable),
                "loss_count": len(losing),
                "win_rate": round(win_rate, 4),
                "total_pnl_pct": round(total_pnl, 2),
                "avg_pnl_pct": round(avg_pnl, 2),
                "max_win_pct": round(max_win, 2),
                "max_loss_pct": round(max_loss, 2),
                "total_signals": len(week_signals),
                "current_holdings": len(holdings),
            },
            "attribution": attribution,
            "best_trades": [self._format_trade(t) for t in best_trades],
            "worst_trades": [self._format_trade(t) for t in worst_trades],
            "lessons": lessons,
            "next_week_suggestions": self._generate_next_suggestions(win_rate, total_pnl, lessons),
            "generated_at": datetime.now().isoformat(),
        }

        return report

    def generate_monthly_report(
        self,
        month_trades: List[Dict[str, Any]],
        month_signals: List[Dict[str, Any]],
        holdings: List[Dict[str, Any]],
        weekly_reports: Optional[List[Dict]] = None,
    ) -> Dict[str, Any]:
        """生成月报"""
        total_trades = len(month_trades)
        profitable = [t for t in month_trades if t.get("pnl_pct", 0) > 0]
        win_rate = len(profitable) / total_trades if total_trades > 0 else 0
        total_pnl = sum(t.get("pnl_pct", 0) for t in month_trades)

        # 月度趋势
        weekly_pnls = []
        if weekly_reports:
            for wr in weekly_reports:
                weekly_pnls.append(wr.get("summary", {}).get("total_pnl_pct", 0))

        return {
            "type": "monthly",
            "period": {
                "start": (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d"),
                "end": datetime.now().strftime("%Y-%m-%d"),
            },
            "summary": {
                "total_trades": total_trades,
                "win_rate": round(win_rate, 4),
                "total_pnl_pct": round(total_pnl, 2),
                "total_signals": len(month_signals),
                "current_holdings": len(holdings),
            },
            "weekly_trend": weekly_pnls,
            "strategy_comparison": self._compare_strategies_monthly(month_trades),
            "generated_at": datetime.now().isoformat(),
        }

    def _compute_attribution(
        self,
        trades: List[Dict],
        strategy_perfs: Optional[List[Dict]] = None,
    ) -> Dict[str, Any]:
        """收益归因分析"""
        # 按策略归因
        by_strategy: Dict[str, float] = {}
        for t in trades:
            strategy = t.get("strategy", "unknown")
            by_strategy[strategy] = by_strategy.get(strategy, 0) + t.get("pnl_pct", 0)

        # 按板块归因
        by_sector: Dict[str, float] = {}
        for t in trades:
            sector = t.get("sector", "其他")
            by_sector[sector] = by_sector.get(sector, 0) + t.get("pnl_pct", 0)

        return {
            "by_strategy": {k: round(v, 2) for k, v in sorted(by_strategy.items(), key=lambda x: x[1], reverse=True)},
            "by_sector": {k: round(v, 2) for k, v in sorted(by_sector.items(), key=lambda x: x[1], reverse=True)},
        }

    def _extract_lessons(self, trades: List[Dict]) -> List[str]:
        lessons = []
        losing = [t for t in trades if t.get("pnl_pct", 0) < -3]
        if len(losing) > len(trades) * 0.3:
            lessons.append("大亏交易占比过高，需加强止损纪律")

        quick_loss = [t for t in trades if t.get("pnl_pct", 0) < -2 and t.get("hold_minutes", 0) < 60]
        if quick_loss:
            lessons.append(f"存在{len(quick_loss)}笔快速亏损交易，避免冲动操作")

        if not lessons:
            lessons.append("本周操作纪律良好，继续保持")
        return lessons

    def _generate_next_suggestions(self, win_rate: float, total_pnl: float, lessons: List[str]) -> List[str]:
        suggestions = []
        if win_rate < 0.5:
            suggestions.append("提高选股评分门槛，宁缺毋滥")
        if total_pnl < 0:
            suggestions.append("减少交易频率，等待高确定性机会")
        if win_rate > 0.6:
            suggestions.append("当前策略有效，可适当增加仓位")
        suggestions.append("严格执行止损纪律")
        return suggestions

    def _compare_strategies_monthly(self, trades: List[Dict]) -> List[Dict]:
        by_strategy: Dict[str, List] = {}
        for t in trades:
            s = t.get("strategy", "unknown")
            by_strategy.setdefault(s, []).append(t)

        result = []
        for strategy, st_list in by_strategy.items():
            wr = len([t for t in st_list if t.get("pnl_pct", 0) > 0]) / len(st_list) if st_list else 0
            avg = sum(t.get("pnl_pct", 0) for t in st_list) / len(st_list) if st_list else 0
            result.append({
                "strategy": strategy,
                "trades": len(st_list),
                "win_rate": round(wr, 4),
                "avg_pnl_pct": round(avg, 2),
            })
        return sorted(result, key=lambda x: x["avg_pnl_pct"], reverse=True)

    def _format_trade(self, t: Dict) -> Dict:
        return {
            "symbol": t.get("symbol", ""),
            "name": t.get("name", ""),
            "pnl_pct": round(t.get("pnl_pct", 0), 2),
            "strategy": t.get("strategy", ""),
        }

    def ai_generate_report(self, report_data: Dict) -> Optional[str]:
        """AI生成报告"""
        if not self.llm or not self.llm.is_available:
            return None

        report_type = report_data.get("type", "weekly")
        summary = report_data.get("summary", {})

        prompt = f"""你是量化交易报告分析师，请根据以下数据生成{report_type}交易报告：

## 概要统计
- 总交易: {summary.get('total_trades', 0)} 笔
- 胜率: {summary.get('win_rate', 0)*100:.1f}%
- 总收益: {summary.get('total_pnl_pct', 0):.2f}%
- 最大盈利: {summary.get('max_win_pct', 0):.2f}%
- 最大亏损: {summary.get('max_loss_pct', 0):.2f}%

## 收益归因
{report_data.get('attribution', {})}

## 教训
{report_data.get('lessons', [])}

请生成专业报告，包含：
1. 本期总结
2. 策略表现评价
3. 风险分析
4. 下期建议

用简洁专业的中文回答。"""

        try:
            return self.llm.chat(
                prompt=prompt,
                system="你是专业的量化交易报告分析师。",
            )
        except Exception:
            logger.exception("AI生成报告失败")
            return None
