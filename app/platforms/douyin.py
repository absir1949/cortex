"""抖音平台适配器 - 基于 TikHub API

端点：
- fetch_user_post_videos       博主作品列表
- search/fetch_general_search_v1/v2  关键词综合搜索（POST）
- fetch_video_comments          视频一级评论
- fetch_video_comment_replies   二级回复
"""
from __future__ import annotations
import json
import random
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import requests

from app.settings import settings
from app.models.content import Content, Comment, ContentType
from app.platforms.base import PlatformAdapter, Capability


class DouyinAdapter(PlatformAdapter):
    platform = "douyin"
    platform_label = "抖音"
    identifier_hint = "抖音号 / sec_uid (MS4w...)"

    def __init__(self):
        self.api_key = settings.tikhub_api_key
        self.api_url = settings.tikhub_api_url.rstrip("/")

    # ------ 能力声明 ------

    def capabilities(self) -> set[Capability]:
        return {
            Capability.FETCH_CREATOR,
            Capability.SEARCH,
            Capability.FETCH_COMMENTS,
            Capability.DOWNLOAD_MEDIA,
            Capability.RESOLVE_IDENTIFIER,
        }

    # ------ 解析用户输入 → sec_uid ------

    def resolve_identifier(self, raw_input: str, display_name: str = "") -> tuple[str, str]:
        """把用户输入（昵称/抖音号/sec_uid）解析成 sec_uid。

        - 已是 sec_uid（MS4w 前缀）直接用
        - 否则搜抖音，按 display_name 匹配最可能的作者
        """
        identifier = raw_input.strip()
        if identifier.startswith("MS4w"):
            return identifier, display_name or identifier

        clean = identifier.strip().rstrip("/")
        if "/" in clean:
            clean = clean.split("/")[-1] or clean

        queries: list[str] = []
        if display_name:
            queries.append(f"{display_name} {clean}".strip())
            queries.append(display_name)
        queries.append(clean)

        seen: set[str] = set()
        best = None
        for q in queries:
            if not q or q in seen:
                continue
            seen.add(q)
            try:
                results = self.search(q, limit=10, days=180)
            except Exception:
                continue
            for item in results:
                if not item.author_id:
                    continue
                if display_name and item.author_name == display_name:
                    return item.author_id, item.author_name
                if display_name and display_name.replace(" ", "") in item.author_name.replace(" ", ""):
                    return item.author_id, item.author_name
                if best is None:
                    best = item
        if best and best.author_id:
            return best.author_id, best.author_name or display_name or raw_input
        raise ValueError(f"无法解析抖音作者: {raw_input}")

    # ------ 内部工具 ------

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"}

    def _get(self, path: str, params: dict[str, Any]) -> dict:
        url = f"{self.api_url}{path}"
        resp = requests.get(url, params=params, headers=self._headers(), timeout=30)
        if resp.status_code != 200:
            raise RuntimeError(f"TikHub HTTP {resp.status_code}: {resp.text[:500]}")
        data = resp.json()
        if data.get("code") != 200:
            msg = data.get("message", "unknown")
            raise RuntimeError(f"TikHub API error {data.get('code')}: {msg}")
        return data

    def _post(self, path: str, payload: dict[str, Any]) -> dict:
        url = f"{self.api_url}{path}"
        resp = requests.post(url, json=payload, headers=self._headers(), timeout=60)
        if resp.status_code != 200:
            raise RuntimeError(f"TikHub HTTP {resp.status_code}: {resp.text[:500]}")
        data = resp.json()
        if data.get("code") != 200:
            msg = data.get("message", "unknown")
            raise RuntimeError(f"TikHub API error {data.get('code')}: {msg}")
        return data

    @staticmethod
    def _iso(ts: int) -> str:
        try:
            return datetime.fromtimestamp(ts).isoformat()
        except Exception:
            return ""

    def _aweme_to_content(self, item: dict) -> Content:
        """从 TikHub 返回的 aweme 字典构造 Content"""
        aweme_id = item.get("aweme_id", "")
        author = item.get("author", {}) or {}
        statistics = item.get("statistics", {}) or {}
        video = item.get("video", {}) or {}
        play_addr = video.get("play_addr", {}) or {}
        url_list = play_addr.get("url_list", []) or []

        return Content(
            content_id=aweme_id,
            platform=self.platform,
            content_type=ContentType.VIDEO,
            url=f"https://www.douyin.com/video/{aweme_id}",
            author_id=author.get("sec_uid", "") or author.get("uid", ""),
            author_name=author.get("nickname", ""),
            title=item.get("desc", ""),
            text=item.get("desc", ""),
            media_urls=list(url_list) if url_list else [],
            create_time=self._iso(item.get("create_time", 0)),
            statistics={
                "digg_count": int(statistics.get("digg_count", 0) or 0),
                "comment_count": int(statistics.get("comment_count", 0) or 0),
                "share_count": int(statistics.get("share_count", 0) or 0),
                "play_count": int(statistics.get("play_count", 0) or 0),
            },
        )

    # ------ 博主作品 ------

    def fetch_creator_content(
        self,
        creator_id: str,
        limit: int = 50,
        days: Optional[int] = None,
    ) -> list[Content]:
        data = self._get(
            "/api/v1/douyin/app/v3/fetch_user_post_videos",
            {
                "sec_user_id": creator_id,
                "max_cursor": "0",
                "count": str(limit),
                "sort_type": "0",
            },
        )
        items = (data.get("data") or {}).get("aweme_list") or []
        contents = [self._aweme_to_content(it) for it in items]
        if days and days > 0:
            contents = self._filter_by_days(contents, days)
        return contents

    # ------ 关键词搜索 ------

    def search(
        self,
        query: str,
        limit: int = 20,
        days: Optional[int] = 7,
    ) -> list[Content]:
        """综合搜索 V1 (POST /api/v1/douyin/search/fetch_general_search_v1)

        publish_time: "0"=不限 "1"=近一天 "7"=近一周 "180"=近半年
        """
        publish_time = "0"
        if days:
            if days <= 1:
                publish_time = "1"
            elif days <= 7:
                publish_time = "7"
            elif days <= 180:
                publish_time = "180"

        # 翻页累积，直到够 limit 条
        contents: list[Content] = []
        cursor = 0
        search_id = ""
        backtrace = ""

        for _ in range(5):  # 最多翻 5 页
            payload = {
                "keyword": query,
                "cursor": cursor,
                "sort_type": "0",
                "publish_time": publish_time,
                "filter_duration": "0",
                "content_type": "1",    # 1=视频
                "search_id": search_id,
                "backtrace": backtrace,
            }
            try:
                data = self._search_with_retry(payload)
            except Exception:
                break  # 当前页失败，已有结果还能用

            # 响应结构：{"data": {"data": [ {aweme_info, type}, ... ], "cursor": ..., "search_id": ..., "has_more": ...}}
            raw = data.get("data") or {}
            if isinstance(raw, list):
                items = raw
                has_more = False
            else:
                items = raw.get("data") or raw.get("aweme_list") or []
                has_more = bool(raw.get("has_more"))
                cursor = raw.get("cursor", cursor)
                search_id = raw.get("search_id", search_id)
                backtrace = raw.get("backtrace", backtrace)

            for entry in items:
                aweme = entry.get("aweme_info") if isinstance(entry, dict) else None
                aweme = aweme or entry
                if not isinstance(aweme, dict) or not aweme.get("aweme_id"):
                    continue
                contents.append(self._aweme_to_content(aweme))
                if len(contents) >= limit:
                    break

            if len(contents) >= limit or not has_more or not items:
                break

        if days and days > 0:
            contents = self._filter_by_days(contents, days)
        return contents[:limit]

    def _search_with_retry(self, payload: dict, *, max_v1: int = 3, max_v2: int = 1) -> dict:
        """TikHub 文档说 V1 失败率 <5%，建议重试 1-3 次；V2 稳定性更差只用作兜底"""
        last_err: Optional[Exception] = None
        for attempt in range(max_v1):
            try:
                return self._post("/api/v1/douyin/search/fetch_general_search_v1", payload)
            except Exception as e:
                last_err = e
                if attempt < max_v1 - 1:
                    time.sleep(0.5 + random.random())  # jitter
        # V1 全失败再试 V2
        for attempt in range(max_v2):
            try:
                return self._post("/api/v1/douyin/search/fetch_general_search_v2", payload)
            except Exception as e:
                last_err = e
                if attempt < max_v2 - 1:
                    time.sleep(0.5 + random.random())
        raise RuntimeError(f"search failed after {max_v1}+{max_v2} attempts: {last_err}")

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
        creator_id: str = "",
    ) -> list[Comment]:
        """抓一级评论 + 可选二级回复"""
        # 一级
        data = self._get(
            "/api/v1/douyin/app/v3/fetch_video_comments",
            {"aweme_id": content_id, "cursor": "0", "count": str(top_n)},
        )
        raw = data.get("data") or {}
        l1_items = raw.get("comments") or raw.get("data") or []
        comments: list[Comment] = []
        for item in l1_items[:top_n]:
            if not isinstance(item, dict):
                continue
            cid = str(item.get("cid") or item.get("id") or "")
            if not cid:
                continue
            c = Comment(
                comment_id=cid,
                author=(item.get("user") or {}).get("nickname", ""),
                text=item.get("text", "") or item.get("content", ""),
                likes=int(item.get("digg_count", 0) or 0),
                create_time=self._iso(item.get("create_time", 0)),
            )
            # 二级
            if fetch_replies:
                reply_count = int(item.get("reply_comment_total") or item.get("reply_comment_count") or 0)
                if reply_count > 0:
                    try:
                        c.replies = self._fetch_replies(content_id, cid, min(reply_count, 10))
                    except Exception:
                        c.replies = []
            comments.append(c)
        return comments

    def _fetch_replies(self, aweme_id: str, comment_id: str, count: int) -> list[Comment]:
        try:
            data = self._get(
                "/api/v1/douyin/app/v3/fetch_video_comment_replies",
                {"item_id": aweme_id, "comment_id": comment_id, "cursor": "0", "count": str(count)},
            )
        except Exception:
            return []
        raw = data.get("data") or {}
        items = raw.get("comments") or raw.get("data") or []
        out: list[Comment] = []
        for item in items[:count]:
            if not isinstance(item, dict):
                continue
            cid = str(item.get("cid") or item.get("id") or "")
            if not cid:
                continue
            out.append(Comment(
                comment_id=cid,
                author=(item.get("user") or {}).get("nickname", ""),
                text=item.get("text", "") or item.get("content", ""),
                likes=int(item.get("digg_count", 0) or 0),
                create_time=self._iso(item.get("create_time", 0)),
            ))
        return out

    # ------ 下载 ------

    def download_media(self, content: Content, output_path: str) -> bool:
        """纯 Python 下载：先直链，失败用 yt-dlp 兜底"""
        # 直链
        for url in content.media_urls:
            try:
                resp = requests.get(
                    url,
                    headers={
                        "User-Agent": "Mozilla/5.0 (Linux; Android 12) AppleWebKit/537.36",
                        "Referer": "https://www.douyin.com/",
                    },
                    stream=True,
                    timeout=120,
                )
                if resp.status_code == 200:
                    with open(output_path, "wb") as f:
                        for chunk in resp.iter_content(chunk_size=8192):
                            f.write(chunk)
                    if Path(output_path).stat().st_size > 10000:
                        return True
                    Path(output_path).unlink(missing_ok=True)
            except Exception:
                Path(output_path).unlink(missing_ok=True)

        # yt-dlp 兜底
        try:
            result = subprocess.run(
                ["yt-dlp", "--no-warnings", "-o", output_path, content.url],
                capture_output=True,
                text=True,
                timeout=180,
            )
            return result.returncode == 0 and Path(output_path).exists()
        except Exception:
            return False
