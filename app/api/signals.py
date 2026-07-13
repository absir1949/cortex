from __future__ import annotations
import json
from pathlib import Path
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import select

from app.auth import get_current_user
from app.authz import assert_group_owner, owned_group_ids
from app.db.engine import get_session
from app.db.repos import SignalRepo, SourceRepo
from app.db.schema import GlobalContent, Report, Source, SourceContent
from app.models.group import ReportKind
from app.storage.fs import StorageManager


router = APIRouter(prefix="/api", tags=["signals"])


def _to_brief(sig) -> dict:
    return {
        "id": sig.id,
        "global_content_id": sig.global_content_id,
        "group_id": sig.group_id,
        "source_id": sig.source_id,
        "content_id": sig.content_id,
        "is_new": sig.is_new,
        "summary": sig.summary,
        "matched_points": list(sig.matched_points or []),
        "new_points": list(sig.new_points or []),
        "created_at": sig.created_at,
    }


def _enrich_with_content(signals: list, sources: dict, group_id: int | None = None) -> list:
    """给信号列表附加 source_name/platform/url/title/group_name"""
    # 批量查 group_name（一次 IN 查询，避免 N+1）
    group_ids = {src.group_id for src in sources.values() if src.group_id}
    group_names: dict[int, str] = {}
    if group_ids:
        with get_session() as s:
            from sqlmodel import select
            from app.db.schema import KnowledgeGroup
            rows = s.exec(select(KnowledgeGroup).where(KnowledgeGroup.id.in_(group_ids))).all()
            group_names = {r.id: r.name for r in rows}

    global_ids = [sig.global_content_id for sig in signals if getattr(sig, "global_content_id", None)]
    global_map: dict[int, GlobalContent] = {}
    source_for_global: dict[int, object] = {}
    if global_ids:
        with get_session() as s:
            from sqlmodel import select
            rows = s.exec(select(GlobalContent).where(GlobalContent.id.in_(global_ids))).all()
            global_map = {r.id: r for r in rows if r.id is not None}
            if group_id is not None:
                linked = s.exec(
                    select(SourceContent.global_content_id, Source)
                    .join(Source, Source.id == SourceContent.source_id)
                    .where(Source.group_id == group_id)
                    .where(SourceContent.global_content_id.in_(global_ids))
                ).all()
                source_for_global = {gid: src for gid, src in linked}

    storage_cache: dict[int, StorageManager] = {}
    out = []
    for sig in signals:
        d = _to_brief(sig)
        src = source_for_global.get(sig.global_content_id) or sources.get(sig.source_id)
        d["source_name"] = src.display_name if src else ""
        global_item = global_map.get(sig.global_content_id)
        d["platform"] = global_item.platform if global_item else (src.platform if src else "")
        d["group_name"] = group_names.get(src.group_id, "") if src else ""
        # 读 url/title
        url, title = "", ""
        if global_item:
            url = global_item.url
            title = global_item.title
        elif src:
            if src.id not in storage_cache:
                storage_cache[src.id] = StorageManager(src.directory)
            md = storage_cache[src.id].get_metadata(sig.content_id)
            if md:
                url = md.get("url", "")
                title = md.get("title", "")
        d["url"] = url
        d["title"] = title
        out.append(d)
    return out


@router.get("/signals/recent")
def list_recent_signals(
    is_new: Optional[bool] = Query(None),
    limit: int = Query(20, ge=1, le=100),
    current_user: dict = Depends(get_current_user),
):
    """最近的观点信号（首页新信号展示用）"""
    with get_session() as s:
        group_ids = owned_group_ids(s, current_user)
        signals = SignalRepo(s).list_recent_by_group_ids(group_ids, is_new=is_new, limit=limit)
        source_ids = {sig.source_id for sig in signals}
        sources = {src.id: src for src in (SourceRepo(s).get(sid) for sid in source_ids) if src}
    return _enrich_with_content(signals, sources)


@router.get("/groups/{group_id}/signals")
def list_group_signals(
    group_id: int,
    is_new: Optional[bool] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    current_user: dict = Depends(get_current_user),
):
    """组内信号列表（可过滤新观点）"""
    with get_session() as s:
        assert_group_owner(s, group_id, current_user)
        signals = SignalRepo(s).list_by_group(group_id, is_new=is_new, limit=limit)
        sources = {src.id: src for src in SourceRepo(s).list_by_group(group_id)}
    return _enrich_with_content(signals, sources, group_id=group_id)


@router.get("/groups/{group_id}/signals/stats")
def group_signal_stats(group_id: int, current_user: dict = Depends(get_current_user)):
    """组内信号统计（新观点数 / 老调重弹数）"""
    with get_session() as s:
        assert_group_owner(s, group_id, current_user)
        repo = SignalRepo(s)
        new_sigs = repo.list_by_group(group_id, is_new=True, limit=1000)
        old_sigs = repo.list_by_group(group_id, is_new=False, limit=1000)
    return {
        "group_id": group_id,
        "new_signal_count": len(new_sigs),
        "repeat_count": len(old_sigs),
        "total": len(new_sigs) + len(old_sigs),
    }


@router.get("/groups/{group_id}/insights")
def get_group_insights(
    group_id: int,
    days: Optional[int] = Query(None, ge=1, le=90),
    current_user: dict = Depends(get_current_user),
):
    """读取最新整理报告里的洞察快照，不在页面访问时实时消耗 LLM。"""
    with get_session() as s:
        assert_group_owner(s, group_id, current_user)
        report = s.exec(
            select(Report)
            .where(Report.group_id == group_id)
            .where(Report.kind == ReportKind.SCHEDULED.value)
            .order_by(Report.created_at.desc())
            .limit(1)
        ).first()
    if not report or not report.content_json_path:
        return None

    path = Path(report.content_json_path)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    insights = payload.get("insights")
    if not insights:
        return None
    return {
        "trends": list(insights.get("trends") or []),
        "raw_signal_count": int(insights.get("raw_signal_count") or 0),
        "creator_count": int(insights.get("creator_count") or 0),
        "days": int(insights.get("days") or days or 14),
        "overview": insights.get("overview") or "",
        "questions": list(insights.get("questions") or []),
        "period": insights.get("period"),
        "basis": insights.get("basis") or "report_snapshot",
        "report_id": report.id,
        "report_title": report.title,
        "generated_at": report.created_at,
    }
