# -*- coding: utf-8 -*-
"""
AI管家 - 量化系统智能运营助手
主动监控、智能预警、决策建议、自动报告
"""

import json
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Callable
from enum import Enum

from src.core.logger import get_logger
from src.modules.ai_integration.llm_client import LLMClient
from src.modules.ai_integration.ai_response_models import MorningBriefingPayload, PostMarketReviewPayload
from src.modules.ai_integration.structured_output import llm_chat_structured

logger = get_logger("ai_butler")


class ButlerRole(Enum):
    """管家角色"""
    MORNING_BRIEFER = "盘前简报员"      # 盘前准备
    INTRADAY_WATCHER = "盘中监控员"      # 盘中盯盘
    POST_MARKET_ANALYST = "盘后分析师"   # 盘后复盘
    RISK_SENTINEL = "风控哨兵"           # 风险监控
    STRATEGY_ADVISOR = "策略顾问"        # 策略建议
    CODE_ASSISTANT = "代码助手"          # 代码生成


class AIButler:
    """
    AI管家 - 量化系统智能运营核心

    职责:
    1. 主动监控: 持仓、信号、市场、系统健康
    2. 智能预警: 异常波动、风险事件、机会提醒
    3. 决策建议: 操作建议、仓位调整、策略优化
    4. 自动报告: 盘前简报、盘中快报、盘后复盘
    """

    def __init__(self, llm_client: LLMClient):
        self.llm = llm_client
        self._watchlist: List[Dict] = []       # 关注列表
        self._alerts: List[Dict] = []          # 预警队列
        self._today_plan: Optional[Dict] = None # 今日计划
        self._context: Dict = {}               # 上下文信息

    # ==================== 盘前职责 ====================

    def morning_briefing(
        self,
        yesterday_review: Optional[Dict] = None,
        today_selection: Optional[List[Dict]] = None,
        overnight_news: Optional[List[Dict]] = None,
        data_status: Optional[Dict] = None,
    ) -> Dict:
        """
        盘前简报 - 8:00-9:15

        Args:
            yesterday_review: 昨日复盘数据
            today_selection: 今日选股结果
            overnight_news: 隔夜新闻
            data_status: 数据更新状态

        Returns:
            {
                "briefing": "简报内容",
                "focus_stocks": [重点关注股票],
                "risk_alerts": [风险预警],
                "opportunity_alerts": [机会提醒],
                "suggestions": [操作建议],
            }
        """
        if not self.llm.is_available:
            return self._fallback_briefing(today_selection)

        # 构建上下文
        context_parts = []

        if data_status:
            status_text = self._format_data_status(data_status)
            if "异常" in status_text or "缺失" in status_text:
                context_parts.append(f"⚠️ 数据状态:\n{status_text}")

        if yesterday_review:
            context_parts.append(f"📊 昨日复盘:\n{self._format_review(yesterday_review)}")

        if today_selection:
            context_parts.append(f"🎯 今日选股:\n{self._format_selection(today_selection)}")

        if overnight_news:
            context_parts.append(f"📰 隔夜新闻:\n{self._format_news(overnight_news[:5])}")

        context = "\n\n".join(context_parts) if context_parts else "暂无数据"

        prompt = f"""你是量化交易系统的AI管家，现在需要生成盘前简报。

## 当前信息
{context}

请生成盘前简报，包含以下内容：

### 1. 数据检查
- 数据是否完整？有无缺失？
- 如有异常，需要采取什么补救措施？

### 2. 昨日回顾
- 昨日操作得失
- 需要记住的教训

### 3. 今日策略
- 市场环境判断
- 仓位建议
- 重点关注的股票（最多3只）及原因

### 4. 风险预警
- 需要警惕的风险点
- 隔夜新闻可能的影响

### 5. 操作建议
- 开盘后首先应该做什么？
- 今日交易纪律提醒

请用简洁专业的中文回答，突出重点，可操作性强。"""

        system = "你是专业的A股量化交易管家，擅长盘前准备、风险预警和策略建议。你的建议必须具体可操作。"
        structured, _raw = llm_chat_structured(
            self.llm,
            prompt=prompt,
            system=system,
            model_cls=MorningBriefingPayload,
            temperature=0.3,
            max_tokens=1400,
            max_fix_attempts=1,
        )

        if structured:
            briefing = self._render_morning_briefing(structured)
            focus_stocks = (structured.focus_stocks or [])[:3]
            risk_alerts = [{"type": "风险提醒", "message": item} for item in (structured.risk_alerts or [])[:10]]
            opportunity_alerts = []
            suggestions = (structured.action_suggestions or [])[:8]
        else:
            briefing = self.llm.chat(prompt=prompt, system=system)
            focus_stocks = self._extract_focus_stocks(today_selection or [], briefing)
            risk_alerts = self._extract_risk_alerts(briefing)
            opportunity_alerts = self._extract_opportunities(briefing, today_selection or [])
            suggestions = self._extract_suggestions(briefing)

        # 保存今日计划
        self._today_plan = {
            "briefing": briefing,
            "focus_stocks": focus_stocks,
            "risk_alerts": risk_alerts,
            "suggestions": suggestions,
            "created_at": datetime.now().isoformat(),
        }

        return {
            "briefing": briefing,
            "focus_stocks": focus_stocks,
            "risk_alerts": risk_alerts,
            "opportunity_alerts": opportunity_alerts,
            "suggestions": suggestions,
        }

    # ==================== 盘中职责 ====================

    def intraday_monitor(
        self,
        holdings: Optional[List[Dict]] = None,
        signals: Optional[List[Dict]] = None,
        market_status: Optional[Dict] = None,
        watchlist_hits: Optional[List[Dict]] = None,
    ) -> Dict:
        """
        盘中监控 - 9:30-15:00

        Args:
            holdings: 当前持仓
            signals: 最新信号
            market_status: 市场状态
            watchlist_hits: 关注标的触发事件

        Returns:
            {
                "status_summary": "状态摘要",
                "alerts": [预警列表],
                "action_suggestions": [操作建议],
                "watch_reminders": [盯盘提醒],
            }
        """
        if not self.llm.is_available:
            return self._fallback_monitor(holdings, signals)

        context_parts = []

        if holdings:
            context_parts.append(f"当前持仓:\n{self._format_holdings(holdings)}")

        if signals:
            context_parts.append(f"最新信号:\n{self._format_signals(signals[:5])}")

        if market_status:
            context_parts.append(f"市场状态:\n{self._format_market(market_status)}")

        if watchlist_hits:
            context_parts.append(f"关注触发:\n{self._format_watchlist_hits(watchlist_hits)}")

        context = "\n\n".join(context_parts) if context_parts else "暂无数据"

        prompt = f"""你是量化交易系统的AI管家，正在进行盘中监控。

## 当前状态
{context}

请分析当前状态并给出建议：

### 1. 持仓监控
- 持仓股票表现如何？
- 有无异常波动需要关注？
- 是否需要调整止损/止盈？

### 2. 信号解读
- 最新信号的含义？
- 信号有效性判断？
- 是否应该执行？如何执行？

### 3. 市场环境
- 当前市场环境如何？
- 是否有系统性风险？
- 仓位是否需要调整？

### 4. 操作建议
- 当前最应该做什么？
- 具体操作步骤

请用简洁专业的中文回答，重点突出，可操作性强。"""

        analysis = self.llm.chat(
            prompt=prompt,
            system="你是专业的A股短线交易管家，擅长盘中监控、信号解读和风险控制。",
        )

        # 生成预警
        alerts = self._generate_intraday_alerts(holdings or [], signals or [], market_status or {})

        # 提取操作建议
        action_suggestions = self._extract_suggestions(analysis)

        # 生成盯盘提醒
        watch_reminders = self._generate_watch_reminders(holdings or [], self._watchlist)

        return {
            "status_summary": analysis,
            "alerts": alerts,
            "action_suggestions": action_suggestions,
            "watch_reminders": watch_reminders,
        }

    def analyze_signal_realtime(
        self,
        signal: Dict,
        stock_info: Dict,
        position: Optional[Dict] = None,
    ) -> Dict:
        """
        实时信号分析 - 信号触发时立即调用

        Args:
            signal: 信号详情
            stock_info: 股票信息
            position: 如果有持仓

        Returns:
            {
                "analysis": "分析内容",
                "action": "BUY/HOLD/SELL/WATCH",
                "confidence": 0.0-1.0,
                "reason": "原因",
                "execution_advice": "执行建议",
            }
        """
        if not self.llm.is_available:
            return {
                "analysis": f"信号: {signal.get('type', '未知')}",
                "action": "WATCH",
                "confidence": 0.5,
                "reason": "AI服务不可用",
                "execution_advice": "请人工判断",
            }

        signal_type = signal.get("type", "未知")
        price = stock_info.get("price", "N/A")
        name = stock_info.get("name", stock_info.get("code", "未知"))

        position_text = ""
        if position:
            position_text = f"""
当前持仓:
- 成本价: {position.get('cost_price', 'N/A')}
- 持仓数量: {position.get('quantity', 'N/A')}
- 浮盈: {position.get('pnl_pct', 'N/A')}%
"""

        prompt = f"""股票 {name} 刚刚触发 {signal_type} 信号！

## 信号详情
- 信号类型: {signal_type}
- 触发价格: {price}
- 触发时间: {signal.get('time', datetime.now().strftime('%H:%M:%S'))}
- 技术指标: {json.dumps(signal.get('indicators', {}), ensure_ascii=False)}

{position_text}

请快速分析并给出建议：

1. **信号有效性**: 这个信号是否可靠？判断依据？
2. **操作建议**: 应该买入/卖出/持有/观望？
3. **执行方案**: 如果执行，建议的价格、仓位、止损位？
4. **风险提示**: 需要注意什么？

请快速回答，简洁明了。"""

        analysis = self.llm.chat(
            prompt=prompt,
            system="你是专业的短线交易员，擅长快速判断信号有效性并给出操作建议。",
            temperature=0.3,  # 降低随机性，更确定性的建议
        )

        # 解析操作建议
        action = self._parse_action(analysis)
        confidence = self._parse_confidence(analysis)
        reason = self._parse_reason(analysis)
        execution_advice = self._parse_execution(analysis)

        return {
            "analysis": analysis,
            "action": action,
            "confidence": confidence,
            "reason": reason,
            "execution_advice": execution_advice,
        }

    # ==================== 盘后职责 ====================

    def post_market_review(
        self,
        today_trades: Optional[List[Dict]] = None,
        today_signals: Optional[List[Dict]] = None,
        holdings: Optional[List[Dict]] = None,
        market_summary: Optional[Dict] = None,
    ) -> Dict:
        """
        盘后复盘 - 15:00-18:00

        Args:
            today_trades: 今日交易记录
            today_signals: 今日信号记录
            holdings: 当前持仓
            market_summary: 市场总结

        Returns:
            {
                "review_report": "复盘报告",
                "performance_summary": "表现总结",
                "lessons": [经验教训],
                "tomorrow_plan": "明日计划",
            }
        """
        if not self.llm.is_available:
            return self._fallback_review(today_trades, today_signals)

        context_parts = []

        if today_trades:
            context_parts.append(f"今日交易:\n{self._format_trades(today_trades)}")

        if today_signals:
            context_parts.append(f"今日信号:\n{self._format_signals(today_signals)}")

        if holdings:
            context_parts.append(f"当前持仓:\n{self._format_holdings(holdings)}")

        if market_summary:
            context_parts.append(f"市场总结:\n{self._format_market(market_summary)}")

        context = "\n\n".join(context_parts) if context_parts else "暂无数据"

        prompt = f"""你是量化交易系统的AI管家，现在需要生成盘后复盘报告。

## 今日数据
{context}

请生成详细的复盘报告：

### 1. 今日表现
- 交易次数、胜率、盈亏
- 持仓表现
- 与大盘对比

### 2. 操作回顾
- 哪些操作做对了？为什么？
- 哪些操作做错了？原因是什么？
- 错过的好机会？为什么错过？

### 3. 信号评估
- 今日信号有效性如何？
- 哪些信号应该执行但没执行？
- 哪些信号不应该执行但执行了？

### 4. 经验教训
- 今日最重要的3条教训
- 需要改进的地方

### 5. 明日计划
- 市场预判
- 操作策略
- 重点关注的股票

请用专业但通俗易懂的中文撰写，便于学习和改进。"""

        system = "你是专业的量化交易复盘分析师，擅长总结经验教训和制定改进计划。"
        structured, _raw = llm_chat_structured(
            self.llm,
            prompt=prompt,
            system=system,
            model_cls=PostMarketReviewPayload,
            temperature=0.3,
            max_tokens=1600,
            max_fix_attempts=1,
        )

        if structured:
            review_text = self._render_post_market_review(structured)
            return {
                "review_report": review_text,
                "performance_summary": "\n".join((structured.performance_summary or [])[:10]),
                "lessons": (structured.lessons or [])[:7],
                "tomorrow_plan": "\n".join((structured.tomorrow_plan or [])[:12]),
            }

        review = self.llm.chat(prompt=prompt, system=system)
        lessons = self._extract_lessons(review)
        tomorrow_plan = self._extract_tomorrow_plan(review)
        return {
            "review_report": review,
            "performance_summary": self._extract_performance(review),
            "lessons": lessons,
            "tomorrow_plan": tomorrow_plan,
        }

    def _render_morning_briefing(self, payload: MorningBriefingPayload) -> str:
        lines: List[str] = []
        lines.append(f"【盘前总览】{payload.summary}".strip())
        if payload.data_checks:
            lines.append("\n【数据检查】")
            for item in payload.data_checks[:8]:
                lines.append(f"- {item}")
        if payload.market_view:
            lines.append("\n【市场环境】")
            for item in payload.market_view[:8]:
                lines.append(f"- {item}")
        if payload.position_advice:
            lines.append("\n【仓位建议】")
            for item in payload.position_advice[:6]:
                lines.append(f"- {item}")
        if payload.focus_stocks:
            lines.append("\n【重点关注】")
            for s in payload.focus_stocks[:3]:
                code = s.get("code") or s.get("symbol") or ""
                name = s.get("name") or ""
                score = s.get("score", s.get("total_score", ""))
                label = f"{name}({code})" if code else name
                if label:
                    lines.append(f"- {label} 评分:{score}")
        if payload.risk_alerts:
            lines.append("\n【风险预警】")
            for item in payload.risk_alerts[:8]:
                lines.append(f"- {item}")
        if payload.action_suggestions:
            lines.append("\n【开盘优先动作】")
            for item in payload.action_suggestions[:8]:
                lines.append(f"- {item}")
        lines.append("\n[免责声明] 以上内容仅供参考，不构成投资建议。")
        return "\n".join(lines)

    def _render_post_market_review(self, payload: PostMarketReviewPayload) -> str:
        lines: List[str] = []
        lines.append(f"【复盘结论】{payload.summary}".strip())
        if payload.performance_summary:
            lines.append("\n【表现总结】")
            for item in payload.performance_summary[:10]:
                lines.append(f"- {item}")
        if payload.what_went_well:
            lines.append("\n【做对了什么】")
            for item in payload.what_went_well[:8]:
                lines.append(f"- {item}")
        if payload.what_went_wrong:
            lines.append("\n【做错了什么】")
            for item in payload.what_went_wrong[:8]:
                lines.append(f"- {item}")
        if payload.lessons:
            lines.append("\n【经验教训】")
            for item in payload.lessons[:7]:
                lines.append(f"- {item}")
        if payload.tomorrow_plan:
            lines.append("\n【明日计划】")
            for item in payload.tomorrow_plan[:12]:
                lines.append(f"- {item}")
        if payload.risk_notes:
            lines.append("\n【风险与改进】")
            for item in payload.risk_notes[:8]:
                lines.append(f"- {item}")
        lines.append("\n[免责声明] 以上内容仅供参考，不构成投资建议。")
        return "\n".join(lines)

    # ==================== 风控哨兵 ====================

    def risk_check(
        self,
        holdings: List[Dict],
        market_data: Dict,
        account_info: Optional[Dict] = None,
    ) -> Dict:
        """
        风险检查 - 定期调用

        Args:
            holdings: 持仓列表
            market_data: 市场数据
            account_info: 账户信息

        Returns:
            {
                "risk_level": "LOW/MEDIUM/HIGH/CRITICAL",
                "alerts": [风险预警],
                "suggestions": [风控建议],
            }
        """
        alerts = []
        risk_level = "LOW"

        # 1. 持仓集中度检查
        if holdings:
            total_position = sum(h.get("position", 0) for h in holdings)
            if total_position > 0.8:
                alerts.append({
                    "level": "HIGH",
                    "type": "仓位过重",
                    "message": f"总仓位{total_position:.1%}，超过80%，建议减仓",
                })
                risk_level = "HIGH"
            elif total_position > 0.6:
                alerts.append({
                    "level": "MEDIUM",
                    "type": "仓位偏高",
                    "message": f"总仓位{total_position:.1%}，注意控制风险",
                })
                risk_level = max(risk_level, "MEDIUM")

            # 单只股票仓位检查
            for h in holdings:
                if h.get("position", 0) > 0.3:
                    alerts.append({
                        "level": "MEDIUM",
                        "type": "单票仓位过重",
                        "message": f"{h.get('name', h.get('code'))} 仓位{h['position']:.1%}，超过30%",
                    })

        # 2. 市场环境检查
        if market_data:
            regime = market_data.get("regime", "")
            if regime in ["STRONG_BEAR", "BEAR"]:
                alerts.append({
                    "level": "HIGH",
                    "type": "市场环境恶化",
                    "message": f"当前市场体制: {regime}，建议降低仓位或空仓",
                })
                risk_level = "HIGH"
            elif regime == "WEAK_BEAR":
                alerts.append({
                    "level": "MEDIUM",
                    "type": "市场偏弱",
                    "message": "市场环境偏弱，谨慎操作",
                })
                risk_level = max(risk_level, "MEDIUM")

        # 3. AI深度分析（如果可用）
        if self.llm.is_available and alerts:
            ai_analysis = self._ai_risk_analysis(holdings, market_data, alerts)
            alerts.extend(ai_analysis.get("additional_alerts", []))

        return {
            "risk_level": risk_level,
            "alerts": alerts,
            "suggestions": self._generate_risk_suggestions(alerts),
        }

    # ==================== 辅助方法 ====================

    def set_watchlist(self, stocks: List[Dict]):
        """设置关注列表"""
        self._watchlist = stocks

    def add_to_watchlist(self, stock: Dict):
        """添加到关注列表"""
        self._watchlist.append(stock)

    def get_context(self) -> Dict:
        """获取上下文"""
        return self._context

    def update_context(self, key: str, value: Any):
        """更新上下文"""
        self._context[key] = value

    # ==================== 格式化方法 ====================

    def _format_data_status(self, status: Dict) -> str:
        lines = []
        for k, v in status.items():
            lines.append(f"- {k}: {v}")
        return "\n".join(lines)

    def _format_review(self, review: Dict) -> str:
        return json.dumps(review, ensure_ascii=False, indent=2)

    def _format_selection(self, stocks: List[Dict]) -> str:
        lines = []
        for i, s in enumerate(stocks[:10], 1):
            name = s.get("name", s.get("code", "未知"))
            score = s.get("score", s.get("total_score", "N/A"))
            lines.append(f"{i}. {name} 评分:{score}")
        return "\n".join(lines)

    def _format_news(self, news: List[Dict]) -> str:
        lines = []
        for i, n in enumerate(news, 1):
            title = n.get("title", "无标题")
            lines.append(f"{i}. {title}")
        return "\n".join(lines)

    def _format_holdings(self, holdings: List[Dict]) -> str:
        lines = []
        for h in holdings:
            name = h.get("name", h.get("code", "未知"))
            pos = h.get("position", 0)
            pnl = h.get("pnl_pct", "N/A")
            lines.append(f"- {name} 仓位:{pos:.1%} 盈亏:{pnl}%")
        return "\n".join(lines)

    def _format_signals(self, signals: List[Dict]) -> str:
        lines = []
        for s in signals:
            name = s.get("name", s.get("code", "未知"))
            stype = s.get("type", "未知")
            time = s.get("time", "")
            lines.append(f"- [{time}] {name} {stype}")
        return "\n".join(lines)

    def _format_market(self, market: Dict) -> str:
        lines = []
        for k, v in market.items():
            lines.append(f"- {k}: {v}")
        return "\n".join(lines)

    def _format_trades(self, trades: List[Dict]) -> str:
        lines = []
        for t in trades:
            name = t.get("name", t.get("code", "未知"))
            action = t.get("action", "未知")
            price = t.get("price", "N/A")
            lines.append(f"- {name} {action}@{price}")
        return "\n".join(lines)

    def _format_watchlist_hits(self, hits: List[Dict]) -> str:
        lines = []
        for h in hits:
            name = h.get("name", h.get("code", "未知"))
            event = h.get("event", "未知")
            lines.append(f"- {name}: {event}")
        return "\n".join(lines)

    # ==================== 提取方法 ====================

    def _extract_focus_stocks(self, stocks: List[Dict], briefing: str) -> List[Dict]:
        """从简报中提取重点关注股票"""
        # 简单实现：返回评分最高的3只
        if not stocks:
            return []
        sorted_stocks = sorted(stocks, key=lambda x: x.get("score", x.get("total_score", 0)), reverse=True)
        return sorted_stocks[:3]

    def _extract_risk_alerts(self, text: str) -> List[Dict]:
        """提取风险预警"""
        alerts = []
        if "风险" in text:
            alerts.append({"type": "风险提醒", "source": "盘前分析"})
        return alerts

    def _extract_opportunities(self, text: str, stocks: List[Dict]) -> List[Dict]:
        """提取机会提醒"""
        return []

    def _extract_suggestions(self, text: str) -> List[str]:
        """提取操作建议"""
        suggestions = []
        lines = text.split("\n")
        for line in lines:
            if "建议" in line or "应该" in line or "需要" in line:
                suggestions.append(line.strip())
        return suggestions[:5]

    def _extract_lessons(self, text: str) -> List[str]:
        """提取经验教训"""
        lessons = []
        lines = text.split("\n")
        capture = False
        for line in lines:
            if "教训" in line or "经验" in line:
                capture = True
            if capture and line.strip().startswith("-"):
                lessons.append(line.strip())
        return lessons[:5]

    def _extract_tomorrow_plan(self, text: str) -> str:
        """提取明日计划"""
        lines = text.split("\n")
        plan_lines = []
        capture = False
        for line in lines:
            if "明日" in line or "明天" in line:
                capture = True
            if capture:
                plan_lines.append(line)
        return "\n".join(plan_lines[:10])

    def _extract_performance(self, text: str) -> str:
        """提取表现总结"""
        lines = text.split("\n")
        perf_lines = []
        capture = False
        for line in lines:
            if "表现" in line:
                capture = True
            if capture and line.strip():
                perf_lines.append(line)
        return "\n".join(perf_lines[:10])

    def _parse_action(self, text: str) -> str:
        """解析操作建议"""
        text_lower = text.lower()
        if "买入" in text_lower or "建仓" in text_lower:
            return "BUY"
        elif "卖出" in text_lower or "减仓" in text_lower or "清仓" in text_lower:
            return "SELL"
        elif "持有" in text_lower or "持仓" in text_lower:
            return "HOLD"
        else:
            return "WATCH"

    def _parse_confidence(self, text: str) -> float:
        """解析置信度"""
        if "强烈" in text or "明确" in text or "确定" in text:
            return 0.8
        elif "建议" in text or "可以" in text:
            return 0.6
        else:
            return 0.5

    def _parse_reason(self, text: str) -> str:
        """解析原因"""
        lines = text.split("\n")
        for line in lines:
            if "因为" in line or "由于" in line or "原因" in line:
                return line.strip()
        return "基于技术分析"

    def _parse_execution(self, text: str) -> str:
        """解析执行建议"""
        lines = text.split("\n")
        for line in lines:
            if "执行" in line or "操作" in line:
                return line.strip()
        return "请根据实际情况执行"

    def _generate_intraday_alerts(self, holdings: List[Dict], signals: List[Dict], market: Dict) -> List[Dict]:
        """生成盘中预警"""
        alerts = []

        # 持仓异常检查
        for h in holdings:
            pnl = h.get("pnl_pct", 0)
            if pnl < -5:
                alerts.append({
                    "level": "HIGH",
                    "type": "持仓亏损",
                    "message": f"{h.get('name', '')} 亏损{abs(pnl):.1f}%，注意止损",
                })
            elif pnl > 8:
                alerts.append({
                    "level": "MEDIUM",
                    "type": "持仓盈利",
                    "message": f"{h.get('name', '')} 盈利{pnl:.1f}%，考虑止盈",
                })

        return alerts

    def _generate_watch_reminders(self, holdings: List[Dict], watchlist: List[Dict]) -> List[Dict]:
        """生成盯盘提醒"""
        reminders = []
        for w in watchlist[:5]:
            reminders.append({
                "stock": w.get("name", w.get("code", "")),
                "reminder": f"关注 {w.get('name', '')} 的关键价位",
            })
        return reminders

    def _generate_risk_suggestions(self, alerts: List[Dict]) -> List[str]:
        """生成风控建议"""
        suggestions = []
        for alert in alerts:
            if alert["level"] in ["HIGH", "CRITICAL"]:
                suggestions.append(f"⚠️ {alert['message']}")
        return suggestions

    def _ai_risk_analysis(self, holdings: List[Dict], market: Dict, alerts: List[Dict]) -> Dict:
        """AI深度风险分析"""
        return {"additional_alerts": []}

    # ==================== 降级方法 ====================

    def _fallback_briefing(self, selection: Optional[List[Dict]]) -> Dict:
        """降级盘前简报"""
        briefing = "今日选股结果:\n"
        if selection:
            for i, s in enumerate(selection[:5], 1):
                name = s.get("name", s.get("code", "未知"))
                score = s.get("score", "N/A")
                briefing += f"  {i}. {name} (评分:{score})\n"
        briefing += "\n[AI服务不可用，仅展示基础信息]"
        return {
            "briefing": briefing,
            "focus_stocks": (selection or [])[:3],
            "risk_alerts": [],
            "opportunity_alerts": [],
            "suggestions": [],
        }

    def _fallback_monitor(self, holdings: Optional[List[Dict]], signals: Optional[List[Dict]]) -> Dict:
        """降级盘中监控"""
        return {
            "status_summary": "[AI服务不可用]",
            "alerts": [],
            "action_suggestions": [],
            "watch_reminders": [],
        }

    def _fallback_review(self, trades: Optional[List[Dict]], signals: Optional[List[Dict]]) -> Dict:
        """降级盘后复盘"""
        return {
            "review_report": "[AI服务不可用]",
            "performance_summary": "",
            "lessons": [],
            "tomorrow_plan": "",
        }
