from __future__ import annotations
from typing import Optional
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import PlainTextResponse

from app.db.engine import get_session
from app.db.repos import CreatorRepo, SourceRepo, GroupRepo, SignalRepo
from app.storage import paths
from app.storage.fs import StorageManager


router = APIRouter(prefix="/api", tags=["creators"])


@router.get("/groups/{group_id}/sources/{source_id}")
def get_source_detail(group_id: int, source_id: int):
    """博主主页顶部信息：博主身份 + 平台账号 + 最近活跃"""
    with get_session() as s:
        group = GroupRepo(s).get(group_id)
        if not group:
            raise HTTPException(404, "group not found")
        src = SourceRepo(s).get(source_id)
        if not src or src.group_id != group_id:
            raise HTTPException(404, "source not found in this group")
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
):
    """博主的内容列表（带信号标记），用于博主主页"""
    with get_session() as s:
        src = SourceRepo(s).get(source_id)
        if not src or src.group_id != group_id:
            raise HTTPException(404, "source not found")

    storage = StorageManager(src.directory)
    mds = storage.list_metadata()  # 已按 create_time 倒序
    page_mds = mds[offset:offset + limit]
    # 按本页 content_id 精确查信号（避免全量拉取 + 500 上限漏标）
    page_cids = [md.get("content_id") or md.get("video_id") for md in page_mds]
    page_cids = [c for c in page_cids if c]
    sig_map: dict[str, object] = {}
    if page_cids:
        with get_session() as s:
            from sqlmodel import select
            from app.db.schema import Signal
            rows = s.exec(
                select(Signal).where(
                    Signal.source_id == source_id,
                    Signal.content_id.in_(page_cids),
                )
            ).all()
            sig_map = {r.content_id: r for r in rows}

    out = []
    for md in page_mds:
        cid = md.get("content_id") or md.get("video_id")
        if not cid:
            continue
        sig = sig_map.get(cid)
        out.append({
            "content_id": cid,
            "title": md.get("title", ""),
            "url": md.get("url", ""),
            "create_time": md.get("create_time", ""),
            "platform": md.get("platform", src.platform),
            "statistics": md.get("statistics", {}),
            "transcribed": bool(md.get("transcribed")),
            "is_new_signal": bool(sig and sig.is_new) if sig else None,  # None=未判定
            "signal_summary": sig.summary if sig else "",
        })
    return {"items": out, "total": len(mds)}


@router.get("/groups/{group_id}/sources/{source_id}/signals")
def list_source_signals(
    group_id: int,
    source_id: int,
    limit: int = Query(50, ge=1, le=200),
):
    """博主的信号历史（新观点时间线）"""
    with get_session() as s:
        src = SourceRepo(s).get(source_id)
        if not src or src.group_id != group_id:
            raise HTTPException(404, "source not found")
        signals = SignalRepo(s).list_by_source(source_id, limit=limit)
    return [
        {
            "id": sig.id,
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
def get_source_profile_md(group_id: int, source_id: int):
    """博主的观点档案（markdown 原文）"""
    with get_session() as s:
        src = SourceRepo(s).get(source_id)
        if not src or src.group_id != group_id:
            raise HTTPException(404, "source not found")
    if not src.creator_id:
        return f"# {src.display_name} 的观点档案\n\n（尚未关联博主身份，采集后会自动建立）"
    path = paths.profile_path(src.creator_id)
    if not path.exists():
        return f"# {src.display_name} 的观点档案\n\n（尚未建立档案，采集后会自动生成）"
    return path.read_text(encoding="utf-8")
