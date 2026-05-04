# -*- coding: utf-8 -*-
"""
量化知识库
内置量化交易知识，支持查询技术指标、交易策略、风控方法
"""

from typing import Any, Dict, List, Optional

from src.core.logger import get_logger
from src.modules.ai_integration.llm_client import LLMClient

logger = get_logger("knowledge_base")


# 内置知识库
BUILTIN_KNOWLEDGE = {
    "macd": {
        "title": "MACD指标",
        "category": "technical_indicator",
        "content": """## MACD指标（移动平均收敛散度）

### 基本概念
MACD由快线(DIF)、慢线(DEA)和柱状图组成。
- DIF = EMA(12) - EMA(26)
- DEA = EMA(DIF, 9)
- 柱状图 = 2 * (DIF - DEA)

### 使用方法
1. **金叉/死叉**: DIF上穿DEA为金叉(买入信号)，下穿为死叉(卖出信号)
2. **背离**: 价格创新高但MACD不创新高 → 顶背离(看跌)
3. **零轴**: DIF在零轴上方为多头市场，下方为空头市场

### 实战要点
- 零轴上方的金叉比零轴下方的金叉更可靠
- 背离信号比金叉/死叉更可靠
- 周线MACD比日线MACD更稳定""",
    },
    "rsi": {
        "title": "RSI指标",
        "category": "technical_indicator",
        "content": """## RSI指标（相对强弱指数）

### 基本概念
RSI衡量一段时间内上涨幅度占总幅度的比例，范围0-100。
- RSI = 100 - 100/(1 + 平均上涨/平均下跌)
- 常用周期: 6日、12日、14日

### 使用方法
1. **超买超卖**: RSI > 70为超买，RSI < 30为超卖
2. **背离**: 与价格走势相反的背离信号
3. **中轴线**: RSI=50为多空分界线

### 实战要点
- 强势市场中RSI可能长期处于70以上
- 超买不等于立即下跌，需结合趋势判断
- 多周期RSI共振信号更可靠""",
    },
    "stop_loss": {
        "title": "止损策略",
        "category": "risk_management",
        "content": """## 止损策略

### 常见止损方法
1. **固定比例止损**: 亏损达到X%时止损（常用5%）
2. **技术止损**: 跌破支撑位、均线时止损
3. **ATR止损**: 止损位 = 买入价 - N*ATR（常用2倍ATR）
4. **时间止损**: 持仓超过N天未盈利则止损

### 止损原则
- 入场前必须设定止损位
- 止损位不应随意移动（只能向盈利方向移动）
- 止损是保护资金，不是承认失败
- 执行止损要坚决，不要抱有侥幸心理

### 常见错误
- 亏损扩大后不止损，期待回本
- 频繁调整止损位
- 止损后立即追回（情绪化交易）""",
    },
    "position_sizing": {
        "title": "仓位管理",
        "category": "risk_management",
        "content": """## 仓位管理

### 常见方法
1. **固定比例法**: 每次投入总资金的固定比例
2. **凯利公式**: f = (bp - q) / b（b=赔率，p=胜率，q=1-p）
3. **风险平价**: 按波动率倒数分配仓位
4. **等风险法**: 每只股票的风险敞口相同

### 仓位原则
- 单只股票不超过总仓位的30%
- 总仓位根据市场环境调整（牛市重仓，熊市轻仓）
- 分批建仓，不要一次性满仓
- 盈利加仓，亏损减仓

### 市场环境对应
- 牛市: 总仓位60-80%
- 震荡市: 总仓位30-50%
- 熊市: 总仓位10-20%或空仓""",
    },
    "breakout": {
        "title": "突破策略",
        "category": "strategy",
        "content": """## 突破策略

### 核心逻辑
识别价格突破关键阻力位的股票，在突破确认后介入。

### 选股条件
1. 价格突破N日高点（常用20/60日）
2. 突破时成交量放大（1.5倍均量以上）
3. 突破前有缩量整理过程
4. 均线多头排列

### 入场时机
- 首次突破：轻仓试探
- 回踩确认：加仓
- 二次突破：满仓

### 风险控制
- 止损设在突破位下方2-3%
- 突破3日内未继续上涨则减仓
- 注意假突破（放量突破后回落）""",
    },
    "secondary_launch": {
        "title": "二次启动策略",
        "category": "strategy",
        "content": """## 二次启动策略

### 核心逻辑
捕捉涨停后缩量回踩、再次启动的股票。

### 选股条件
1. 近期有涨停记录（5-10日内）
2. 回调缩量（量比<0.8）
3. 回调幅度适中（5-15%）
4. 基本面无重大利空

### 入场时机
- 缩量回踩至支撑位
- 分时图出现企稳信号
- 板块整体走强时优先

### 风险控制
- 止损设在回踩低点下方2%
- 若二次启动失败（冲高回落），立即离场
- 注意大盘系统性风险""",
    },
}


