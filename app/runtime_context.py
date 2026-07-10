"""轻量运行上下文。

当前只承载 task_id，供深层 service 在不改大量函数签名的情况下记录计量归属。
"""
from __future__ import annotations

from contextvars import ContextVar, Token
from typing import Optional


_current_task_id: ContextVar[Optional[str]] = ContextVar("current_task_id", default=None)


def current_task_id() -> Optional[str]:
    return _current_task_id.get()


def set_current_task_id(task_id: Optional[str]) -> Token:
    return _current_task_id.set(task_id)


def reset_current_task_id(token: Token) -> None:
    _current_task_id.reset(token)
