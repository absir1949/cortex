"""平台适配器基类 - 能力契约

每个平台声明自己支持的 Capability 集合。上层业务按能力分发调用。
未来接入小红书/B站/YouTube 各自实现 PlatformAdapter 即可。
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from enum import Enum
from typing import Optional

from app.models.content import Content, Comment


class Capability(str, Enum):
    FETCH_CREATOR = "fetch_creator"          # 拉取博主作品列表
    SEARCH = "search"                        # 按关键词搜索
    FETCH_COMMENTS = "fetch_comments"        # 抓取评论（含二级回复）
    DOWNLOAD_MEDIA = "download_media"        # 下载视频/图片到本地


class PlatformAdapter(ABC):
    """平台适配器抽象基类"""

    platform: str = ""

    @classmethod
    def name(cls) -> str:
        return cls.platform

    @abstractmethod
    def capabilities(self) -> set[Capability]:
        """声明本平台支持什么能力"""
        ...

    def has(self, cap: Capability) -> bool:
        return cap in self.capabilities()

    # ---- 以下方法是可选能力，未实现的应抛 NotImplementedError ----

    def fetch_creator_content(
        self,
        creator_id: str,
        limit: int = 50,
        days: Optional[int] = None,
    ) -> list[Content]:
        """拉取指定博主的作品列表"""
        raise NotImplementedError(f"{self.platform} does not support FETCH_CREATOR")

    def search(
        self,
        query: str,
        limit: int = 20,
        days: Optional[int] = 7,
    ) -> list[Content]:
        """按关键词搜索作品"""
        raise NotImplementedError(f"{self.platform} does not support SEARCH")

    def fetch_comments(
        self,
        content_id: str,
        top_n: int = 20,
        fetch_replies: bool = True,
    ) -> list[Comment]:
        """抓取视频评论（含二级回复）"""
        raise NotImplementedError(f"{self.platform} does not support FETCH_COMMENTS")

    def download_media(self, content: Content, output_path: str) -> bool:
        """下载媒体到本地文件"""
        raise NotImplementedError(f"{self.platform} does not support DOWNLOAD_MEDIA")
