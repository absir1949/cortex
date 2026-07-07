from __future__ import annotations
from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse

from app.storage.cache import ContentCache


router = APIRouter(prefix="/api/contents", tags=["contents"])


@router.get("/{content_id}/transcript", response_class=PlainTextResponse)
def get_transcript(content_id: str):
    """按 content_id 全局查转录原文（不依赖 group/source）。供前端 hover 卡片用。"""
    text = ContentCache().get_transcript(content_id)
    if not text:
        raise HTTPException(404, "transcript not found")
    return text
