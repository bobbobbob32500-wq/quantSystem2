# -*- coding: utf-8 -*-
"""
统一LLM客户端（兼容壳）

说明：
本项目实际推荐使用 `src/services/ai_service.py -> LLMClient` 作为唯一调用链路。
该文件历史上尝试做“本地/云端自动路由”，但云端实现文件缺失，容易造成导入断链。

为避免未来被误引用导致运行时崩溃，这里保留一个**安全的薄封装**：
- 只封装 `LLMClient`，不再依赖不存在的云端客户端
- 如需多云路由/回退，请在 `LLMClient` 与 `AIService` 层按配置实现
"""

from typing import Dict, Optional

from src.core.logger import get_logger
from src.modules.ai_integration.llm_client import LLMClient

logger = get_logger("unified_llm")


class UnifiedLLMClient:
    """统一LLM客户端（当前等价于 `LLMClient` 的薄封装）"""

    def __init__(self, config: Optional[Dict] = None):
        self._config = config or {}
        try:
            self._llm = LLMClient(config=self._config)
        except Exception as e:
            logger.warning(f"统一LLM客户端初始化失败: {e}")
            self._llm = LLMClient(config={})

    @property
    def is_available(self) -> bool:
        return self._llm.is_available

    @property
    def active_provider(self) -> str:
        return self._llm.provider

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
        # sensitive 参数仅为兼容保留；当前由调用方自行决定是否使用本地/云端 provider
        _ = sensitive
        return self._llm.chat(
            prompt=prompt,
            model=model,
            system=system,
            temperature=temperature,
            max_tokens=max_tokens,
            history=history,
        )

    def get_status(self) -> Dict:
        status = self._llm.get_status()
        status.update(
            {
                "available": self.is_available,
                "active_provider": self.active_provider,
            }
        )
        return status