class QuantKnowledgeBase:
    """量化知识库"""

    def __init__(self, llm_client: Optional[LLMClient] = None):
        self.llm = llm_client
        self._knowledge = dict(BUILTIN_KNOWLEDGE)
        self._search_index = self._build_search_index()

    def _build_search_index(self) -> Dict[str, List[str]]:
        """构建搜索索引"""
        index: Dict[str, List[str]] = {}
        for key, article in self._knowledge.items():
            title = article.get("title", "").lower()
            category = article.get("category", "").lower()
            content = article.get("content", "").lower()

            words = set()
            words.update(title.split())
            words.update(category.split("_"))
            words.update(content.split()[:50])

            for word in words:
                if len(word) >= 2:
                    index.setdefault(word, []).append(key)
        return index

    def query(self, topic: str) -> Optional[Dict[str, Any]]:
        """查询知识"""
        # 精确匹配
        topic_lower = topic.lower().replace(" ", "_")
        if topic_lower in self._knowledge:
            return self._knowledge[topic_lower]

        # 模糊搜索
        matches = self._search(topic)
        if matches:
            best_key = matches[0]
            return self._knowledge[best_key]

        # AI回答
        return self._ai_query(topic)

    def _search(self, query: str) -> List[str]:
        """搜索知识库"""
        words = query.lower().split()
        scores: Dict[str, int] = {}

        for word in words:
            for key in self._search_index.get(word, []):
                scores[key] = scores.get(key, 0) + 1

        return sorted(scores.keys(), key=lambda k: scores[k], reverse=True)

    def _ai_query(self, topic: str) -> Optional[Dict[str, Any]]:
        """AI回答知识问题"""
        if not self.llm or not self.llm.is_available:
            return None

        prompt = f"""请解释以下量化交易相关概念：

## 问题: {topic}

请用简洁专业的中文回答，包含：
1. 基本概念
2. 使用方法
3. 实战要点
4. 注意事项"""

        try:
            answer = self.llm.chat(
                prompt=prompt,
                system="你是量化交易知识专家，擅长解释技术指标、交易策略和风控方法。",
            )
            return {
                "title": topic,
                "category": "ai_generated",
                "content": answer,
            }
        except Exception:
            logger.exception("AI知识查询失败")
            return None

    def list_topics(self, category: Optional[str] = None) -> List[Dict[str, str]]:
        """列出所有知识主题"""
        result = []
        for key, article in self._knowledge.items():
            if category and article.get("category") != category:
                continue
            result.append({
                "key": key,
                "title": article.get("title", ""),
                "category": article.get("category", ""),
            })
        return result

    def get_categories(self) -> List[str]:
        """获取所有分类"""
        return list(set(a.get("category", "") for a in self._knowledge.values()))

    def add_knowledge(self, key: str, title: str, category: str, content: str):
        """添加知识"""
        self._knowledge[key] = {
            "title": title,
            "category": category,
            "content": content,
        }
        self._search_index = self._build_search_index()
