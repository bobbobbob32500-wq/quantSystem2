# -*- coding: utf-8 -*-
"""
选股解释器
利用大模型对选股结果进行自然语言解释
"""

from typing import Any, Dict, List, Optional

from src.core.logger import get_logger
from src.modules.ai_integration.llm_client import LLMClient

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

    def __init__(self, llm_client: LLMClient):
        self.llm = llm_client

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

        return self.llm.chat(prompt=prompt, system=SYSTEM_PROMPT)

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

        return self.llm.chat(prompt=prompt, system=SYSTEM_PROMPT)

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
