"""平台适配器注册表"""
from __future__ import annotations
from typing import Optional
from .base import PlatformAdapter, Capability
from .douyin import DouyinAdapter
from .wechat_channels import WechatChannelsAdapter

_adapters: dict[str, type[PlatformAdapter]] = {
    "douyin": DouyinAdapter,
    "wechat_channels": WechatChannelsAdapter,
}


def get_adapter(platform: str) -> Optional[PlatformAdapter]:
    cls = _adapters.get(platform)
    if not cls:
        return None
    return cls()


def list_platforms() -> list[str]:
    return list(_adapters.keys())


def list_platforms_metadata() -> list[dict]:
    """返回所有平台的元数据（给前端添加作者表单用）"""
    out = []
    for plat, cls in _adapters.items():
        # 实例化拿 capabilities（类属性 platform_label/identifier_hint 是类级的，直接读）
        try:
            caps = cls().capabilities()
        except Exception:
            caps = set()
        out.append({
            "id": plat,
            "label": cls.platform_label or plat,
            "identifier_hint": cls.identifier_hint or "",
            "capabilities": [c.value for c in caps],
        })
    return out


__all__ = ["PlatformAdapter", "Capability", "get_adapter", "list_platforms", "list_platforms_metadata"]
