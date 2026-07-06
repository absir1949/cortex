"""LLM 客户端抽象 - 为多 provider 留口"""
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Literal


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


class LLMClient(ABC):
    @abstractmethod
    def chat(self, messages: list[LLMMessage], *, config: LLMConfig) -> str:
        """同步 chat 调用，返回 assistant 文本"""
        ...

    def embed(self, texts: list[str], *, config: LLMConfig) -> list[list[float]]:
        """文本向量化（用于未来 RAG 检索）。默认抛 NotImplementedError，子类按需实现。

        预留接口：现阶段不实现，等知识库问答（阶段 B）需要向量检索时再补。
        """
        raise NotImplementedError(f"{self.__class__.__name__} does not support embed()")
