# -*- coding: utf-8 -*-
"""
AI服务层
统一管理AI模块的初始化和调用，供Web看板和API使用
"""

import os
import json
import hashlib
import yaml
from typing import Any, Dict, List, Optional

from src.core.logger import get_logger
from src.modules.ai_integration.llm_client import LLMClient
from src.modules.ai_integration.conversation_store import (
    ConversationStore,
    ConversationStoreConfig,
    default_conversation_db_path,
    trim_history_by_token_budget,
)
from src.modules.ai_integration.llm_cache import LLMCache, LLMCacheConfig
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
        scenario_cfg = gen_config.get("scenarios", {}) or {}
        chat_s = scenario_cfg.get("chat", {}) or {}
        explain_s = scenario_cfg.get("explain", {}) or {}
        report_s = scenario_cfg.get("report", {}) or {}
        code_s = scenario_cfg.get("code", {}) or {}

        # 根据provider选择配置
        if provider == "deepseek":
            provider_config = ai_config.get("deepseek", {})
            default_base_url = "https://api.deepseek.com/v1"
            default_model = "deepseek-chat"
            code_model = "deepseek-coder"
        elif provider == "local_deepseek":
            provider_config = ai_config.get("local_deepseek", {})
            default_base_url = "http://localhost:8000/v1"
            default_model = "deepseek-r1"
            code_model = "deepseek-r1"
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
        protection_cfg = ai_config.get("protection", {}) or {}
        llm_config["max_concurrency"] = int(protection_cfg.get("max_concurrency", 2))
        llm_config["circuit_breaker"] = protection_cfg.get("circuit_breaker", {}) or {}

        self.llm = LLMClient(config=llm_config)
        prompts_cfg = ai_config.get("prompts", {}) or {}
        self.stock_explainer = StockExplainer(
            self.llm,
            system_prompt=prompts_cfg.get("stock_explainer_system"),
            default_temperature=explain_s.get("temperature"),
            default_max_tokens=explain_s.get("max_tokens"),
            default_timeout=explain_s.get("timeout"),
        )
        self.signal_analyzer = SignalAnalyzer(
            self.llm,
            system_prompt=prompts_cfg.get("signal_analyzer_system"),
            default_temperature=explain_s.get("temperature"),
            default_max_tokens=explain_s.get("max_tokens"),
            default_timeout=explain_s.get("timeout"),
        )
        self.news_analyzer = NewsSentimentAnalyzer(self.llm)
        features_cfg = ai_config.get("features", {}) or {}
        self.assistant = AIAssistant(
            self.llm,
            system_prompt=prompts_cfg.get("assistant_system"),
            quick_prompts=prompts_cfg.get("assistant_quick_prompts"),
            default_temperature=chat_s.get("temperature"),
            default_max_tokens=chat_s.get("max_tokens"),
            default_timeout=chat_s.get("timeout"),
            enable_actions=bool(features_cfg.get("action_execution", False)),
            action_whitelist=list(features_cfg.get("action_whitelist", []) or []),
            require_action_confirmation=bool(features_cfg.get("require_action_confirmation", True)),
            action_confirmation_keywords=list(features_cfg.get("action_confirmation_keywords", []) or []),
        )

        self._code_generation_params = {
            "temperature": code_s.get("temperature"),
            "max_tokens": code_s.get("max_tokens"),
            "timeout": code_s.get("timeout"),
        }

        # LLM 结果缓存（对“贵且重复”的接口生效）
        cache_cfg = ai_config.get("cache", {}) or {}
        cache_enabled = bool(cache_cfg.get("enabled", False))
        cache_ttl = int(cache_cfg.get("ttl", 3600))
        cache_max_size = int(cache_cfg.get("max_size", 2000))
        cache_db_path = os.environ.get("AI_CACHE_DB") or cache_cfg.get("db_path") or default_conversation_db_path().replace(
            "ai_conversations.sqlite3", "ai_llm_cache.sqlite3"
        )
        self._llm_cache = LLMCache(
            LLMCacheConfig(
                db_path=cache_db_path,
                enabled=cache_enabled,
                ttl_seconds=cache_ttl,
                max_items=cache_max_size,
            )
        )

        # 会话历史存储（SQLite）
        session_cfg = ai_config.get("session", {}) or {}
        db_path = (
            os.environ.get("AI_CONVERSATION_DB")
            or session_cfg.get("db_path")
            or default_conversation_db_path()
        )
        max_messages = int(session_cfg.get("max_messages", 200))
        self._conversation_store = ConversationStore(
            ConversationStoreConfig(db_path=db_path, max_messages=max_messages)
        )

        # 对话裁剪预算（粗估 token）
        # max_prompt_tokens: history + prompt 的预算；reserved_for_answer_tokens: 给回答预留
        self._chat_max_prompt_tokens = int(session_cfg.get("max_prompt_tokens", 6000))
        self._chat_reserved_answer_tokens = int(session_cfg.get("reserved_answer_tokens", 1200))

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
            "cache": {
                "enabled": bool(getattr(self._llm_cache, "_config", None) and self._llm_cache._config.enabled),  # type: ignore[attr-defined]
            },
            "actions": {
                "enabled": bool(self._config.get("ai", {}).get("features", {}).get("action_execution", False)),
                "require_confirmation": bool(
                    self._config.get("ai", {}).get("features", {}).get("require_action_confirmation", True)
                ),
                "whitelist": list(
                    self._config.get("ai", {}).get("features", {}).get("action_whitelist", []) or []
                ),
            },
            "assistant": self.assistant.get_capabilities(),
        }

    def _make_cache_key(self, prefix: str, payload: Dict[str, Any]) -> str:
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]
        provider = getattr(self.llm, "provider", "unknown")
        return f"{prefix}:{provider}:{digest}"

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
        cache_key = self._make_cache_key(
            "explain_selection",
            {"stocks": stock_list, "factors": factors, "market_context": market_context},
        )
        cached = self._llm_cache.get(cache_key)
        if cached:
            return cached
        result = self.stock_explainer.explain_selection(stock_list, factors, market_context)
        self._llm_cache.set(cache_key, result)
        return result

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
        cache_key = self._make_cache_key(
            "analyze_signal",
            {"code": stock_code, "name": stock_name, "signal": signal_data},
        )
        cached = self._llm_cache.get(cache_key)
        if cached:
            return cached
        result = self.signal_analyzer.analyze_breakout_signal(stock_code, stock_name, signal_data)
        self._llm_cache.set(cache_key, result)
        return result

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
        cache_key = self._make_cache_key(
            "analyze_news",
            {"news": news_list, "holdings": holdings},
        )
        cached = self._llm_cache.get(cache_key)
        if cached:
            return cached
        result = self.news_analyzer.analyze_news_impact(news_list, holdings)
        self._llm_cache.set(cache_key, result)
        return result

    # === AI助手 ===

    def chat(self, user_input: str, context: Optional[Dict] = None, session_id: Optional[str] = None) -> str:
        """AI助手对话（支持 session_id 持久化上下文）"""
        if not self._enabled:
            return "[AI功能已禁用]"
        sid = (session_id or "").strip() or "default"

        history = self._conversation_store.get_history(sid, limit=80)
        history = trim_history_by_token_budget(
            history=history,
            max_prompt_tokens=self._chat_max_prompt_tokens,
            reserved_for_answer_tokens=self._chat_reserved_answer_tokens,
        )

        response = self.assistant.chat_with_history(
            user_input=user_input,
            context=context,
            history=history,
        )

        self._conversation_store.append(sid, "user", user_input)
        self._conversation_store.append(sid, "assistant", response)
        return response

    def quick_ask(
        self, prompt_key: str, context: Optional[Dict] = None, session_id: Optional[str] = None
    ) -> str:
        """快速预设问答（默认清空该 session）"""
        if not self._enabled:
            return "[AI功能已禁用]"
        sid = (session_id or "").strip() or "default"
        self._conversation_store.clear(sid)
        try:
            prompt = self.assistant.get_quick_prompt(prompt_key)
        except Exception as e:
            return str(e)
        return self.chat(user_input=prompt, context=context, session_id=sid)

    def generate_code(self, description: str, framework: str = "pandas") -> str:
        """生成策略代码"""
        if not self._enabled:
            return "[AI功能已禁用]"
        return self.assistant.generate_strategy_code(
            description,
            framework,
            temperature=self._code_generation_params.get("temperature"),
            max_tokens=self._code_generation_params.get("max_tokens"),
            timeout=self._code_generation_params.get("timeout"),
        )

    def clear_chat_history(self, session_id: Optional[str] = None):
        """清除对话历史（按 session_id）"""
        sid = (session_id or "").strip() or "default"
        self._conversation_store.clear(sid)

    def get_chat_history(self, session_id: Optional[str] = None, limit: int = 50) -> List[Dict]:
        """获取对话历史（按 session_id）"""
        sid = (session_id or "").strip() or "default"
        return self._conversation_store.get_history(sid, limit=limit)
