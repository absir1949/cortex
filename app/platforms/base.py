"""平台适配器基类 - 能力契约

每个平台声明自己支持的 Capability 集合。上层业务按能力分发调用。
未来接入视频号/Twitter/YouTube/知乎各自实现 PlatformAdapter 即可。

扩展点（加新平台时实现）：
  - platform_label / identifier_hint：给前端展示用
  - resolve_identifier：把用户输入解析成平台唯一 ID（抖音搜索匹配，视频号 sph→username）
  - _xxx_to_content：把平台原始数据转成统一 Content
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
    RESOLVE_IDENTIFIER = "resolve_identifier"  # 把用户输入解析成平台唯一 ID


class PlatformAdapter(ABC):
    """平台适配器抽象基类"""

    platform: str = ""
    platform_label: str = ""        # 中文展示名（如"抖音"/"视频号"）
    identifier_hint: str = ""       # 添加作者时的输入提示（如"抖音号 / sec_uid"）

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

    def resolve_identifier(self, raw_input: str, display_name: str = "") -> tuple[str, str]:
        """把用户输入解析成平台唯一 ID。返回 (platform_uid, display_name)。

        每个平台的解析方式不同：
        - 抖音：用户可能输入昵称/抖音号，需搜索匹配出 sec_uid
        - 视频号：用户输入 sph 短号，需转成 finder username
        - Twitter：用户输入 @screen_name，直接用
        """
        raise NotImplementedError(f"{self.platform} does not support RESOLVE_IDENTIFIER")

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
