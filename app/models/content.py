"""内容模型 - 跨平台统一抽象

Content 是平台返回给业务层的数据结构（不存 DB）。
视频/图文笔记/微博等都归一到这里，通过 content_type 区分。
"""
from __future__ import annotations
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class ContentType(str, Enum):
    VIDEO = "video"   # 抖音/B站视频
    NOTE = "note"     # 小红书笔记
    POST = "post"     # 微博/推特

    @property
    def needs_transcribe(self) -> bool:
        """默认是否需要转录：只有视频默认需要"""
        return self == ContentType.VIDEO


class Comment(BaseModel):
    """评论（含楼中楼）"""
    comment_id: str
    author: str = ""
    text: str = ""
    likes: int = 0
    create_time: Optional[str] = None  # ISO 8601
    replies: list[Comment] = Field(default_factory=list)


Comment.model_rebuild()


class Content(BaseModel):
    """平台内容（泛化的 Video）"""
    # 标识
    content_id: str
    platform: str                            # douyin / xiaohongshu / ...
    content_type: ContentType
    url: str = ""                            # 分享链接（稳定可跳转）

    # 创作者
    author_id: str = ""
    author_name: str = ""

    # 本体
    title: str = ""
    text: str = ""                           # 正文/描述
    media_urls: list[str] = Field(default_factory=list)  # 视频/图片直链（可能失效）

    # 时间与统计
    create_time: str = ""                    # ISO 8601
    statistics: dict[str, int] = Field(default_factory=dict)  # likes, comments, shares, plays

    # 评论（调用方可选填充）
    comments: list[Comment] = Field(default_factory=list)

    # 转录控制
    needs_transcribe: Optional[bool] = None  # None 时按 content_type 默认决定

    def should_transcribe(self) -> bool:
        if self.needs_transcribe is not None:
            return self.needs_transcribe
        return self.content_type.needs_transcribe
