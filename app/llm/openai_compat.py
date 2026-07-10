"""OpenAI 兼容客户端 - 可切 DeepSeek / OpenAI / Moonshot / 千问 等任何 OpenAI 兼容 API"""
from __future__ import annotations
from typing import Optional

from openai import OpenAI

from .base import LLMClient, LLMConfig, LLMMessage, LLMTokenUsage, LLMUsageContext


class OpenAICompatClient(LLMClient):
    """使用 openai 官方 SDK，base_url 指向任意 OpenAI 兼容端点"""

    def chat(
        self,
        messages: list[LLMMessage],
        *,
        config: LLMConfig,
        usage_context: Optional[LLMUsageContext] = None,
    ) -> str:
        try:
            client = OpenAI(
                api_key=config.api_key,
                base_url=config.base_url,
                timeout=config.timeout_sec,
            )
            resp = client.chat.completions.create(
                model=config.model,
                messages=[{"role": m.role, "content": m.content} for m in messages],
                temperature=config.temperature,
                max_tokens=config.max_tokens,
            )
            text = resp.choices[0].message.content or ""
            self._record_usage(config, messages, text, usage_context, self._extract_usage(resp))
            return text
        except Exception as e:
            self._record_usage(config, messages, "", usage_context, None, error=e)
            raise

    @staticmethod
    def _extract_usage(resp) -> Optional[LLMTokenUsage]:
        usage = getattr(resp, "usage", None)
        if usage is None:
            return None
        prompt_details = _read(usage, "prompt_tokens_details")
        completion_details = _read(usage, "completion_tokens_details")
        return LLMTokenUsage(
            prompt_tokens=_read_int(usage, "prompt_tokens"),
            completion_tokens=_read_int(usage, "completion_tokens"),
            total_tokens=_read_int(usage, "total_tokens"),
            cached_tokens=_read_int(prompt_details, "cached_tokens"),
            reasoning_tokens=_read_int(completion_details, "reasoning_tokens"),
        )

    @staticmethod
    def _record_usage(
        config: LLMConfig,
        messages: list[LLMMessage],
        response_text: str,
        usage_context: Optional[LLMUsageContext],
        token_usage: Optional[LLMTokenUsage],
        *,
        error: Optional[BaseException] = None,
    ) -> None:
        try:
            from app.services.usage_service import record_llm_usage

            record_llm_usage(
                config=config,
                messages=messages,
                response_text=response_text,
                usage_context=usage_context,
                token_usage=token_usage,
                error=error,
            )
        except Exception:
            pass


def _read(obj, key: str):
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)


def _read_int(obj, key: str) -> Optional[int]:
    value = _read(obj, key)
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
