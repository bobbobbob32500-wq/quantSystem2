# -*- coding: utf-8 -*-
"""
上下文感知问答
理解当前页面上下文，提供针对性回答，支持多轮对话
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from src.core.logger import get_logger
from src.modules.ai_integration.llm_client import LLMClient

logger = get_logger("context_qa")


class ContextAwareQA:
    """上下文感知问答"""

    # 页面上下文映射
    PAGE_CONTEXT = {
        "overview": "总览页面：显示系统整体状态、候选池、信号、持仓概览",
        "stocks": "候选池页面：显示选股结果、候选股票列表",
        "signals": "信号页面：显示最新交易信号、信号历史",
        "trades": "持仓页面：显示虚拟持仓、盈亏情况",
        "strategy": "策略中心页面：显示策略列表、策略参数",
        "analytics": "复盘统计页面：显示策略表现统计",
        "settings": "设置页面：系统配置",
        "ai_assistant": "AI助手页面：与AI管家对话",
        "alert_center": "预警中心页面：显示各类预警",
    }

    def __init__(self, llm_client: Optional[LLMClient] = None):
        self.llm = llm_client
        self._conversation_history: List[Dict[str, str]] = []
        self._max_history = 20

    def answer_with_context(
        self,
        question: str,
        current_page: str = "",
        current_data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """基于上下文回答问题"""
        if not self.llm or not self.llm.is_available:
            return {
                "answer": "AI服务暂不可用，请检查配置后重试。",
                "source": "fallback",
                "suggestions": [],
            }

        # 构建上下文
        page_context = self.PAGE_CONTEXT.get(current_page, "")
        data_context = self._build_data_context(current_page, current_data)
        history_context = self._build_history_context()

        # 判断问题类型
        question_type = self._classify_question(question, current_page)

        # 构建提示词
        system_prompt = self._build_system_prompt(question_type, current_page)

        user_prompt = f"""## 当前页面
{page_context or '未知页面'}

## 页面数据
{data_context}

## 对话历史
{history_context or '无历史对话'}

## 用户问题
{question}

请基于以上上下文回答用户问题。如果问题与当前页面数据相关，请引用具体数据。"""

        try:
            answer = self.llm.chat(
                prompt=user_prompt,
                system=system_prompt,
            )

            # 记录对话
            self._add_to_history("user", question)
            self._add_to_history("assistant", answer)

            # 生成推荐问题
            suggestions = self._generate_suggestions(question_type, current_page, current_data)

            return {
                "answer": answer,
                "source": "ai",
                "question_type": question_type,
                "suggestions": suggestions,
                "context_page": current_page,
            }
        except Exception:
            logger.exception("上下文问答失败")
            return {
                "answer": "抱歉，AI回答失败，请稍后重试。",
                "source": "error",
                "suggestions": [],
            }

    def _classify_question(self, question: str, current_page: str) -> str:
        """分类问题类型"""
        q = question.lower()

        if any(kw in q for kw in ["怎么样", "分析", "看看", "如何"]):
            if current_page == "trades":
                return "position_analysis"
            elif current_page == "stocks":
                return "stock_analysis"
            elif current_page == "signals":
                return "signal_analysis"
            return "general_analysis"

        if any(kw in q for kw in ["买", "卖", "操作", "执行", "建仓"]):
            return "action_advice"

        if any(kw in q for kw in ["风险", "止损", "回撤"]):
            return "risk_question"

        if any(kw in q for kw in ["策略", "参数", "优化"]):
            return "strategy_question"

        if any(kw in q for kw in ["为什么", "原因", "逻辑"]):
            return "explanation"

        return "general"

    def _build_system_prompt(self, question_type: str, current_page: str) -> str:
        prompts = {
            "position_analysis": "你是持仓分析专家，请基于当前持仓数据给出专业分析。",
            "stock_analysis": "你是选股分析专家，请基于候选池数据解释选股逻辑。",
            "signal_analysis": "你是信号分析专家，请基于信号数据给出操作建议。",
            "action_advice": "你是交易执行顾问，请给出具体可操作的建议。",
            "risk_question": "你是风控专家，请评估风险并给出风控建议。",
            "strategy_question": "你是策略优化专家，请分析策略表现并给出优化建议。",
            "explanation": "你是量化系统解释者，请用通俗语言解释系统逻辑。",
            "general": "你是量化交易AI管家，请专业回答用户问题。",
        }
        return prompts.get(question_type, prompts["general"])

    def _build_data_context(self, page: str, data: Optional[Dict]) -> str:
        if not data:
            return "暂无页面数据"

        parts = []
        if page == "trades" and "open_trades" in data:
            trades = data["open_trades"]
            parts.append(f"当前持仓 {len(trades)} 只:")
            for t in trades[:5]:
                parts.append(f"  - {t.get('symbol', '')} {t.get('name', '')} 盈亏{t.get('pnl_pct', 0):.2f}%")

        elif page == "stocks" and "candidates" in data:
            candidates = data["candidates"]
            parts.append(f"候选池 {len(candidates)} 只:")
            for c in candidates[:5]:
                parts.append(f"  - {c.get('symbol', '')} {c.get('name', '')} 评分{c.get('score', 0):.1f}")

        elif page == "signals" and "signals" in data:
            signals = data["signals"]
            parts.append(f"最新信号 {len(signals)} 个:")
            for s in signals[:5]:
                parts.append(f"  - {s.get('symbol', '')} {s.get('signal_type', '')} {s.get('signal_time', '')}")

        return "\n".join(parts) if parts else "暂无相关数据"

    def _build_history_context(self) -> str:
        if not self._conversation_history:
            return ""
        recent = self._conversation_history[-6:]
        return "\n".join(f"{h['role']}: {h['content']}" for h in recent)

    def _add_to_history(self, role: str, content: str):
        self._conversation_history.append({"role": role, "content": content})
        if len(self._conversation_history) > self._max_history:
            self._conversation_history = self._conversation_history[-self._max_history:]

    def _generate_suggestions(self, question_type: str, page: str, data: Optional[Dict]) -> List[str]:
        suggestions = {
            "position_analysis": ["这只股票止损位在哪？", "整体仓位是否过重？", "哪些持仓需要关注？"],
            "stock_analysis": ["为什么选这只股票？", "候选池整体质量如何？", "哪只最值得关注？"],
            "signal_analysis": ["这个信号可靠吗？", "应该立即操作吗？", "还有类似信号吗？"],
            "action_advice": ["应该分批建仓吗？", "最佳执行时机？", "仓位建议多少？"],
            "risk_question": ["最大可能亏损多少？", "如何降低风险？", "当前风险水平？"],
            "strategy_question": ["策略参数需要调整吗？", "哪个策略表现最好？", "如何优化当前策略？"],
            "explanation": ["选股逻辑是什么？", "信号怎么产生的？", "评分怎么计算的？"],
            "general": ["市场分析", "选股逻辑", "风控策略", "策略优化"],
        }
        return suggestions.get(question_type, suggestions["general"])

    def clear_history(self):
        self._conversation_history.clear()

    def get_history(self, limit: int = 10) -> List[Dict]:
        return self._conversation_history[-limit:]
