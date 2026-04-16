# -*- coding: utf-8 -*-
"""
选股解释器
利用大模型对选股结果进行自然语言解释
"""

import json
from typing import Any, Dict, List, Optional

from src.core.logger import get_logger
from src.modules.ai_integration.llm_client import LLMClient
from src.modules.ai_integration.ai_response_models import SelectionExplanation
from src.modules.ai_integration.structured_output import llm_chat_structured

logger = get_logger("stock_explainer")

# 系统提示词
SYSTEM_PROMPT = """你是一个专业的A股量化分析助手。你的任务是：
1. 用通俗易懂的中文解释选股结果
2. 分析主要驱动因子和逻辑
3. 提供风险提示
4. 给出操作建议参考

注意：你的分析仅供参考，不构成投资建议。"""


class StockExplainer:
    """选股解释器 - 用大模型解释选股逻辑"""

    def __init__(
        self,
        llm_client: LLMClient,
        system_prompt: Optional[str] = None,
        default_temperature: Optional[float] = None,
        default_max_tokens: Optional[int] = None,
        default_timeout: Optional[float] = None,
    ):
        self.llm = llm_client
        self._system_prompt = system_prompt or SYSTEM_PROMPT
        self._default_temperature = default_temperature
        self._default_max_tokens = default_max_tokens
        self._default_timeout = default_timeout

    def explain_selection(
        self,
        stock_list: List[Dict],
        factors: Optional[Dict] = None,
        market_context: Optional[Dict] = None,
    ) -> str:
        """
        解释选股结果

        Args:
            stock_list: 选中的股票列表 [{"code": "000001.SZ", "name": "平安银行", "score": 85.5, ...}]
            factors: 关键因子信息 {"trend": 0.26, "momentum": 0.33, ...}
            market_context: 市场环境 {"index_trend": "震荡", "market_breadth": 0.55, ...}

        Returns:
            选股解释文本
        """
        if not self.llm.is_available:
            return self._fallback_explain(stock_list, factors)

        structured = self.explain_selection_structured(stock_list, factors=factors, market_context=market_context)
        if structured:
            return self._render_structured_selection(structured)

        # 格式化股票信息
        stocks_text = self._format_stocks(stock_list)
        factors_text = self._format_factors(factors) if factors else "未提供因子信息"
        market_text = self._format_market(market_context) if market_context else "未提供市场环境"

        prompt = f"""请分析以下今日选股结果：

## 选中股票
{stocks_text}

## 因子权重
{factors_text}

## 市场环境
{market_text}

请从以下角度进行分析：
1. **选股逻辑解读**：为什么选中这些股票？主要驱动因子是什么？
2. **共性特征**：这些股票有什么共同特征？（行业、市值、技术形态等）
3. **风险提示**：当前选股可能面临的风险
4. **操作建议**：针对这些股票的跟踪建议

请用简洁专业的中文回答。"""

        return self.llm.chat(
            prompt=prompt,
            system=self._system_prompt,
            temperature=self._default_temperature,
            max_tokens=self._default_max_tokens,
            timeout=self._default_timeout,
        )

    def explain_selection_structured(
        self,
        stock_list: List[Dict],
        factors: Optional[Dict] = None,
        market_context: Optional[Dict] = None,
    ) -> Optional[SelectionExplanation]:
        """结构化解释（返回 Pydantic 对象；失败则返回 None）"""
        if not self.llm.is_available:
            return None

        stocks_text = self._format_stocks(stock_list)
        factors_text = self._format_factors(factors) if factors else "未提供因子信息"
        market_text = self._format_market(market_context) if market_context else "未提供市场环境"

        prompt = f"""你需要对“选股结果”做结构化解释。

【输入-选中股票】（仅供引用，不得编造不在此列表中的股票）
{stocks_text}

【输入-因子权重】
{factors_text}

【输入-市场环境】
{market_text}

输出要求：
1) 结论先行，尽量短
2) 关键点 3-7 条，避免空话
3) focus_stocks 只能从输入 stock_list 中选择，最多 3 只；每只股票至少包含 code/name/score（若输入里没有则为空）
4) evidence 必须引用输入里出现过的字段和值（例如 score、行业、因子权重、市场环境字段等），禁止杜撰
"""

        obj, _raw = llm_chat_structured(
            self.llm,
            prompt=prompt,
            system=self._system_prompt,
            model_cls=SelectionExplanation,
            temperature=self._default_temperature if self._default_temperature is not None else 0.3,
            max_tokens=self._default_max_tokens if self._default_max_tokens is not None else 1200,
            timeout=self._default_timeout,
            max_fix_attempts=1,
        )
        return obj

    def explain_single_stock(
        self,
        stock: Dict,
        factor_details: Optional[Dict] = None,
    ) -> str:
        """
        解释单只股票的选股原因

        Args:
            stock: 股票信息 {"code": "000001.SZ", "name": "平安银行", "score": 85.5, ...}
            factor_details: 因子详情 {"MA30": 0.8, "ROC30": 0.6, ...}

        Returns:
            单股解释文本
        """
        if not self.llm.is_available:
            return f"选中 {stock.get('name', stock.get('code', '未知'))}，评分: {stock.get('score', 'N/A')}"

        stock_text = self._format_stocks([stock])
        factors_text = self._format_factor_details(factor_details) if factor_details else ""

        prompt = f"""请详细分析以下股票的选股原因：

## 股票信息
{stock_text}

{factors_text}

请分析：
1. **入选原因**：为什么这只股票被选中？
2. **核心优势**：主要技术/基本面优势
3. **潜在风险**：需要注意的风险点
4. **关注要点**：后续应关注什么？

请用简洁专业的中文回答。"""

        return self.llm.chat(
            prompt=prompt,
            system=self._system_prompt,
            temperature=self._default_temperature,
            max_tokens=self._default_max_tokens,
            timeout=self._default_timeout,
        )

    def _render_structured_selection(self, payload: SelectionExplanation) -> str:
        lines = []
        lines.append(f"【结论】{payload.summary}".strip())
        if payload.key_points:
            lines.append("\n【要点】")
            for item in payload.key_points[:7]:
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
        if payload.action_suggestions:
            lines.append("\n【操作建议】")
            for item in payload.action_suggestions[:5]:
                lines.append(f"- {item}")
        if payload.risks:
            lines.append("\n【风险提示】")
            for item in payload.risks[:5]:
                lines.append(f"- {item}")
        if payload.evidence:
            lines.append("\n【证据】")
            for ev in payload.evidence[:6]:
                note = f"（{ev.note}）" if ev.note else ""
                lines.append(f"- {ev.key}: {ev.value}{note}")
        lines.append("\n[免责声明] 以上内容仅供参考，不构成投资建议。")
        return "\n".join(lines)

    def _format_stocks(self, stock_list: List[Dict]) -> str:
        """格式化股票列表"""
        lines = []
        for i, s in enumerate(stock_list, 1):
            code = s.get("code", "未知")
            name = s.get("name", "未知")
            score = s.get("score", s.get("total_score", "N/A"))
            industry = s.get("industry", "")
            lines.append(f"{i}. {name}({code}) 评分:{score}" + (f" 行业:{industry}" if industry else ""))
        return "\n".join(lines)

    def _format_factors(self, factors: Dict) -> str:
        """格式化因子权重"""
        lines = []
        for k, v in factors.items():
            if isinstance(v, (int, float)):
                lines.append(f"- {k}: {v:.4f}")
            else:
                lines.append(f"- {k}: {v}")
        return "\n".join(lines)

    def _format_factor_details(self, details: Dict) -> str:
        """格式化因子详情"""
        if not details:
            return ""
        lines = ["## 因子详情"]
        for k, v in details.items():
            if isinstance(v, (int, float)):
                lines.append(f"- {k}: {v:.4f}")
            else:
                lines.append(f"- {k}: {v}")
        return "\n".join(lines)

    def _format_market(self, context: Dict) -> str:
        """格式化市场环境"""
        lines = []
        for k, v in context.items():
            lines.append(f"- {k}: {v}")
        return "\n".join(lines)

    def _fallback_explain(self, stock_list: List[Dict], factors: Optional[Dict]) -> str:
        """降级解释（大模型不可用时）"""
        lines = ["今日选股结果："]
        for i, s in enumerate(stock_list, 1):
            name = s.get("name", s.get("code", "未知"))
            score = s.get("score", s.get("total_score", "N/A"))
            lines.append(f"  {i}. {name} (评分: {score})")
        if factors:
            lines.append("\n主要因子权重：")
            for k, v in factors.items():
                if isinstance(v, (int, float)):
                    lines.append(f"  - {k}: {v:.2%}")
        lines.append("\n[AI服务不可用，仅展示基础信息]")
        return "\n".join(lines)
