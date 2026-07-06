from __future__ import annotations
from typing import Optional
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import PlainTextResponse

from app.db.engine import get_session
from app.db.repos import SignalRepo, GroupRepo, SourceRepo
from app.services import config_service
from app.storage import paths
from app.storage.fs import StorageManager


router = APIRouter(prefix="/api", tags=["signals"])


def _to_brief(sig) -> dict:
    return {
        "id": sig.id,
        "group_id": sig.group_id,
        "source_id": sig.source_id,
        "content_id": sig.content_id,
        "is_new": sig.is_new,
        "summary": sig.summary,
        "matched_points": list(sig.matched_points or []),
        "new_points": list(sig.new_points or []),
        "created_at": sig.created_at,
    }


def _enrich_with_content(signals: list, sources: dict) -> list:
    """给信号列表附加 source_name/platform/url/title（从 metadata 读，按 source 批量）"""
    # 按 source_id 收集 content_id，批量读 metadata，避免逐条读盘
    storage_cache: dict[int, StorageManager] = {}
    out = []
    for sig in signals:
        d = _to_brief(sig)
        src = sources.get(sig.source_id)
        d["source_name"] = src.display_name if src else ""
        d["platform"] = src.platform if src else ""
        # 读 url/title
        url, title = "", ""
        if src:
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
):
    """最近的观点信号（首页新信号展示用）"""
    with get_session() as s:
        signals = SignalRepo(s).list_recent(is_new=is_new, limit=limit)
        source_ids = {sig.source_id for sig in signals}
        sources = {src.id: src for src in (SourceRepo(s).get(sid) for sid in source_ids) if src}
    return _enrich_with_content(signals, sources)


@router.get("/groups/{group_id}/signals")
def list_group_signals(
    group_id: int,
    is_new: Optional[bool] = Query(None),
    limit: int = Query(100, ge=1, le=500),
):
    """组内信号列表（可过滤新观点）"""
    with get_session() as s:
        if not GroupRepo(s).get(group_id):
            raise HTTPException(404, "group not found")
        signals = SignalRepo(s).list_by_group(group_id, is_new=is_new, limit=limit)
        sources = {src.id: src for src in SourceRepo(s).list_by_group(group_id)}
    return _enrich_with_content(signals, sources)


@router.get("/groups/{group_id}/signals/stats")
def group_signal_stats(group_id: int):
    """组内信号统计（新观点数 / 老调重弹数）"""
    with get_session() as s:
        if not GroupRepo(s).get(group_id):
            raise HTTPException(404, "group not found")
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
def get_group_insights(group_id: int, days: Optional[int] = Query(None, ge=1, le=90)):
    """按需重新生成跨博主趋势洞察。

    days 不传时，读 insight_lookback_days 配置作为默认值（与日报里的趋势提炼保持一致）。
    """
    with get_session() as s:
        if not GroupRepo(s).get(group_id):
            raise HTTPException(404, "group not found")
    # days 未指定则用配置默认值
    if days is None:
        days = config_service.system_int("insight_lookback_days", 14)
    from app.services.insight_service import InsightService
    return InsightService().build_group_insights(group_id, days=days)


@router.get("/groups/{group_id}/profile/{source_id}", response_class=PlainTextResponse)
def get_source_profile(group_id: int, source_id: int):
    """读单个 source 的观点档案（markdown 原文）"""
    with get_session() as s:
        group = GroupRepo(s).get(group_id)
        src = SourceRepo(s).get(source_id)
    if not group:
        raise HTTPException(404, "group not found")
    if not src or src.group_id != group_id:
        raise HTTPException(404, "source not found in this group")
    path = paths.profile_path(group.slug, src.id)
    if not path.exists():
        return f"# {src.display_name} 的观点档案\n\n（尚未建立档案，采集后会自动生成）"
    return path.read_text(encoding="utf-8")
