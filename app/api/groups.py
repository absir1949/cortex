from __future__ import annotations
from datetime import datetime, timedelta
from fastapi import APIRouter, HTTPException, Query

from app.api.schemas import (
    GroupCreateReq, GroupUpdateReq,
    GroupResp, GroupSummaryResp, GroupDetailResp, SourceBrief,
)
from app.services.group_service import GroupService
from app.services.source_service import SourceService
from app.db.engine import get_session
from app.db.repos import GroupRepo, SignalRepo
from app.models.group import TaskKind
from app.storage.fs import StorageManager
from app.tasks import get_runner


router = APIRouter(prefix="/api/groups", tags=["groups"])


def _to_resp(g, source_count: int = 0) -> GroupResp:
    return GroupResp(
        id=g.id,
        name=g.name,
        slug=g.slug,
        description=g.description,
        enabled=g.enabled,
        defaults=g.defaults or {},
        prompt_overrides=g.prompt_overrides or {},
        source_count=source_count,
        created_at=g.created_at,
        updated_at=g.updated_at,
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


@router.get("", response_model=list[GroupResp])
def list_groups():
    svc = GroupService()
    groups = svc.list()
    # 查每组的 source_count
    with get_session() as s:
        repo = GroupRepo(s)
        counts = {g.id: repo.source_count(g.id) for g in groups}
    return [_to_resp(g, counts.get(g.id, 0)) for g in groups]


@router.get("/summary", response_model=list[GroupSummaryResp])
def list_group_summaries(days: int = Query(7, ge=1, le=90)):
    groups = GroupService().list()
    cutoff = datetime.now() - timedelta(days=days)
    with get_session() as s:
        group_repo = GroupRepo(s)
        signal_repo = SignalRepo(s)
        out: list[GroupSummaryResp] = []
        for group in groups:
            sources = SourceService().list_by_group(group.id)
            recent_content_ids: set[tuple[int, str]] = set()
            failed_source_count = 0
            for src in sources:
                if src.last_error:
                    failed_source_count += 1
                for md in StorageManager(src.directory).list_metadata():
                    created = _parse_time(md.get("create_time", ""))
                    if not created or created < cutoff:
                        continue
                    cid = md.get("content_id") or md.get("video_id")
                    if cid:
                        recent_content_ids.add((src.id, cid))
            recent_signals = []
            for sig in signal_repo.list_by_group(group.id, limit=1000):
                created = _parse_time(sig.created_at)
                if created and created >= cutoff:
                    recent_signals.append(sig)
            out.append(GroupSummaryResp(
                **_to_resp(group, group_repo.source_count(group.id)).model_dump(),
                recent_content_count=len(recent_content_ids),
                recent_signal_count=len(recent_signals),
                recent_new_signal_count=sum(1 for sig in recent_signals if sig.is_new),
                failed_source_count=failed_source_count,
                window_days=days,
            ))
    return out


@router.post("", response_model=GroupResp, status_code=201)
def create_group(req: GroupCreateReq):
    try:
        g = GroupService().create(
            name=req.name,
            slug=req.slug,
            description=req.description,
            defaults=req.defaults,
            prompt_overrides=req.prompt_overrides,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    return _to_resp(g, 0)


@router.get("/{group_id}", response_model=GroupDetailResp)
def get_group(group_id: int):
    svc = GroupService()
    g = svc.get(group_id)
    if not g:
        raise HTTPException(404, "group not found")
    sources = SourceService().list_by_group(group_id)
    return GroupDetailResp(
        **_to_resp(g, len(sources)).model_dump(),
        sources=[SourceBrief(
            id=s.id,
            type=s.type,
            platform=s.platform,
            identifier=s.identifier,
            display_name=s.display_name,
            enabled=s.enabled,
            interval_hours=s.interval_hours,
            last_check=s.last_check,
            last_error=s.last_error,
            directory=s.directory,
        ) for s in sources],
    )


@router.patch("/{group_id}", response_model=GroupResp)
def update_group(group_id: int, req: GroupUpdateReq):
    g = GroupService().update(group_id, **req.model_dump(exclude_unset=True))
    if not g:
        raise HTTPException(404, "group not found")
    try:
        from app.scheduler import get_scheduler
        get_scheduler().reload()
    except Exception:
        pass
    with get_session() as s:
        count = GroupRepo(s).source_count(g.id)
    return _to_resp(g, count)


@router.post("/{group_id}/run", status_code=202)
def run_group(group_id: int, force: bool = Query(True), analyze: bool = Query(True)):
    g = GroupService().get(group_id)
    if not g:
        raise HTTPException(404, "group not found")
    task_id = get_runner().enqueue(
        TaskKind.INGEST,
        params={"group_id": group_id, "force": force, "analyze": analyze},
        group_id=group_id,
    )
    return {"task_id": task_id, "status": "pending"}


@router.post("/{group_id}/analyze", status_code=202)
def analyze_group(group_id: int):
    """只整理报告，不重新采集。基于已有信号和转录产出日报。"""
    g = GroupService().get(group_id)
    if not g:
        raise HTTPException(404, "group not found")
    task_id = get_runner().enqueue(
        TaskKind.ANALYZE,
        params={"group_id": group_id},
        group_id=group_id,
    )
    return {"task_id": task_id, "status": "pending"}


@router.delete("/{group_id}", status_code=204)
def delete_group(group_id: int, cascade: bool = Query(False)):
    GroupService().delete(group_id, cascade=cascade)
    return None
