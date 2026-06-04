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
