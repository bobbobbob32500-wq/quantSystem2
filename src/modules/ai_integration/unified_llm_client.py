# -*- coding: autopep8
"""
统一LLM客户端 - 自动选择本地或云端
根据配置和可用性自动切换
"""

import os
from typing import Optional, Dict

from src.core.logger import get_logger
from src.modules.ai_integration.llm_client import LLMClient
from src.modules.ai_integration.cloud_llm_client import CloudLLMClient, CloudProvider

logger = get_logger("unified_llm")


class UnifiedLLMClient:
    """
    统一LLM客户端
    
    自动选择最佳服务:
    1. 优先使用本地Ollama（隐私保护）
    2. 本地不可用时使用云API
    3. 都不可用时降级处理
    """
    
    def __init__(self, config: Optional[Dict] = None):
        """
        初始化统一客户端
        
        Args:
            config: 配置字典
        """
        self._config = config or {}
        self._local_llm = None
        self._cloud_llm = None
        self._provider = self._config.get("provider", "ollama")
        
        # 初始化本地LLM
        if self._provider == "ollama" or self._config.get("fallback", {}).get("prefer_local", True):
            try:
                self._local_llm = LLMClient(config=self._config.get("ollama", {}))
                if self._local_llm.is_available:
                    logger.info("本地Ollama服务可用")
                else:
                    logger.warning("本地Ollama服务不可用")
                    self._local_llm = None
            except Exception as e:
                logger.warning(f"本地LLM初始化失败: {e}")
                self._local_llm = None
        
        # 初始化云端LLM
        if self._provider != "ollama" or self._config.get("fallback", {}).get("use_cloud", True):
            try:
                cloud_provider = self._get_cloud_provider()
                api_key = self._get_api_key(cloud_provider)
                
                if api_key:
                    self._cloud_llm = CloudLLMClient(
                        provider=cloud_provider,
                        api_key=api_key,
                        config=self._config.get(self._provider, {})
                    )
                    if self._cloud_llm.is_available:
                        logger.info(f"云端LLM服务可用: {cloud_provider.value}")
                    else:
                        self._cloud_llm = None
            except Exception as e:
                logger.warning(f"云端LLM初始化失败: {e}")
                self._cloud_llm = None
        
        # 检查可用性
        if not self._local_llm and not self._cloud_llm:
            logger.warning("所有LLM服务不可用，将使用降级模式")
    
    def _get_cloud_provider(self) -> CloudProvider:
        """获取云服务商"""
        provider_map = {
            "deepseek": CloudProvider.DEEPSEEK,
            "qwen": CloudProvider.QWEN,
            "openai": CloudProvider.OPENAI,
            "ernie": CloudProvider.ERNIE,
            "zhipu": CloudProvider.ZHIPU,
        }
        return provider_map.get(self._provider, CloudProvider.DEEPSEEK)
    
    def _get_api_key(self, provider: CloudProvider) -> Optional[str]:
        """获取API密钥"""
        # 从配置获取
        provider_config = self._config.get(self._provider, {})
        api_key = provider_config.get("api_key")
        
        if api_key:
            return api_key
        
        # 从环境变量获取
        env_map = {
            CloudProvider.DEEPSEEK: "DEEPSEEK_API_KEY",
            CloudProvider.QWEN: "QWEN_API_KEY",
            CloudProvider.OPENAI: "OPENAI_API_KEY",
            CloudProvider.ERNIE: "ERNIE_API_KEY",
            CloudProvider.ZHIPU: "ZHIPU_API_KEY",
        }
        
        env_name = provider_config.get("api_key_env") or env_map.get(provider)
        if env_name:
            return os.getenv(env_name)
        
        return None
    
    @property
    def is_available(self) -> bool:
        """是否有可用的LLM服务"""
        return bool(self._local_llm or self._cloud_llm)
    
    @property
    def active_provider(self) -> str:
        """当前使用的服务"""
        if self._local_llm and self._local_llm.is_available:
            return "ollama (本地)"
        elif self._cloud_llm and self._cloud_llm.is_available:
            return f"{self._provider} (云端)"
        else:
            return "降级模式"
    
    def chat(
        self,
        prompt: str,
        model: Optional[str] = None,
        system: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        history: Optional[list] = None,
        sensitive: bool = False,
    ) -> str:
        """
        调用大模型对话
        
        Args:
            prompt: 用户输入
            model: 模型名称
            system: 系统提示词
            temperature: 温度参数
            max_tokens: 最大token数
            history: 对话历史
            sensitive: 是否为敏感数据（优先使用本地）
        
        Returns:
            模型回复
        """
        # 优先级选择
        if sensitive and self._local_llm:
            # 敏感数据优先本地
            logger.debug("使用本地LLM处理敏感数据")
            return self._local_llm.chat(prompt, model, system, temperature, max_tokens, history)
        
        if self._provider == "ollama" and self._local_llm:
            # 配置为本地优先
            return self._local_llm.chat(prompt, model, system, temperature, max_tokens, history)
        
        if self._cloud_llm:
            # 使用云端API
            logger.debug(f"使用云端LLM: {self._provider}")
            return self._cloud_llm.chat(prompt, model, system, temperature, max_tokens, history)
        
        if self._local_llm:
            # 云端不可用，降级到本地
            logger.debug("云端不可用，降级到本地LLM")
            return self._local_llm.chat(prompt, model, system, temperature, max_tokens, history)
        
        # 完全降级
        return self._fallback_response(prompt)
    
    def _fallback_response(self, prompt: str) -> str:
        """降级响应"""
        return (
            "AI服务暂时不可用。\n\n"
            "可能原因：\n"
            "1. 本地Ollama服务未启动\n"
            "2. 云端API密钥未配置\n\n"
            "请检查配置或稍后重试。"
        )
    
    def get_status(self) -> Dict:
        """获取服务状态"""
        return {
            "available": self.is_available,
            "active_provider": self.active_provider,
            "local_available": bool(self._local_llm and self._local_llm.is_available),
            "cloud_available": bool(self._cloud_llm and self._cloud_llm.is_available),
            "provider": self._provider,
        }
