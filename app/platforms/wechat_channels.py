"""微信视频号平台适配器 - 基于 TikHub WeChat Channels V2 API

端点（都是 POST /api/v1/wechat_channels/v2/...）：
- fetch_channel_id_to_username   sph 短号 → finder username
- fetch_channel_info              账号信息
- fetch_user_videos               用户作品列表
- fetch_video_detail             作品详情
- fetch_video_comments            作品评论

注意：视频号视频是加密的（需 decode_key 解密），当前版本暂不支持下载/转录。
先支持「作品列表 + 标题描述 + 评论」，信号判定可用这些做。
"""
from __future__ import annotations
from datetime import datetime
from typing import Any, Optional

import requests

from app.settings import settings
from app.models.content import Content, Comment, ContentType
from app.platforms.base import PlatformAdapter, Capability


class WechatChannelsAdapter(PlatformAdapter):
    platform = "wechat_channels"
    platform_label = "视频号"
    identifier_hint = "sph 短号或 finder username（视频号暂不支持搜名字）"

    def __init__(self):
        self.api_key = settings.tikhub_api_key
        self.api_url = settings.tikhub_api_url.rstrip("/")

    # ------ 能力声明 ------

    def capabilities(self) -> set[Capability]:
        return {
            Capability.RESOLVE_IDENTIFIER,
            Capability.FETCH_CREATOR,
            Capability.FETCH_COMMENTS,
        }

    # ------ 内部工具 ------

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"}

    def _post(self, path: str, payload: dict[str, Any]) -> dict:
        url = f"{self.api_url}{path}"
        resp = requests.post(url, json=payload, headers=self._headers(), timeout=30)
        if resp.status_code != 200:
            raise RuntimeError(f"TikHub HTTP {resp.status_code}: {resp.text[:500]}")
        data = resp.json()
        if data.get("code") != 200:
            msg = data.get("message", "unknown")
            raise RuntimeError(f"TikHub API error {data.get('code')}: {msg}")
        return data

    @staticmethod
    def _iso(ts: Any) -> str:
        try:
            return datetime.fromtimestamp(int(ts)).isoformat()
        except Exception:
            return ""

    def _video_to_content(self, item: dict, author_name: str = "", author_id: str = "") -> Content:
        object_id = str(item.get("object_id") or item.get("objectId") or "")
        desc = item.get("desc") or item.get("title") or ""
        return Content(
            content_id=object_id,
            platform=self.platform,
            content_type=ContentType.VIDEO,
            url=f"https://channels.weixin.qq.com/web/feed/{object_id}" if object_id else "",
            author_id=author_id,
            author_name=author_name,
            title=desc,
            text=desc,
            media_urls=[],
            create_time=self._iso(item.get("create_time") or item.get("createTime")),
            statistics={
                "like_count": int(item.get("like_count") or item.get("likeCount") or 0),
                "comment_count": int(item.get("comment_count") or item.get("commentCount") or 0),
                "forward_count": int(item.get("forward_count") or item.get("forwardCount") or 0),
            },
            needs_transcribe=False,
        )

    # ------ 解析用户输入 → finder username ------

    def resolve_identifier(self, raw_input: str, display_name: str = "") -> tuple[str, str]:
        """视频号不支持搜名字。用户必须输入 sph 短号或 finder username。

        sph 短号会通过 fetch_channel_id_to_username 转成 finder username。
        """
        raw = raw_input.strip()
        # 已是 finder username
        if raw.startswith("v2_") and "@finder" in raw:
            return raw, display_name or raw
        # 尝试当作 channel_id（sph 短号或其他 ID）转换
        try:
            data = self._post(
                "/api/v1/wechat_channels/v2/fetch_channel_id_to_username",
                {"channel_id": raw, "raw": False},
            )
            d = data.get("data") or {}
            username = d.get("username") or ""
            nickname = d.get("nickname") or ""
            if username:
                return username, display_name or nickname or raw
        except Exception as e:
            raise ValueError(
                f"视频号无法解析「{raw}」。视频号暂不支持搜名字，"
                f"请输入 sph 短号（如 sph_xxx）或 finder username（v2_xxx@finder）。"
            )
        raise ValueError(
            f"视频号无法解析「{raw}」。请确认输入的是 sph 短号或 finder username。"
        )

    # ------ 博主作品 ------

    def fetch_creator_content(
        self,
        creator_id: str,
        limit: int = 50,
        days: Optional[int] = None,
    ) -> list[Content]:
        author_name = ""
        try:
            info = self._post(
                "/api/v1/wechat_channels/v2/fetch_channel_info",
                {"username": creator_id},
            )
            nick = (info.get("data") or {}).get("nickname") or ""
            if nick:
                author_name = nick
        except Exception:
            pass

        contents: list[Content] = []
        cursor = ""
        for _ in range(5):
            try:
                data = self._post(
                    "/api/v1/wechat_channels/v2/fetch_user_videos",
                    {"username": creator_id, "cursor": cursor},
                )
            except Exception:
                break
            raw = data.get("data") or {}
            items = raw.get("object_list") or raw.get("objectList") or raw.get("videos") or []
            for item in items:
                if isinstance(item, dict):
                    contents.append(self._video_to_content(item, author_name, creator_id))
                    if len(contents) >= limit:
                        break
            if len(contents) >= limit:
                break
            cursor = raw.get("cursor") or raw.get("next_cursor") or ""
            if not cursor or not raw.get("has_more", True):
                break

        if days and days > 0:
            contents = self._filter_by_days(contents, days)
        return contents[:limit]

    @staticmethod
    def _filter_by_days(contents: list[Content], days: int) -> list[Content]:
        from datetime import timedelta
        cutoff = datetime.now() - timedelta(days=days)
        out = []
        for c in contents:
            try:
                t = datetime.fromisoformat(c.create_time) if c.create_time else None
                if t is None or t >= cutoff:
                    out.append(c)
            except Exception:
                out.append(c)
        return out

    # ------ 评论 ------

    def fetch_comments(
        self,
        content_id: str,
        top_n: int = 20,
        fetch_replies: bool = True,
    ) -> list[Comment]:
        try:
            data = self._post(
                "/api/v1/wechat_channels/v2/fetch_video_comments",
                {"object_id": content_id, "cursor": ""},
            )
        except Exception:
            return []
        raw = data.get("data") or {}
        items = raw.get("comment_list") or raw.get("commentList") or []
        comments: list[Comment] = []
        for item in items[:top_n]:
            if not isinstance(item, dict):
                continue
            cid = str(item.get("comment_id") or item.get("commentID") or item.get("id") or "")
            if not cid:
                continue
            user = item.get("user_info") or item.get("userInfo") or {}
            comments.append(Comment(
                comment_id=cid,
                author=user.get("nickname", ""),
                text=item.get("content") or item.get("text") or "",
                likes=int(item.get("like_count") or item.get("likeCount") or 0),
                create_time=self._iso(item.get("create_time") or item.get("createTime")),
            ))
        return comments
