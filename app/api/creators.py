from __future__ import annotations
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse
from sqlmodel import select

from app.auth import get_current_user
from app.authz import assert_source_owner
from app.db.engine import get_session
from app.db.repos import CreatorRepo, SignalRepo
from app.db.schema import GlobalContent, Signal, SourceContent
from app.storage import paths
from app.storage.fs import GlobalStorage


router = APIRouter(prefix="/api", tags=["creators"])


@router.get("/groups/{group_id}/sources/{source_id}")
def get_source_detail(
    group_id: int,
    source_id: int,
    current_user: dict = Depends(get_current_user),
):
    """博主主页顶部信息：博主身份 + 平台账号 + 最近活跃"""
    with get_session() as s:
        src = assert_source_owner(s, group_id, source_id, current_user)
        creator = CreatorRepo(s).get(src.creator_id) if src.creator_id else None
        aliases = CreatorRepo(s).aliases_for(src.creator_id) if src.creator_id else []

    return {
        "source_id": src.id,
        "creator_id": src.creator_id,
        "name": creator.name if creator else src.display_name,
        "slug": creator.slug if creator else None,
        "bio": creator.bio if creator else "",
        "platform": src.platform,
        "identifier": src.identifier,
        "display_name": src.display_name,
        "enabled": src.enabled,
        "last_check": src.last_check,
        "last_error": src.last_error,
        "aliases": [
            {"platform": a.platform, "platform_uid": a.platform_uid, "display_name": a.display_name}
            for a in aliases
        ],
    }


@router.get("/groups/{group_id}/sources/{source_id}/contents")
def list_source_contents(
    group_id: int,
    source_id: int,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: dict = Depends(get_current_user),
):
    """博主的内容列表（带信号标记），用于博主主页"""
    with get_session() as s:
        src = assert_source_owner(s, group_id, source_id, current_user)

    with get_session() as s:
        all_rows = s.exec(
            select(GlobalContent)
            .join(SourceContent, SourceContent.global_content_id == GlobalContent.id)
            .where(SourceContent.source_id == source_id)
            .order_by(GlobalContent.create_time.desc())
        ).all()
        total = len(all_rows)
        page_rows = all_rows[offset:offset + limit]
        global_ids = [row.id for row in page_rows if row.id is not None]
        sig_rows = s.exec(select(Signal).where(Signal.global_content_id.in_(global_ids))).all() if global_ids else []
        sig_map = {r.global_content_id: r for r in sig_rows}

    out = []
    for item in page_rows:
        sig = sig_map.get(item.id)
        storage = GlobalStorage(item.platform, item.creator_id)
        out.append({
            "global_content_id": item.id,
            "content_id": item.content_id,
            "title": item.title,
            "url": item.url,
            "create_time": item.create_time,
            "platform": item.platform,
            "statistics": item.statistics or {},
            "transcribed": bool(storage.get_transcript(item.content_id)),
            "is_new_signal": bool(sig and sig.is_new) if sig else None,  # None=未判定
            "signal_summary": sig.summary if sig else "",
        })
    return {"items": out, "total": total}


@router.get("/groups/{group_id}/sources/{source_id}/signals")
def list_source_signals(
    group_id: int,
    source_id: int,
    limit: int = Query(50, ge=1, le=200),
    current_user: dict = Depends(get_current_user),
):
    """博主的信号历史（新观点时间线）"""
    with get_session() as s:
        assert_source_owner(s, group_id, source_id, current_user)
        global_ids = s.exec(
            select(SourceContent.global_content_id)
            .where(SourceContent.source_id == source_id)
            .order_by(SourceContent.id.desc())
            .limit(limit)
        ).all()
        signals = s.exec(
            select(Signal)
            .where(Signal.global_content_id.in_([int(i) for i in global_ids]))
            .order_by(Signal.created_at.desc())
            .limit(limit)
        ).all() if global_ids else SignalRepo(s).list_by_source(source_id, limit=limit)
    return [
        {
            "id": sig.id,
            "global_content_id": sig.global_content_id,
            "content_id": sig.content_id,
            "is_new": sig.is_new,
            "summary": sig.summary,
            "new_points": list(sig.new_points or []),
            "matched_points": list(sig.matched_points or []),
            "created_at": sig.created_at,
        }
        for sig in signals
    ]


@router.get("/groups/{group_id}/sources/{source_id}/profile", response_class=PlainTextResponse)
def get_source_profile_md(
    group_id: int,
    source_id: int,
    current_user: dict = Depends(get_current_user),
):
    """博主的观点档案（markdown 原文）"""
    with get_session() as s:
        src = assert_source_owner(s, group_id, source_id, current_user)
    if not src.creator_id:
        return f"# {src.display_name} 的观点档案\n\n（尚未关联博主身份，采集后会自动建立）"
    path = paths.profile_path(src.creator_id)
    if not path.exists():
        return f"# {src.display_name} 的观点档案\n\n（尚未建立档案，采集后会自动生成）"
    return path.read_text(encoding="utf-8")
