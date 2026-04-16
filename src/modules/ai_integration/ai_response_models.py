#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
AI 输出结构化协议（Pydantic）

说明：
- 这些模型用于“高频关键场景”的稳定输出，便于前端/移动端卡片化展示与缓存。
- 字段尽量少而稳定，避免一上来就做成复杂嵌套，影响模型输出稳定性。
"""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class EvidenceItem(BaseModel):
    """证据条目：用于约束模型必须基于系统注入数据给出可核对的依据。"""

    key: str = Field(..., description="证据字段名，如 score、volume_ratio、breakout_price 等")
    value: Any = Field(None, description="证据字段值，来自系统数据/输入数据")
    note: Optional[str] = Field(None, description="简短解释，说明该证据如何支持结论")


class SelectionExplanation(BaseModel):
    summary: str = Field(..., description="一句话结论（结论先行）")
    key_points: List[str] = Field(default_factory=list, description="3-7 条要点，聚焦选股共性与因子驱动")
    risks: List[str] = Field(default_factory=list, description="1-5 条风险点")
    action_suggestions: List[str] = Field(default_factory=list, description="1-5 条可执行建议（跟踪/过滤/入场纪律）")
    focus_stocks: List[Dict[str, Any]] = Field(default_factory=list, description="最多 3 只重点关注股（从输入 stock_list 内选择）")
    evidence: List[EvidenceItem] = Field(default_factory=list, description="可核对的证据（必须来自输入数据）")


class SignalExplanation(BaseModel):
    summary: str = Field(..., description="一句话结论（是否参与/如何处理）")
    action: str = Field(..., description="BUY/HOLD/SELL/WATCH 之一")
    confidence: float = Field(..., ge=0.0, le=1.0, description="0-1 置信度（越高越确定）")
    key_points: List[str] = Field(default_factory=list, description="3-7 条信号解读要点")
    execution_advice: List[str] = Field(default_factory=list, description="执行建议：价格/仓位/止损/触发条件")
    risks: List[str] = Field(default_factory=list, description="风险提示")
    evidence: List[EvidenceItem] = Field(default_factory=list, description="引用输入信号字段的证据")


class MorningBriefingPayload(BaseModel):
    summary: str = Field(..., description="一句话盘前总览（结论先行）")
    data_checks: List[str] = Field(default_factory=list, description="数据检查结果与补救建议")
    market_view: List[str] = Field(default_factory=list, description="市场环境判断要点")
    position_advice: List[str] = Field(default_factory=list, description="仓位建议与纪律")
    focus_stocks: List[Dict[str, Any]] = Field(default_factory=list, description="最多 3 只重点关注股（来自输入 today_selection）")
    risk_alerts: List[str] = Field(default_factory=list, description="风险预警要点")
    action_suggestions: List[str] = Field(default_factory=list, description="开盘后优先动作（可执行）")
    evidence: List[EvidenceItem] = Field(default_factory=list, description="引用输入数据的证据")


class PostMarketReviewPayload(BaseModel):
    summary: str = Field(..., description="一句话复盘结论（结论先行）")
    performance_summary: List[str] = Field(default_factory=list, description="表现总结要点")
    what_went_well: List[str] = Field(default_factory=list, description="做对了什么（要点）")
    what_went_wrong: List[str] = Field(default_factory=list, description="做错了什么（要点）")
    lessons: List[str] = Field(default_factory=list, description="3-7 条经验教训")
    tomorrow_plan: List[str] = Field(default_factory=list, description="明日计划要点")
    risk_notes: List[str] = Field(default_factory=list, description="风险与改进方向")
    evidence: List[EvidenceItem] = Field(default_factory=list, description="引用输入数据的证据")

