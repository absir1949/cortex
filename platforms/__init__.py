"""平台适配器"""
from .base import PlatformAdapter, Video
from .douyin import DouyinAdapter

# 平台注册表
PLATFORMS = {
    'douyin': DouyinAdapter,
}


def get_adapter(platform: str, config):
    """获取平台适配器"""
    adapter_class = PLATFORMS.get(platform)
    if not adapter_class:
        raise ValueError(f"不支持的平台: {platform}")
    return adapter_class(config)


__all__ = ['PlatformAdapter', 'Video', 'DouyinAdapter', 'get_adapter']
