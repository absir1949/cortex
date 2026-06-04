"""任务类型注册表"""
from __future__ import annotations
from typing import Callable, Any
from app.models.group import TaskKind


_handlers: dict[str, Callable[..., Any]] = {}


def register_handler(kind: TaskKind | str):
    """装饰器：注册一个任务处理函数

    Handler 签名: (task: Task, ctx: TaskContext) -> dict
    """
    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        key = kind.value if isinstance(kind, TaskKind) else kind
        _handlers[key] = fn
        return fn
    return decorator


def get_handler(kind: TaskKind | str) -> Callable[..., Any] | None:
    key = kind.value if isinstance(kind, TaskKind) else kind
    return _handlers.get(key)
