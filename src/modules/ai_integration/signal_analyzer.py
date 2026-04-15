# -*- coding: utf-8 -*-
"""
信号分析器
利用大模型对交易信号进行深度解读
"""

from typing import Any, Dict, List, Optional

from src.core.logger import get_logger
from src.modules.ai_integration.llm_client import LLMClient

logger = get_logger("signal_analyzer")

SYSTEM_PROMPT = """你是一个专业的A股短线交易信号分析师。你的任务是：
1. 解读买卖信号的技术含义
2. 评估信号的有效性和可靠性
3. 分析后续可能的走势
4. 给出具体的操作建议

注意：你的分析仅供参考，不构成投资建议。所有交易决策需结合自身风险承受能力。"""


class SignalAnalyzer:
    """信号分析器 - 用大模型解读交易信号"""

    def __init__(self, llm_client: LLMClient):
        self.llm = llm_client

    def analyze_breakout_signal(
        self,
        stock_code: str,
        stock_name: str,
        signal_data: Dict,
    ) -> str:
        """
        分析突破信号

        Args:
            stock_code: 股票代码
            stock_name: 股票名称
            signal_data: 信号数据 {
                "price": 当前价格,
                "breakout_type": 突破类型,
                "breakout_price": 突破价位,
                "volume_ratio": 量比,
                "indicators": {技术指标},
                "trend": 趋势状态,
            }

        Returns:
            信号分析文本
        """
        if not self.llm.is_available:
            return self._fallback_analyze(stock_name, signal_data)

        prompt = f"""请分析以下股票的突破信号：

## 股票: {stock_name}({stock_code})
- 当前价格: {signal_data.get('price', 'N/A')}
- 突破类型: {signal_data.get('breakout_type', 'N/A')}
- 突破价位: {signal_data.get('breakout_price', 'N/A')}
- 量比: {signal_data.get('volume_ratio', 'N/A')}
- 趋势状态: {signal_data.get('trend', 'N/A')}

## 技术指标
{self._format_indicators(signal_data.get('indicators', {}))}

请从以下角度分析：
1. **突破有效性**：这次突破是否有效？判断依据是什么？
2. **量价配合**：成交量是否配合突破？量价关系如何？
3. **后续走势预判**：突破后可能的三种走势及概率
4. **操作建议**：如果参与，建议的入场时机、仓位和止损位
5. **风险提示**：需要特别注意的风险

请用简洁专业的中文回答。"""

        return self.llm.chat(prompt=prompt, system=SYSTEM_PROMPT)

    def analyze_sell_signal(
        self,
        stock_code: str,
        stock_name: str,
        signal_data: Dict,
        position_data: Optional[Dict] = None,
    ) -> str:
        """
        分析卖出信号

        Args:
            stock_code: 股票代码
            stock_name: 股票名称
            signal_data: 卖出信号数据
            position_data: 持仓数据

        Returns:
            卖出信号分析文本
        """
        if not self.llm.is_available:
            return f"{stock_name} 出现卖出信号: {signal_data.get('reason', 'N/A')}"

        position_text = self._format_position(position_data) if position_data else "无持仓信息"

        prompt = f"""请分析以下卖出信号：

## 股票: {stock_name}({stock_code})
- 卖出原因: {signal_data.get('reason', 'N/A')}
- 当前价格: {signal_data.get('price', 'N/A')}
- 信号类型: {signal_data.get('signal_type', 'N/A')}

## 持仓信息
{position_text}

## 技术指标
{self._format_indicators(signal_data.get('indicators', {}))}

请分析：
1. **卖出信号评估**：这个卖出信号是否合理？
2. **是否应该立即执行**：还是可以再观察？
3. **替代方案**：是否有其他操作选择（如减仓、移动止损等）？
4. **后续关注**：卖出后应关注什么？

请用简洁专业的中文回答。"""

        return self.llm.chat(prompt=prompt, system=SYSTEM_PROMPT)

    def analyze_market_gate(
        self,
        gate_status: Dict,
        index_data: Optional[Dict] = None,
    ) -> str:
        """
        分析市场闸门状态

        Args:
            gate_status: 闸门状态 {"regime": "NORMAL", "is_open": True, ...}
            index_data: 指数数据

        Returns:
            市场环境分析文本
        """
        if not self.llm.is_available:
            regime = gate_status.get("regime", "UNKNOWN")
            return f"当前市场状态: {regime}"

        prompt = f"""请分析当前市场环境：

## 市场闸门状态
- 市场体制: {gate_status.get('regime', 'N/A')}
- 闸门是否开放: {'是' if gate_status.get('is_open') else '否'}
- 建议仓位: {gate_status.get('position_ratio', 'N/A')}

## 指数数据
{self._format_index(index_data) if index_data else '未提供'}

请分析：
1. **市场环境判断**：当前市场处于什么阶段？
2. **操作策略建议**：在这种市场环境下应采取什么策略？
3. **仓位管理**：建议的仓位水平及调整方向
4. **风险关注**：需要关注的市场风险

请用简洁专业的中文回答。"""

        return self.llm.chat(prompt=prompt, system=SYSTEM_PROMPT)

    def _format_indicators(self, indicators: Dict) -> str:
        """格式化技术指标"""
        if not indicators:
            return "未提供技术指标"
        lines = []
        for k, v in indicators.items():
            if isinstance(v, float):
                lines.append(f"- {k}: {v:.4f}")
            else:
                lines.append(f"- {k}: {v}")
        return "\n".join(lines)

    def _format_position(self, position: Dict) -> str:
        """格式化持仓信息"""
        if not position:
            return "无持仓信息"
        lines = []
        for k, v in position.items():
            lines.append(f"- {k}: {v}")
        return "\n".join(lines)

    def _format_index(self, index_data: Dict) -> str:
        """格式化指数数据"""
        if not index_data:
            return "未提供指数数据"
        lines = []
        for k, v in index_data.items():
            lines.append(f"- {k}: {v}")
        return "\n".join(lines)

    def _fallback_analyze(self, stock_name: str, signal_data: Dict) -> str:
        """降级分析"""
        return (
            f"{stock_name} 出现{signal_data.get('breakout_type', '突破')}信号，"
            f"价格: {signal_data.get('price', 'N/A')}，"
            f"量比: {signal_data.get('volume_ratio', 'N/A')}\n"
            "[AI服务不可用，仅展示基础信号信息]"
        )
