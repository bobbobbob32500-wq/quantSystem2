# -*- coding: utf-8 -*-
"""
信号分析器
利用大模型对交易信号进行深度解读
"""

import json
from typing import Any, Dict, List, Optional

from src.core.logger import get_logger
from src.modules.ai_integration.llm_client import LLMClient
from src.modules.ai_integration.ai_response_models import SignalExplanation
from src.modules.ai_integration.structured_output import llm_chat_structured

logger = get_logger("signal_analyzer")

SYSTEM_PROMPT = """你是一个专业的A股短线交易信号分析师。你的任务是：
1. 解读买卖信号的技术含义
2. 评估信号的有效性和可靠性
3. 分析后续可能的走势
4. 给出具体的操作建议

注意：你的分析仅供参考，不构成投资建议。所有交易决策需结合自身风险承受能力。"""


class SignalAnalyzer:
    """信号分析器 - 用大模型解读交易信号"""

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

        structured = self.analyze_breakout_signal_structured(stock_code, stock_name, signal_data)
        if structured:
            return self._render_structured_signal(structured)

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

        return self.llm.chat(
            prompt=prompt,
            system=self._system_prompt,
            temperature=self._default_temperature,
            max_tokens=self._default_max_tokens,
            timeout=self._default_timeout,
        )

    def analyze_breakout_signal_structured(
        self,
        stock_code: str,
        stock_name: str,
        signal_data: Dict,
    ) -> Optional[SignalExplanation]:
        """结构化分析突破信号（失败返回 None）"""
        if not self.llm.is_available:
            return None

        indicators = signal_data.get("indicators", {}) if isinstance(signal_data.get("indicators", {}), dict) else {}
        prompt = f"""你需要对“突破信号”做结构化解读。

【输入-股票】
- name: {stock_name}
- code: {stock_code}

【输入-信号字段】（只能引用这些字段，禁止编造）
{json.dumps(signal_data, ensure_ascii=False, indent=2)[:3000]}

输出要求：
1) action 只能取 BUY/HOLD/SELL/WATCH
2) confidence 取 0-1 小数
3) execution_advice 给出 1-5 条可执行建议（仓位/止损/触发条件）
4) evidence 必须引用 signal_data 里出现过的字段和值（如 price、breakout_price、volume_ratio、trend、indicators 等）
"""

        obj, _raw = llm_chat_structured(
            self.llm,
            prompt=prompt,
            system=self._system_prompt,
            model_cls=SignalExplanation,
            temperature=self._default_temperature if self._default_temperature is not None else 0.3,
            max_tokens=self._default_max_tokens if self._default_max_tokens is not None else 1000,
            timeout=self._default_timeout,
            max_fix_attempts=1,
        )
        return obj

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

        return self.llm.chat(
            prompt=prompt,
            system=self._system_prompt,
            temperature=self._default_temperature,
            max_tokens=self._default_max_tokens,
            timeout=self._default_timeout,
        )

    def _render_structured_signal(self, payload: SignalExplanation) -> str:
        lines = []
        head = f"【结论】{payload.summary}".strip()
        lines.append(head)
        lines.append(f"【建议动作】{payload.action}（置信度:{payload.confidence:.2f}）")
        if payload.key_points:
            lines.append("\n【要点】")
            for item in payload.key_points[:7]:
                lines.append(f"- {item}")
        if payload.execution_advice:
            lines.append("\n【执行建议】")
            for item in payload.execution_advice[:5]:
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

        return self.llm.chat(
            prompt=prompt,
            system=self._system_prompt,
            temperature=self._default_temperature,
            max_tokens=self._default_max_tokens,
            timeout=self._default_timeout,
        )

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
