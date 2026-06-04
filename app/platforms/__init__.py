"""平台适配器注册表"""
from __future__ import annotations
from typing import Optional
from .base import PlatformAdapter, Capability
from .douyin import DouyinAdapter

_adapters: dict[str, type[PlatformAdapter]] = {
    "douyin": DouyinAdapter,
}


def get_adapter(platform: str) -> Optional[PlatformAdapter]:
    cls = _adapters.get(platform)
    if not cls:
        return None
    return cls()


def list_platforms() -> list[str]:
    return list(_adapters.keys())


__all__ = ["PlatformAdapter", "Capability", "get_adapter", "list_platforms"]
