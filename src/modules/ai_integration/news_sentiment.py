# -*- coding: utf-8 -*-
"""
新闻情感分析器
利用大模型分析财经新闻对持仓股票的影响
"""

from typing import Any, Dict, List, Optional

from src.core.logger import get_logger
from src.modules.ai_integration.llm_client import LLMClient

logger = get_logger("news_sentiment")

SYSTEM_PROMPT = """你是一个专业的A股财经新闻分析师。你的任务是：
1. 分析财经新闻对股票的影响
2. 判断新闻情感倾向（正面/负面/中性）
3. 评估影响程度和持续时间
4. 给出持仓调整建议

注意：你的分析仅供参考，不构成投资建议。"""


class NewsSentimentAnalyzer:
    """新闻情感分析器"""

    def __init__(self, llm_client: LLMClient):
        self.llm = llm_client

    def analyze_news_impact(
        self,
        news_list: List[Dict],
        holdings: Optional[List[Dict]] = None,
    ) -> str:
        """
        分析新闻对持仓的影响

        Args:
            news_list: 新闻列表 [{"title": "...", "content": "...", "source": "...", "time": "..."}]
            holdings: 持仓列表 [{"code": "000001.SZ", "name": "平安银行", "position": 0.3, ...}]

        Returns:
            新闻影响分析文本
        """
        if not self.llm.is_available:
            return self._fallback_analyze(news_list)

        news_text = self._format_news(news_list)
        holdings_text = self._format_holdings(holdings) if holdings else "无持仓信息"

        prompt = f"""请分析以下财经新闻对持仓股票的影响：

## 当前持仓
{holdings_text}

## 最新财经新闻
{news_text}

请分析：
1. **重要新闻筛选**：哪些新闻可能影响持仓股票？
2. **情感判断**：对每只受影响股票判断正面/负面/中性
3. **影响程度**：评估影响程度（强/中/弱）和持续时间（短期/中期）
4. **操作建议**：是否需要调整仓位？具体建议
5. **风险预警**：需要特别关注的风险

请用简洁专业的中文回答。"""

        return self.llm.chat(prompt=prompt, system=SYSTEM_PROMPT)

    def analyze_single_news(
        self,
        news: Dict,
        target_stocks: Optional[List[str]] = None,
    ) -> Dict:
        """
        分析单条新闻的情感和影响

        Args:
            news: 新闻信息 {"title": "...", "content": "..."}
            target_stocks: 需要关注的股票代码列表

        Returns:
            分析结果 {"sentiment": "positive/negative/neutral", "impact_stocks": [...], "analysis": "..."}
        """
        if not self.llm.is_available:
            return {
                "sentiment": "unknown",
                "impact_stocks": [],
                "analysis": "[AI服务不可用]",
            }

        title = news.get("title", "")
        content = news.get("content", "")
        stocks_text = f"关注股票: {', '.join(target_stocks)}" if target_stocks else ""

        prompt = f"""请分析以下财经新闻：

## 新闻标题
{title}

## 新闻内容
{content}

{stocks_text}

请按以下格式回答：
- 情感倾向: [正面/负面/中性]
- 影响股票: [列出可能受影响的股票代码]
- 影响程度: [强/中/弱]
- 持续时间: [短期/中期/长期]
- 分析说明: [简要分析原因]"""

        analysis = self.llm.chat(prompt=prompt, system=SYSTEM_PROMPT)

        # 尝试解析情感
        sentiment = "neutral"
        if "正面" in analysis[:50]:
            sentiment = "positive"
        elif "负面" in analysis[:50]:
            sentiment = "negative"

        return {
            "sentiment": sentiment,
            "impact_stocks": target_stocks or [],
            "analysis": analysis,
        }

    def batch_analyze_news(
        self,
        news_list: List[Dict],
        stock_code: str,
    ) -> str:
        """
        批量分析与某只股票相关的新闻

        Args:
            news_list: 相关新闻列表
            stock_code: 股票代码

        Returns:
            综合分析文本
        """
        if not self.llm.is_available:
            return f"共{len(news_list)}条相关新闻 [AI服务不可用]"

        news_text = self._format_news(news_list)

        prompt = f"""请综合分析以下与股票 {stock_code} 相关的新闻：

{news_text}

请给出：
1. **整体情感倾向**：综合判断正面/负面/中性
2. **关键信息提取**：最重要的3条信息
3. **对股价影响预判**：短期可能的影响方向
4. **操作建议**：基于新闻面是否需要调整

请用简洁专业的中文回答。"""

        return self.llm.chat(prompt=prompt, system=SYSTEM_PROMPT)

    def _format_news(self, news_list: List[Dict]) -> str:
        """格式化新闻列表"""
        if not news_list:
            return "暂无新闻"
        lines = []
        for i, n in enumerate(news_list[:10], 1):  # 最多10条
            title = n.get("title", "无标题")
            source = n.get("source", "")
            time_str = n.get("time", "")
            lines.append(f"{i}. [{time_str}] {title}" + (f" - {source}" if source else ""))
        if len(news_list) > 10:
            lines.append(f"... 还有{len(news_list) - 10}条新闻")
        return "\n".join(lines)

    def _format_holdings(self, holdings: List[Dict]) -> str:
        """格式化持仓"""
        if not holdings:
            return "当前无持仓"
        lines = []
        for h in holdings:
            code = h.get("code", "未知")
            name = h.get("name", "未知")
            pos = h.get("position", 0)
            pnl = h.get("pnl_pct", "N/A")
            lines.append(f"- {name}({code}) 仓位:{pos:.1%} 盈亏:{pnl}")
        return "\n".join(lines)

    def _fallback_analyze(self, news_list: List[Dict]) -> str:
        """降级分析"""
        if not news_list:
            return "暂无新闻"
        lines = [f"共{len(news_list)}条新闻："]
        for i, n in enumerate(news_list[:5], 1):
            lines.append(f"  {i}. {n.get('title', '无标题')}")
        lines.append("[AI服务不可用，仅展示新闻标题]")
        return "\n".join(lines)
