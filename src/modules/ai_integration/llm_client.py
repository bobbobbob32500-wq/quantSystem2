# -*- coding: utf-8 -*-
"""
大模型客户端
统一封装Ollama / DeepSeek API调用，支持多模型切换、重试、降级
"""

import json
import os
import time
from typing import Any, Dict, List, Optional

import requests

from src.core.logger import get_logger

logger = get_logger("llm_client")


class LLMClient:
    """大模型统一客户端 - 支持Ollama和DeepSeek"""

    # 默认模型配置
    DEFAULT_CONFIG = {
        "provider": "ollama",  # "ollama" 或 "deepseek"
        "base_url": "http://localhost:11434",
        "api_key": "",
        "default_model": "qwen2.5:7b",
        "code_model": "mistral:7b",
        "timeout": 120,
        "max_retries": 2,
        "retry_delay": 3,
        "temperature": 0.7,
        "max_tokens": 2048,
    }

    def __init__(self, config: Optional[Dict] = None):
        """
        初始化大模型客户端

        Args:
            config: 配置字典，覆盖默认配置
        """
        self._config = {**self.DEFAULT_CONFIG}
        if config:
            self._config.update(config)

        self._base_url = self._config["base_url"].rstrip("/")
        self._api_key = self._config.get("api_key", "") or os.environ.get("DEEPSEEK_API_KEY", "")
        self._provider = self._config.get("provider", "ollama")

        # 自动检测: 如果配置了api_key或base_url包含deepseek，切换为deepseek
        if self._api_key and "deepseek" in self._base_url.lower():
            self._provider = "deepseek"
            logger.info("检测到DeepSeek配置，自动切换为DeepSeek模式")

        self._available = False
        self._installed_models = []
        self._check_availability()

    def _check_availability(self) -> bool:
        """检查LLM服务是否可用"""
        if self._provider == "deepseek":
            return self._check_deepseek_availability()
        return self._check_ollama_availability()

    def _check_ollama_availability(self) -> bool:
        """检查Ollama服务是否可用"""
        try:
            resp = requests.get(f"{self._base_url}/api/tags", timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                models = [m.get("name", "") for m in data.get("models", [])]
                logger.info(f"Ollama服务可用, 已安装模型: {models}")
                self._available = True
                self._installed_models = models
                return True
        except Exception as e:
            logger.warning(f"Ollama服务不可用: {e}")

        self._available = False
        self._installed_models = []
        return False

    def _check_deepseek_availability(self) -> bool:
        """检查DeepSeek API是否可用"""
        if not self._api_key:
            logger.warning("DeepSeek API Key未配置")
            self._available = False
            self._installed_models = []
            return False

        try:
            headers = {
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            }
            resp = requests.get(f"{self._base_url}/models", headers=headers, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                models = [m.get("id", "") for m in data.get("data", [])]
                logger.info(f"DeepSeek API可用, 可用模型: {models}")
                self._available = True
                self._installed_models = models
                return True
            else:
                logger.warning(f"DeepSeek API认证失败, 状态码={resp.status_code}")
        except Exception as e:
            logger.warning(f"DeepSeek API不可用: {e}")

        self._available = False
        self._installed_models = []
        return False

    @property
    def is_available(self) -> bool:
        """大模型服务是否可用"""
        return self._available

    @property
    def installed_models(self) -> List[str]:
        """已安装的模型列表"""
        return self._installed_models

    @property
    def provider(self) -> str:
        """当前使用的LLM提供者"""
        return self._provider

    def list_models(self) -> List[str]:
        """列出所有可用模型"""
        self._check_availability()
        return self._installed_models

    def chat(
        self,
        prompt: str,
        model: Optional[str] = None,
        system: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        history: Optional[List[Dict]] = None,
    ) -> str:
        """
        调用大模型进行对话

        Args:
            prompt: 用户输入
            model: 模型名称，默认使用default_model
            system: 系统提示词
            temperature: 温度参数
            max_tokens: 最大token数
            history: 对话历史 [{"role": "user/assistant", "content": "..."}]

        Returns:
            模型回复文本
        """
        if not self._available:
            self._check_availability()
            if not self._available:
                if self._provider == "deepseek":
                    return "[AI服务不可用] 请检查DeepSeek API Key和网络连接"
                return "[AI服务不可用] 请确保Ollama已安装并运行 (ollama serve)"

        model = model or self._config["default_model"]
        temperature = temperature or self._config["temperature"]
        max_tokens = max_tokens or self._config["max_tokens"]

        # 构建消息列表
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": prompt})

        if self._provider == "deepseek":
            return self._chat_deepseek(messages, model, temperature, max_tokens)
        return self._chat_ollama(messages, model, temperature, max_tokens)

    def _chat_ollama(
        self,
        messages: List[Dict],
        model: str,
        temperature: float,
        max_tokens: int,
    ) -> str:
        """Ollama API调用"""
        for attempt in range(self._config["max_retries"] + 1):
            try:
                resp = requests.post(
                    f"{self._base_url}/api/chat",
                    json={
                        "model": model,
                        "messages": messages,
                        "stream": False,
                        "options": {
                            "temperature": temperature,
                            "num_predict": max_tokens,
                        },
                    },
                    timeout=self._config["timeout"],
                )

                if resp.status_code == 200:
                    result = resp.json()
                    content = result.get("message", {}).get("content", "")
                    logger.debug(f"Ollama调用成功, 模型={model}, 输出长度={len(content)}")
                    return content
                else:
                    logger.warning(f"Ollama调用失败, 状态码={resp.status_code}, 响应={resp.text[:200]}")

            except requests.exceptions.Timeout:
                logger.warning(f"Ollama调用超时 (尝试 {attempt + 1}/{self._config['max_retries'] + 1})")
            except Exception as e:
                logger.warning(f"Ollama调用异常: {e} (尝试 {attempt + 1}/{self._config['max_retries'] + 1})")

            if attempt < self._config["max_retries"]:
                time.sleep(self._config["retry_delay"])

        return "[AI调用失败] 请检查Ollama服务状态和模型是否已下载"

    def _chat_deepseek(
        self,
        messages: List[Dict],
        model: str,
        temperature: float,
        max_tokens: int,
    ) -> str:
        """DeepSeek API调用 (OpenAI兼容格式)"""
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        for attempt in range(self._config["max_retries"] + 1):
            try:
                resp = requests.post(
                    f"{self._base_url}/chat/completions",
                    headers=headers,
                    json={
                        "model": model,
                        "messages": messages,
                        "temperature": temperature,
                        "max_tokens": max_tokens,
                        "stream": False,
                    },
                    timeout=self._config["timeout"],
                )

                if resp.status_code == 200:
                    result = resp.json()
                    content = result.get("choices", [{}])[0].get("message", {}).get("content", "")
                    logger.debug(f"DeepSeek调用成功, 模型={model}, 输出长度={len(content)}")
                    return content
                elif resp.status_code == 401:
                    logger.error("DeepSeek API Key无效或已过期")
                    return "[AI调用失败] DeepSeek API Key无效或已过期，请检查配置"
                elif resp.status_code == 402:
                    logger.error("DeepSeek API余额不足，请充值后使用")
                    return "[AI调用失败] DeepSeek API余额不足，请前往 https://platform.deepseek.com/ 充值"
                elif resp.status_code == 429:
                    logger.warning(f"DeepSeek API限流 (尝试 {attempt + 1}/{self._config['max_retries'] + 1})")
                else:
                    logger.warning(f"DeepSeek调用失败, 状态码={resp.status_code}, 响应={resp.text[:200]}")

            except requests.exceptions.Timeout:
                logger.warning(f"DeepSeek调用超时 (尝试 {attempt + 1}/{self._config['max_retries'] + 1})")
            except Exception as e:
                logger.warning(f"DeepSeek调用异常: {e} (尝试 {attempt + 1}/{self._config['max_retries'] + 1})")

            if attempt < self._config["max_retries"]:
                time.sleep(self._config["retry_delay"])

        return "[AI调用失败] 请检查DeepSeek API Key和网络连接"

    def chat_with_code(
        self,
        prompt: str,
        system: Optional[str] = None,
        **kwargs,
    ) -> str:
        """
        使用代码模型进行对话（用于策略代码生成等）

        Args:
            prompt: 用户输入
            system: 系统提示词

        Returns:
            模型回复文本
        """
        return self.chat(
            prompt=prompt,
            model=self._config["code_model"],
            system=system or "你是一个专业的量化交易策略开发助手，擅长Python编程和金融数据分析。",
            **kwargs,
        )

    def pull_model(self, model_name: str) -> bool:
        """
        拉取模型 (仅Ollama支持)

        Args:
            model_name: 模型名称

        Returns:
            是否成功
        """
        if self._provider == "deepseek":
            logger.info("DeepSeek为云端API，无需拉取模型")
            return True

        try:
            logger.info(f"开始拉取模型: {model_name}")
            resp = requests.post(
                f"{self._base_url}/api/pull",
                json={"name": model_name, "stream": False},
                timeout=600,
            )
            if resp.status_code == 200:
                logger.info(f"模型拉取成功: {model_name}")
                self._check_availability()
                return True
            else:
                logger.error(f"模型拉取失败: {resp.text[:200]}")
                return False
        except Exception as e:
            logger.error(f"模型拉取异常: {e}")
            return False

    def get_status(self) -> Dict[str, Any]:
        """获取AI服务状态"""
        return {
            "available": self._available,
            "provider": self._provider,
            "base_url": self._base_url,
            "default_model": self._config["default_model"],
            "code_model": self._config["code_model"],
            "installed_models": self._installed_models,
        }
