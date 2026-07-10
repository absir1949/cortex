"""LLM 客户端抽象 - 为多 provider 留口"""
from __future__ import annotations
import inspect
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Literal, Optional


Role = Literal["system", "user", "assistant"]


@dataclass
class LLMMessage:
    role: Role
    content: str


@dataclass
class LLMConfig:
    base_url: str
    api_key: str
    model: str
    temperature: float = 0.3
    max_tokens: int = 4096
    timeout_sec: int = 180


@dataclass
class LLMUsageContext:
    operation: str = "unknown"
    task_id: Optional[str] = None
    user_id: Optional[int] = None
    group_id: Optional[int] = None
    source_id: Optional[int] = None
    creator_id: Optional[int] = None
    global_content_id: Optional[int] = None
    ingest_target_id: Optional[int] = None
    conversation_id: Optional[int] = None


@dataclass
class LLMTokenUsage:
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    total_tokens: Optional[int] = None
    cached_tokens: Optional[int] = None
    reasoning_tokens: Optional[int] = None


class LLMClient(ABC):
    @abstractmethod
    def chat(
        self,
        messages: list[LLMMessage],
        *,
        config: LLMConfig,
        usage_context: Optional[LLMUsageContext] = None,
    ) -> str:
        """同步 chat 调用，返回 assistant 文本"""
        ...

    def embed(self, texts: list[str], *, config: LLMConfig) -> list[list[float]]:
        """文本向量化（用于未来 RAG 检索）。默认抛 NotImplementedError，子类按需实现。

        预留接口：现阶段不实现，等知识库问答（阶段 B）需要向量检索时再补。
        """
        raise NotImplementedError(f"{self.__class__.__name__} does not support embed()")


def chat_with_usage(
    client: LLMClient,
    messages: list[LLMMessage],
    *,
    config: LLMConfig,
    usage_context: Optional[LLMUsageContext] = None,
) -> str:
    """兼容测试里的轻量 monkeypatch，同时让真实 client 记录计量。"""
    try:
        params = inspect.signature(client.chat).parameters
    except (TypeError, ValueError):
        params = {}
    if "usage_context" in params:
        return client.chat(messages, config=config, usage_context=usage_context)
    return client.chat(messages, config=config)
