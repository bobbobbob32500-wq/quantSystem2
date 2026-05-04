# -*- coding: utf-8 -*-
"""
大模型客户端
统一封装Ollama / DeepSeek API调用，支持多模型切换、重试、降级
"""

import json
import os
import time
import uuid
import threading
from typing import Any, Dict, List, Optional

import requests

from src.core.logger import get_logger

logger = get_logger("llm_client")


class LLMClient:
    """大模型统一客户端 - 支持Ollama、DeepSeek和本地DeepSeek"""

    # 默认模型配置
    DEFAULT_CONFIG = {
        "provider": "ollama",  # "ollama" 或 "deepseek" 或 "local_deepseek"
        "base_url": "http://localhost:11434",
        "api_key": "",
        "default_model": "qwen2.5:7b",
        "code_model": "mistral:7b",
        "timeout": 120,
        "max_retries": 2,
        "retry_delay": 3,
        "temperature": 0.7,
        "max_tokens": 2048,
        # 保护机制
        "max_concurrency": 2,  # 最大并发调用数（保护本地推理服务）
        "circuit_breaker": {
            "enabled": True,
            "fail_threshold": 5,       # 连续失败次数阈值
            "cooldown_seconds": 60,    # 熔断冷却期
        },
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

        # 自动检测: 如果配置了api_key且base_url包含deepseek，切换为deepseek
        # 但如果显式配置为local_deepseek，则保持不变
        if self._provider == "local_deepseek":
            logger.info("使用本地DeepSeek R1模式")
        elif self._api_key and "deepseek" in self._base_url.lower():
            self._provider = "deepseek"
            logger.info("检测到DeepSeek配置，自动切换为DeepSeek模式")

        self._available = False
        self._installed_models = []
        self._recent_calls: List[Dict[str, Any]] = []  # 轻量指标，用于本地排查

        # 并发保护
        max_concurrency = int(self._config.get("max_concurrency", 2) or 2)
        max_concurrency = max(1, min(max_concurrency, 16))
        self._semaphore = threading.BoundedSemaphore(max_concurrency)

        # 熔断器
        cb = self._config.get("circuit_breaker", {}) or {}
        self._cb_enabled = bool(cb.get("enabled", True))
        self._cb_fail_threshold = int(cb.get("fail_threshold", 5) or 5)
        self._cb_cooldown_seconds = int(cb.get("cooldown_seconds", 60) or 60)
        self._cb_consecutive_failures = 0
        self._cb_open_until = 0
        self._check_availability()

    def _check_availability(self) -> bool:
        """检查LLM服务是否可用"""
        if self._provider in ("deepseek", "local_deepseek"):
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
        """检查DeepSeek API是否可用（云端和本地通用）"""
        # 本地DeepSeek可能无需API Key，仅云端强制要求
        if not self._api_key and self._provider == "deepseek":
            logger.warning("DeepSeek API Key未配置")
            self._available = False
            self._installed_models = []
            return False

        try:
            headers = {
                "Content-Type": "application/json",
            }
            if self._api_key:
                headers["Authorization"] = f"Bearer {self._api_key}"
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
        timeout: Optional[float] = None,
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
            timeout: 超时（秒），不传则使用配置默认值
            history: 对话历史 [{"role": "user/assistant", "content": "..."}]

        Returns:
            模型回复文本
        """
        now = int(time.time())
        if self._cb_enabled and self._cb_open_until and now < self._cb_open_until:
            return "[AI服务熔断中] 最近失败较多，已进入短暂冷却期，请稍后重试。"

        if not self._available:
            self._check_availability()
            if not self._available:
                if self._provider == "local_deepseek":
                    return "[AI服务不可用] 请检查本地DeepSeek R1服务是否已启动"
                elif self._provider == "deepseek":
                    return "[AI服务不可用] 请检查DeepSeek API Key和网络连接"
                return "[AI服务不可用] 请确保Ollama已安装并运行 (ollama serve)"

        model = model or self._config["default_model"]
        temperature = temperature or self._config["temperature"]
        max_tokens = max_tokens or self._config["max_tokens"]
        timeout = timeout or self._config["timeout"]

        # 构建消息列表
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": prompt})

        acquired = self._semaphore.acquire(timeout=2)
        if not acquired:
            return "[AI服务繁忙] 当前并发请求较多，请稍后重试。"

        try:
            if self._provider in ("deepseek", "local_deepseek"):
                result = self._chat_deepseek(messages, model, temperature, max_tokens, timeout)
            else:
                result = self._chat_ollama(messages, model, temperature, max_tokens, timeout)
            return result
        finally:
            try:
                self._semaphore.release()
            except Exception:
                pass

    def _chat_ollama(
        self,
        messages: List[Dict],
        model: str,
        temperature: float,
        max_tokens: int,
        timeout: float,
    ) -> str:
        """Ollama API调用"""
        request_id = uuid.uuid4().hex[:12]
        for attempt in range(self._config["max_retries"] + 1):
            try:
                start = time.time()
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
                    timeout=timeout,
                )

                if resp.status_code == 200:
                    result = resp.json()
                    content = result.get("message", {}).get("content", "")
                    self._record_call(
                        request_id=request_id,
                        model=model,
                        elapsed_ms=int((time.time() - start) * 1000),
                        success=True,
                        status_code=resp.status_code,
                        attempt=attempt,
                    )
                    logger.debug(f"Ollama调用成功, 模型={model}, 输出长度={len(content)}")
                    return content
                else:
                    self._record_call(
                        request_id=request_id,
                        model=model,
                        elapsed_ms=int((time.time() - start) * 1000),
                        success=False,
                        status_code=resp.status_code,
                        attempt=attempt,
                    )
                    logger.warning(f"Ollama调用失败, 状态码={resp.status_code}, 响应={resp.text[:200]}")

            except requests.exceptions.Timeout:
                self._record_call(
                    request_id=request_id,
                    model=model,
                    elapsed_ms=int(timeout * 1000),
                    success=False,
                    status_code=None,
                    attempt=attempt,
                    error_type="timeout",
                )
                logger.warning(f"Ollama调用超时 (尝试 {attempt + 1}/{self._config['max_retries'] + 1})")
            except Exception as e:
                self._record_call(
                    request_id=request_id,
                    model=model,
                    elapsed_ms=0,
                    success=False,
                    status_code=None,
                    attempt=attempt,
                    error_type="exception",
                )
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
        timeout: float,
    ) -> str:
        """DeepSeek API调用 (OpenAI兼容格式，云端和本地通用)"""
        request_id = uuid.uuid4().hex[:12]
        headers = {
            "Content-Type": "application/json",
        }
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        for attempt in range(self._config["max_retries"] + 1):
            try:
                start = time.time()
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
                    timeout=timeout,
                )

                if resp.status_code == 200:
                    result = resp.json()
                    content = result.get("choices", [{}])[0].get("message", {}).get("content", "")
                    self._record_call(
                        request_id=request_id,
                        model=model,
                        elapsed_ms=int((time.time() - start) * 1000),
                        success=True,
                        status_code=resp.status_code,
                        attempt=attempt,
                    )
                    logger.debug(f"DeepSeek调用成功, 模型={model}, 输出长度={len(content)}")
                    return content
                elif resp.status_code == 401:
                    self._record_call(
                        request_id=request_id,
                        model=model,
                        elapsed_ms=int((time.time() - start) * 1000),
                        success=False,
                        status_code=resp.status_code,
                        attempt=attempt,
                        error_type="unauthorized",
                    )
                    logger.error("DeepSeek API Key无效或已过期")
                    return "[AI调用失败] DeepSeek API Key无效或已过期，请检查配置"
                elif resp.status_code == 402:
                    self._record_call(
                        request_id=request_id,
                        model=model,
                        elapsed_ms=int((time.time() - start) * 1000),
                        success=False,
                        status_code=resp.status_code,
                        attempt=attempt,
                        error_type="payment_required",
                    )
                    logger.error("DeepSeek API余额不足，请充值后使用")
                    return "[AI调用失败] DeepSeek API余额不足，请前往 https://platform.deepseek.com/ 充值"
                elif resp.status_code == 429:
                    self._record_call(
                        request_id=request_id,
                        model=model,
                        elapsed_ms=int((time.time() - start) * 1000),
                        success=False,
                        status_code=resp.status_code,
                        attempt=attempt,
                        error_type="rate_limited",
                    )
                    logger.warning(f"DeepSeek API限流 (尝试 {attempt + 1}/{self._config['max_retries'] + 1})")
                else:
                    self._record_call(
                        request_id=request_id,
                        model=model,
                        elapsed_ms=int((time.time() - start) * 1000),
                        success=False,
                        status_code=resp.status_code,
                        attempt=attempt,
                        error_type="http_error",
                    )
                    logger.warning(f"DeepSeek调用失败, 状态码={resp.status_code}, 响应={resp.text[:200]}")

            except requests.exceptions.Timeout:
                self._record_call(
                    request_id=request_id,
                    model=model,
                    elapsed_ms=int(timeout * 1000),
                    success=False,
                    status_code=None,
                    attempt=attempt,
                    error_type="timeout",
                )
                logger.warning(f"DeepSeek调用超时 (尝试 {attempt + 1}/{self._config['max_retries'] + 1})")
            except Exception as e:
                self._record_call(
                    request_id=request_id,
                    model=model,
                    elapsed_ms=0,
                    success=False,
                    status_code=None,
                    attempt=attempt,
                    error_type="exception",
                )
                logger.warning(f"DeepSeek调用异常: {e} (尝试 {attempt + 1}/{self._config['max_retries'] + 1})")

            if attempt < self._config["max_retries"]:
                time.sleep(self._config["retry_delay"])

        if self._provider == "local_deepseek":
            return "[AI调用失败] 请检查本地DeepSeek R1服务状态和模型是否已加载"
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
        if self._provider in ("deepseek", "local_deepseek"):
            logger.info("DeepSeek为API服务，无需拉取模型")
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
        provider_display_map = {
            "ollama": "Ollama (本地)",
            "deepseek": "DeepSeek (云端)",
            "local_deepseek": "DeepSeek R1 (本地)",
        }
        return {
            "available": self._available,
            "provider": self._provider,
            "provider_display": provider_display_map.get(self._provider, self._provider),
            "base_url": self._base_url,
            "default_model": self._config["default_model"],
            "code_model": self._config["code_model"],
            "installed_models": self._installed_models,
            "metrics": self._metrics_summary(),
        }

    def _record_call(
        self,
        *,
        request_id: str,
        model: str,
        elapsed_ms: int,
        success: bool,
        status_code: Optional[int],
        attempt: int,
        error_type: Optional[str] = None,
    ) -> None:
        item = {
            "ts": int(time.time()),
            "request_id": request_id,
            "provider": self._provider,
            "model": model,
            "elapsed_ms": int(elapsed_ms),
            "success": bool(success),
            "status_code": status_code,
            "attempt": int(attempt),
            "error_type": error_type,
        }
        self._recent_calls.append(item)
        if len(self._recent_calls) > 200:
            self._recent_calls = self._recent_calls[-200:]

        # 熔断计数更准确：以 success 为准
        if item.get("success"):
            self._on_call_succeeded()
        else:
            self._on_call_failed()

    def _on_call_succeeded(self) -> None:
        self._cb_consecutive_failures = 0
        self._cb_open_until = 0

    def _on_call_failed(self) -> None:
        if not self._cb_enabled:
            return
        self._cb_consecutive_failures += 1
        if self._cb_consecutive_failures >= self._cb_fail_threshold:
            self._cb_open_until = int(time.time()) + int(self._cb_cooldown_seconds)
            logger.warning(
                f"AI服务触发熔断: 连续失败{self._cb_consecutive_failures}次, 冷却{self._cb_cooldown_seconds}s"
            )

    def _metrics_summary(self) -> Dict[str, Any]:
        calls = list(self._recent_calls)
        if not calls:
            return {"recent": 0}
        latencies = [c["elapsed_ms"] for c in calls if isinstance(c.get("elapsed_ms"), int)]
        latencies_sorted = sorted(latencies) if latencies else []
        success_count = sum(1 for c in calls if c.get("success"))
        fail_count = len(calls) - success_count

        def pctl(p: float) -> Optional[int]:
            if not latencies_sorted:
                return None
            idx = int(round((len(latencies_sorted) - 1) * p))
            idx = max(0, min(idx, len(latencies_sorted) - 1))
            return int(latencies_sorted[idx])

        last_fail = next((c for c in reversed(calls) if not c.get("success")), None)
        return {
            "recent": len(calls),
            "success": success_count,
            "failed": fail_count,
            "p50_ms": pctl(0.50),
            "p90_ms": pctl(0.90),
            "p95_ms": pctl(0.95),
            "last_error": {
                "request_id": last_fail.get("request_id") if last_fail else None,
                "status_code": last_fail.get("status_code") if last_fail else None,
                "error_type": last_fail.get("error_type") if last_fail else None,
            }
            if last_fail
            else None,
            "circuit_breaker": {
                "enabled": self._cb_enabled,
                "consecutive_failures": self._cb_consecutive_failures,
                "open_until": self._cb_open_until or None,
            },
        }
