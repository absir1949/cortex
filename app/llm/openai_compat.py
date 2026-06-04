"""OpenAI 兼容客户端 - 可切 DeepSeek / OpenAI / Moonshot / 千问 等任何 OpenAI 兼容 API"""
from __future__ import annotations
from openai import OpenAI

from .base import LLMClient, LLMConfig, LLMMessage


class OpenAICompatClient(LLMClient):
    """使用 openai 官方 SDK，base_url 指向任意 OpenAI 兼容端点"""

    def chat(self, messages: list[LLMMessage], *, config: LLMConfig) -> str:
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
        return resp.choices[0].message.content or ""
