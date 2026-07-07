from __future__ import annotations
from functools import lru_cache
from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse

from app.storage.cache import ContentCache


router = APIRouter(prefix="/api/contents", tags=["contents"])


@lru_cache(maxsize=2048)
def _cached_transcript(content_id: str):
    """进程内缓存 content_id -> 转录原文。转录不可变，命中后不再 rglob。"""
    return ContentCache().get_transcript(content_id)


@router.get("/{content_id}/transcript", response_class=PlainTextResponse)
def get_transcript(content_id: str):
    """按 content_id 全局查转录原文。点击「查看原文」时调用，结果按 content_id 缓存。"""
    text = _cached_transcript(content_id)
    if not text:
        raise HTTPException(404, "transcript not found")
    return text
