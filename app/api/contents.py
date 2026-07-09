from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse

from app.auth import get_current_user
from app.authz import assert_content_owner
from app.db.engine import get_session
from app.db.schema import ContentItem, GlobalContent, Source
from app.storage.cache import ContentCache
from app.storage.fs import GlobalStorage, StorageManager


router = APIRouter(prefix="/api/contents", tags=["contents"])

# 进程内缓存 (platform, content_id) -> 转录原文。重新采集后可单条失效。
_transcript_cache: dict[tuple[str, str], str] = {}


def _get_cached_transcript(platform: str, content_id: str, source_directory: str | None = None):
    """优先走进程缓存，未命中走 ContentCache（rglob），命中后回填缓存。"""
    key = (platform, content_id)
    if key in _transcript_cache:
        return _transcript_cache[key]
    text = None
    if source_directory:
        text = StorageManager(source_directory).get_transcript(content_id)
    if not text:
        text = ContentCache().get_transcript(platform, content_id)
    if text:
        _transcript_cache[key] = text
    return text


def _get_cached_global_transcript(platform: str, content_id: str, creator_id: int | None = None):
    key = (platform, content_id)
    if key in _transcript_cache:
        return _transcript_cache[key]
    text = GlobalStorage(platform, creator_id).get_transcript(content_id)
    if not text:
        text = ContentCache().get_transcript(platform, content_id)
    if text:
        _transcript_cache[key] = text
    return text


def invalidate_transcript_cache(content_id: str, platform: str | None = None) -> None:
    """重新采集后调用，清掉缓存的旧转录文本。"""
    if platform:
        _transcript_cache.pop((platform, content_id), None)
        return
    for key in [k for k in _transcript_cache if k[1] == content_id]:
        _transcript_cache.pop(key, None)


@router.get("/{content_id}/transcript", response_class=PlainTextResponse)
def get_transcript(
    content_id: str,
    platform: str = Query(..., min_length=1),
    current_user: dict = Depends(get_current_user),
):
    """按 (platform, content_id) 查转录原文，且必须反查到当前用户拥有该内容。"""
    with get_session() as s:
        item = assert_content_owner(
            s,
            platform=platform,
            content_id=content_id,
            current_user=current_user,
        )
        if isinstance(item, GlobalContent):
            text = _get_cached_global_transcript(platform, content_id, item.creator_id)
        else:
            source = s.get(Source, item.source_id)
            source_directory = source.directory if source else None
            text = _get_cached_transcript(platform, content_id, source_directory)
    if not text:
        raise HTTPException(404, "transcript not found")
    return text
