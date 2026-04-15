# -*- coding: utf-8 -*-
"""
AI助手
提供自然语言交互的智能问答能力
支持: 股票查询、策略咨询、市场分析、代码生成
"""

import json
from typing import Any, Dict, List, Optional

from src.core.logger import get_logger
from src.modules.ai_integration.llm_client import LLMClient

logger = get_logger("ai_assistant")

SYSTEM_PROMPT = """你是"A股量化交易辅助系统"的AI助手。你可以帮助用户：
1. 解答关于A股交易、技术分析、量化策略的问题
2. 分析股票的技术形态和基本面
3. 生成和优化量化交易策略代码
4. 解释系统选股和信号逻辑
5. 提供市场分析和风险提示

你熟悉以下领域：
- A股交易规则和特点（T+1、涨跌停板等）
- 技术分析（MA/MACD/KDJ/RSI/BOLL等）
- 量化策略（多因子选股、动量策略、均值回归等）
- Python量化编程（pandas/numpy/backtrader等）
- 风险管理（止损、仓位控制、回撤控制等）

回答要求：
- 使用中文回答
- 专业但通俗易懂
- 给出具体可操作的建议
- 明确标注风险提示
- 不构成投资建议的免责声明"""

# 预设问答模板
QUICK_PROMPTS = {
    "市场分析": "请分析当前A股市场环境，包括大盘趋势、市场情绪、板块轮动情况，并给出操作建议。",
    "选股逻辑": "请解释本系统的选股逻辑，包括Alpha158因子、IC加权方法、五层过滤机制。",
    "风控策略": "请介绍短线交易的风控策略，包括止损设置、仓位管理、最大回撤控制。",
    "策略优化": "请建议如何优化当前的突破策略，包括参数调优、信号过滤、出场优化。",
}


class AIAssistant:
    """AI助手 - 自然语言交互"""

    def __init__(self, llm_client: LLMClient):
        self.llm = llm_client
        self._conversation_history: List[Dict] = []

    def chat(
        self,
        user_input: str,
        context: Optional[Dict] = None,
        clear_history: bool = False,
    ) -> str:
        """
        与AI助手对话

        Args:
            user_input: 用户输入
            context: 上下文信息（如当前持仓、选股结果等）
            clear_history: 是否清除对话历史

        Returns:
            AI回复文本
        """
        if not self.llm.is_available:
            return "[AI服务不可用] 请确保Ollama已安装并运行。安装方法: 访问 https://ollama.com/download"

        if clear_history:
            self._conversation_history = []

        # 构建增强提示
        enhanced_input = user_input
        if context:
            context_text = self._format_context(context)
            if context_text:
                enhanced_input = f"[当前系统上下文]\n{context_text}\n\n[用户问题]\n{user_input}"

        # 调用大模型
        response = self.llm.chat(
            prompt=enhanced_input,
            system=SYSTEM_PROMPT,
            history=self._conversation_history[-10:],  # 保留最近10轮对话
        )

        # 更新对话历史
        self._conversation_history.append({"role": "user", "content": user_input})
        self._conversation_history.append({"role": "assistant", "content": response})

        # 限制历史长度
        if len(self._conversation_history) > 20:
            self._conversation_history = self._conversation_history[-20:]

        return response

    def quick_ask(self, prompt_key: str, context: Optional[Dict] = None) -> str:
        """
        快速预设问答

        Args:
            prompt_key: 预设问题key
            context: 上下文信息

        Returns:
            AI回复文本
        """
        prompt = QUICK_PROMPTS.get(prompt_key)
        if not prompt:
            return f"未知的预设问题: {prompt_key}，可选: {list(QUICK_PROMPTS.keys())}"
        return self.chat(prompt, context=context, clear_history=True)

    def generate_strategy_code(
        self,
        strategy_description: str,
        framework: str = "pandas",
    ) -> str:
        """
        生成量化策略代码

        Args:
            strategy_description: 策略描述
            framework: 代码框架 (pandas/backtrader/vnpy)

        Returns:
            生成的代码
        """
        if not self.llm.is_available:
            return "[AI服务不可用]"

        prompt = f"""请根据以下策略描述生成Python量化交易代码：

## 策略描述
{strategy_description}

## 代码框架
使用 {framework} 框架实现

## 要求
1. 包含完整的数据获取逻辑
2. 包含信号生成逻辑
3. 包含回测逻辑
4. 包含风险控制（止损、仓位管理）
5. 代码注释清晰
6. 使用中文注释

请生成完整可运行的代码。"""

        return self.llm.chat_with_code(prompt=prompt)

    def explain_indicator(self, indicator_name: str, value: Any = None) -> str:
        """
        解释技术指标

        Args:
            indicator_name: 指标名称
            value: 指标值

        Returns:
            指标解释文本
        """
        if not self.llm.is_available:
            return f"{indicator_name}: {value}"

        value_text = f"，当前值: {value}" if value is not None else ""
        prompt = f"""请解释技术指标 {indicator_name}{value_text}：

1. **计算方法**：该指标如何计算？
2. **含义解读**：当前值代表什么含义？
3. **使用方法**：在实战中如何使用？
4. **注意事项**：使用该指标需要注意什么？

请用简洁专业的中文回答。"""

        return self.chat(prompt, clear_history=True)

    def clear_history(self):
        """清除对话历史"""
        self._conversation_history = []

    def get_history(self) -> List[Dict]:
        """获取对话历史"""
        return self._conversation_history.copy()

    def _format_context(self, context: Dict) -> str:
        """格式化上下文信息"""
        lines = []
        if "holdings" in context:
            lines.append("当前持仓:")
            for h in context["holdings"]:
                lines.append(f"  - {h.get('name', '')}({h.get('code', '')}) 仓位:{h.get('position', 0):.1%}")
        if "selected_stocks" in context:
            lines.append("今日选股:")
            for s in context["selected_stocks"]:
                lines.append(f"  - {s.get('name', '')}({s.get('code', '')}) 评分:{s.get('score', 'N/A')}")
        if "market_status" in context:
            lines.append(f"市场状态: {context['market_status']}")
        if "signals" in context:
            lines.append(f"活跃信号: {len(context['signals'])}个")
        return "\n".join(lines)
