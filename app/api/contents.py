from __future__ import annotations
from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse

from app.storage.cache import ContentCache


router = APIRouter(prefix="/api/contents", tags=["contents"])

# 进程内缓存 content_id -> 转录原文。重新采集后可单条失效。
_transcript_cache: dict = {}


def _get_cached_transcript(content_id: str):
    """优先走进程缓存，未命中走 ContentCache（rglob），命中后回填缓存。"""
    if content_id in _transcript_cache:
        return _transcript_cache[content_id]
    text = ContentCache().get_transcript(content_id)
    if text:
        _transcript_cache[content_id] = text
    return text


def invalidate_transcript_cache(content_id: str) -> None:
    """重新采集后调用，清掉缓存的旧转录文本。"""
    _transcript_cache.pop(content_id, None)


@router.get("/{content_id}/transcript", response_class=PlainTextResponse)
def get_transcript(content_id: str):
    """按 content_id 全局查转录原文。点击「查看原文」时调用，结果按 content_id 缓存。"""
    text = _get_cached_transcript(content_id)
    if not text:
        raise HTTPException(404, "transcript not found")
    return text
