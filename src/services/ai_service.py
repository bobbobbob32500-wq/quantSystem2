# -*- coding: utf-8 -*-
"""
AI服务层
统一管理AI模块的初始化和调用，供Web看板和API使用
"""

import os
import yaml
from typing import Any, Dict, List, Optional

from src.core.logger import get_logger
from src.modules.ai_integration.llm_client import LLMClient
from src.modules.ai_integration.stock_explainer import StockExplainer
from src.modules.ai_integration.signal_analyzer import SignalAnalyzer
from src.modules.ai_integration.news_sentiment import NewsSentimentAnalyzer
from src.modules.ai_integration.ai_assistant import AIAssistant

logger = get_logger("ai_service")


class AIService:
    """AI服务 - 统一入口"""

    _instance = None

    def __new__(cls, *args, **kwargs):
        """单例模式"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, config_path: Optional[str] = None):
        if hasattr(self, "_initialized"):
            return

        self._config = self._load_config(config_path)
        self._enabled = self._config.get("ai", {}).get("enabled", True)

        # 初始化LLM客户端
        ai_config = self._config.get("ai", {})
        provider = ai_config.get("provider", "ollama")
        models_config = ai_config.get("models", {})
        gen_config = ai_config.get("generation", {})

        # 根据provider选择配置
        if provider == "deepseek":
            provider_config = ai_config.get("deepseek", {})
            default_base_url = "https://api.deepseek.com/v1"
            default_model = "deepseek-chat"
            code_model = "deepseek-coder"
        else:
            provider_config = ai_config.get("ollama", {})
            default_base_url = "http://localhost:11434"
            default_model = "qwen2.5:7b"
            code_model = "mistral:7b"

        # API Key: 优先从环境变量读取, 其次从配置文件读取
        api_key_env = provider_config.get("api_key_env", "")
        api_key = os.environ.get(api_key_env, "") if api_key_env else ""
        if not api_key:
            api_key = provider_config.get("api_key", "")

        llm_config = {
            "provider": provider,
            "base_url": provider_config.get("base_url", default_base_url),
            "api_key": api_key,
            "default_model": models_config.get("default", default_model),
            "code_model": models_config.get("code", code_model),
            "timeout": provider_config.get("timeout", 120),
            "max_retries": provider_config.get("max_retries", 2),
            "retry_delay": provider_config.get("retry_delay", 3),
            "temperature": gen_config.get("temperature", 0.7),
            "max_tokens": gen_config.get("max_tokens", 2048),
        }

        self.llm = LLMClient(config=llm_config)
        self.stock_explainer = StockExplainer(self.llm)
        self.signal_analyzer = SignalAnalyzer(self.llm)
        self.news_analyzer = NewsSentimentAnalyzer(self.llm)
        self.assistant = AIAssistant(self.llm)

        self._initialized = True
        logger.info(f"AI服务初始化完成, 可用={self.is_available}, 模型={self.llm.installed_models}")

    def _load_config(self, config_path: Optional[str] = None) -> Dict:
        """加载AI配置"""
        if config_path is None:
            config_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                "config",
                "ai_config.yaml",
            )

        if os.path.exists(config_path):
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    return yaml.safe_load(f) or {}
            except Exception as e:
                logger.warning(f"AI配置加载失败: {e}，使用默认配置")
        return {"ai": {"enabled": True}}

    @property
    def is_available(self) -> bool:
        """AI服务是否可用"""
        return self._enabled and self.llm.is_available

    @property
    def is_enabled(self) -> bool:
        """AI功能是否启用"""
        return self._enabled

    def get_status(self) -> Dict[str, Any]:
        """获取AI服务状态"""
        return {
            "enabled": self._enabled,
            "available": self.is_available,
            "llm_status": self.llm.get_status(),
        }

    # === 选股解释 ===

    def explain_selection(
        self,
        stock_list: List[Dict],
        factors: Optional[Dict] = None,
        market_context: Optional[Dict] = None,
    ) -> str:
        """解释选股结果"""
        if not self._enabled:
            return "[AI功能已禁用]"
        return self.stock_explainer.explain_selection(stock_list, factors, market_context)

    def explain_single_stock(self, stock: Dict, factor_details: Optional[Dict] = None) -> str:
        """解释单只股票"""
        if not self._enabled:
            return "[AI功能已禁用]"
        return self.stock_explainer.explain_single_stock(stock, factor_details)

    # === 信号分析 ===

    def analyze_signal(self, stock_code: str, stock_name: str, signal_data: Dict) -> str:
        """分析交易信号"""
        if not self._enabled:
            return "[AI功能已禁用]"
        return self.signal_analyzer.analyze_breakout_signal(stock_code, stock_name, signal_data)

    def analyze_sell_signal(
        self,
        stock_code: str,
        stock_name: str,
        signal_data: Dict,
        position_data: Optional[Dict] = None,
    ) -> str:
        """分析卖出信号"""
        if not self._enabled:
            return "[AI功能已禁用]"
        return self.signal_analyzer.analyze_sell_signal(stock_code, stock_name, signal_data, position_data)

    # === 新闻分析 ===

    def analyze_news(
        self,
        news_list: List[Dict],
        holdings: Optional[List[Dict]] = None,
    ) -> str:
        """分析新闻影响"""
        if not self._enabled:
            return "[AI功能已禁用]"
        return self.news_analyzer.analyze_news_impact(news_list, holdings)

    # === AI助手 ===

    def chat(self, user_input: str, context: Optional[Dict] = None) -> str:
        """AI助手对话"""
        if not self._enabled:
            return "[AI功能已禁用]"
        return self.assistant.chat(user_input, context)

    def quick_ask(self, prompt_key: str, context: Optional[Dict] = None) -> str:
        """快速预设问答"""
        if not self._enabled:
            return "[AI功能已禁用]"
        return self.assistant.quick_ask(prompt_key, context)

    def generate_code(self, description: str, framework: str = "pandas") -> str:
        """生成策略代码"""
        if not self._enabled:
            return "[AI功能已禁用]"
        return self.assistant.generate_strategy_code(description, framework)

    def clear_chat_history(self):
        """清除对话历史"""
        self.assistant.clear_history()

    def get_chat_history(self) -> List[Dict]:
        """获取对话历史"""
        return self.assistant.get_history()
