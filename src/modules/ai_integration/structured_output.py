#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
结构化输出工具

核心能力：
- 让模型严格输出 JSON（无 markdown code fence、无额外解释）
- 解析失败时做一次“纠错重试”，提升稳定性
"""

import json
from typing import Any, Dict, Optional, Tuple, Type, TypeVar

from pydantic import BaseModel, ValidationError

from src.core.logger import get_logger

logger = get_logger("structured_output")

T = TypeVar("T", bound=BaseModel)


def _strip_code_fence(text: str) -> str:
    text = (text or "").strip()
    if text.startswith("```"):
        # 兼容 ```json ... ```
        parts = text.split("```")
        if len(parts) >= 3:
            text = parts[1]
            # 去掉可能的语言标识
            text = text.lstrip()
            if text.lower().startswith("json"):
                text = text[4:].lstrip()
    return text.strip()


def _build_json_only_system(system: Optional[str]) -> str:
    base = system or ""
    rule = (
        "你必须严格输出 JSON，禁止输出任何额外解释、标题、Markdown、代码块标记。"
        "如果信息不足，仍要输出 JSON，但在对应字段里写明“不足/缺失”。"
    )
    if base:
        return f"{base}\n\n## 输出格式强约束\n{rule}"
    return f"## 输出格式强约束\n{rule}"


def llm_chat_structured(
    llm: Any,
    *,
    prompt: str,
    system: Optional[str],
    model_cls: Type[T],
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
    timeout: Optional[float] = None,
    max_fix_attempts: int = 1,
) -> Tuple[Optional[T], str]:
    """
    调用大模型生成结构化 JSON，并用 Pydantic 校验。

    返回：(结构化对象或 None, 原始文本)
    """
    json_system = _build_json_only_system(system)

    schema_hint = model_cls.model_json_schema() if hasattr(model_cls, "model_json_schema") else None
    schema_text = ""
    if schema_hint:
        schema_text = json.dumps(schema_hint, ensure_ascii=False)

    format_prompt = (
        f"{prompt}\n\n"
        "请严格输出一个 JSON 对象，字段必须完全匹配目标协议。\n"
        "目标协议（JSON Schema，仅供你对齐字段名与结构）：\n"
        f"{schema_text}\n"
    )

    raw = llm.chat(
        prompt=format_prompt,
        system=json_system,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=timeout,
    )
    raw_clean = _strip_code_fence(raw)
    obj = _try_parse(model_cls, raw_clean)
    if obj is not None:
        return obj, raw

    # 纠错重试
    last_error = "结构化解析失败"
    for attempt in range(max_fix_attempts):
        last_error = "JSON 解析或字段校验失败"
        fix_prompt = (
            "你上一次输出的 JSON 无法被程序解析或校验通过。\n"
            "请你只输出一个新的 JSON 对象，不要输出任何解释。\n\n"
            f"目标协议（JSON Schema）：\n{schema_text}\n\n"
            "上一次输出如下：\n"
            f"{raw_clean}\n"
        )
        fixed_raw = llm.chat(
            prompt=fix_prompt,
            system=json_system,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
        )
        fixed_clean = _strip_code_fence(fixed_raw)
        obj = _try_parse(model_cls, fixed_clean)
        if obj is not None:
            return obj, fixed_raw
        raw_clean = fixed_clean

    logger.debug(f"结构化输出最终失败: {last_error}")
    return None, raw


def _try_parse(model_cls: Type[T], text: str) -> Optional[T]:
    try:
        data = json.loads(text)
    except Exception:
        return None
    try:
        # 兼容 pydantic v1/v2
        if hasattr(model_cls, "model_validate"):
            return model_cls.model_validate(data)
        return model_cls.parse_obj(data)  # type: ignore[attr-defined]
    except ValidationError:
        return None
    except Exception:
        return None

