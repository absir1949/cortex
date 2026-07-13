from __future__ import annotations
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.schemas import SourceCreateReq, SourceUpdateReq, SourceBrief, SourceSummary
from app.auth import get_current_user
from app.authz import assert_group_owner, assert_source_owner
from app.db.engine import get_session
from app.db.schema import GlobalContent, Signal, SourceContent
from app.services.source_service import SourceService
from app.models.group import TaskKind
from app.tasks import get_runner


router = APIRouter(prefix="/api/groups/{group_id}/sources", tags=["sources"])


def _to_brief(s) -> SourceBrief:
    return SourceBrief(
        id=s.id, type=s.type, platform=s.platform, identifier=s.identifier,
        display_name=s.display_name, enabled=s.enabled,
        interval_hours=s.interval_hours, last_check=s.last_check,
        last_error=s.last_error, directory=s.directory,
    )


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    raw = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(raw)
        return parsed.replace(tzinfo=None) if parsed.tzinfo else parsed
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(value[:len(fmt)], fmt)
        except ValueError:
            continue
    return None


@router.get("/summary", response_model=list[SourceSummary])
def list_source_summaries(
    group_id: int,
    days: int = Query(7, ge=1, le=90),
    current_user: dict = Depends(get_current_user),
):
    """关注源列表摘要：用于专题侧栏和关注管理页。"""
    with get_session() as s:
        assert_group_owner(s, group_id, current_user)
    sources = SourceService().list_by_group(group_id)
    cutoff = datetime.now() - timedelta(days=days)
    out: list[SourceSummary] = []
    with get_session() as s:
        from sqlmodel import select
        for src in sources:
            items = s.exec(
                select(GlobalContent)
                .join(SourceContent, SourceContent.global_content_id == GlobalContent.id)
                .where(SourceContent.source_id == src.id)
            ).all()
            recent_global_ids: set[int] = set()
            for item in items:
                created = _parse_time(item.create_time)
                if created and created >= cutoff:
                    recent_global_ids.add(item.id)
            if recent_global_ids:
                signals = s.exec(
                    select(Signal).where(Signal.global_content_id.in_(list(recent_global_ids)))
                ).all()
                recent_content_count = len(recent_global_ids)
            else:
                signals = []
                recent_content_count = 0
            recent_signals = []
            for sig in signals:
                created = _parse_time(sig.created_at)
                if created and created >= cutoff:
                    recent_signals.append(sig)
            out.append(SourceSummary(
                **_to_brief(src).model_dump(),
                recent_content_count=recent_content_count,
                recent_signal_count=len(recent_signals),
                recent_new_signal_count=sum(1 for sig in recent_signals if sig.is_new),
                window_days=days,
            ))
    return out


@router.post("", response_model=SourceBrief, status_code=201)
def create_source(group_id: int, req: SourceCreateReq, current_user: dict = Depends(get_current_user)):
    with get_session() as s:
        assert_group_owner(s, group_id, current_user)
    try:
        src = SourceService().create(
            group_id,
            type=req.type,
            platform=req.platform,
            identifier=req.identifier,
            display_name=req.display_name,
            interval_hours=req.interval_hours,
            days=req.days,
            content_limit=req.content_limit,
            comment_top_n=req.comment_top_n,
            resolve_creator=req.resolve_creator,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    return _to_brief(src)


@router.patch("/{source_id}", response_model=SourceBrief)
def update_source(
    group_id: int,
    source_id: int,
    req: SourceUpdateReq,
    current_user: dict = Depends(get_current_user),
):
    """编辑作者：改名/启停/调整采集参数"""
    svc = SourceService()
    with get_session() as s:
        src = assert_source_owner(s, group_id, source_id, current_user)
    fields = {k: v for k, v in req.model_dump(exclude_unset=True).items() if v is not None}
    if not fields:
        return _to_brief(src)
    updated = svc.update(source_id, **fields)
    if not updated:
        raise HTTPException(404, "source not found")
    return _to_brief(updated)


@router.delete("/{source_id}", status_code=204)
def delete_source(group_id: int, source_id: int, current_user: dict = Depends(get_current_user)):
    svc = SourceService()
    with get_session() as s:
        assert_source_owner(s, group_id, source_id, current_user)
    svc.delete(source_id)
    return None


@router.post("/{source_id}/run", status_code=202)
def run_source(
    group_id: int,
    source_id: int,
    force: bool = Query(True),
    days: int = Query(7, ge=1, le=365),
    current_user: dict = Depends(get_current_user),
):
    """手动触发单个源采集。force=True 忽略 interval，days 控制回看天数。"""
    with get_session() as s:
        assert_source_owner(s, group_id, source_id, current_user)
    task_id = get_runner().enqueue(
        TaskKind.INGEST,
        params={"source_id": source_id, "analyze": False, "group_id": group_id,
                "force": force, "days": days},
        group_id=group_id,
        source_id=source_id,
    )
    return {"task_id": task_id, "status": "pending"}
