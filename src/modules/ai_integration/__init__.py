# -*- coding: utf-8 -*-
"""
AI集成模块
将本地大模型能力嵌入量化交易辅助系统
支持: 选股解释、信号分析、新闻情感分析、财报分析、AI助手
"""

from src.modules.ai_integration.llm_client import LLMClient
from src.modules.ai_integration.stock_explainer import StockExplainer
from src.modules.ai_integration.signal_analyzer import SignalAnalyzer
from src.modules.ai_integration.news_sentiment import NewsSentimentAnalyzer
from src.modules.ai_integration.ai_assistant import AIAssistant
from src.modules.ai_integration.ai_butler import AIButler

__all__ = [
    "LLMClient",
    "StockExplainer",
    "SignalAnalyzer",
    "NewsSentimentAnalyzer",
    "AIAssistant",
    "AIButler",
]
