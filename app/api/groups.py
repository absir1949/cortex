from __future__ import annotations
from fastapi import APIRouter, HTTPException, Query

from app.api.schemas import (
    GroupCreateReq, GroupUpdateReq,
    GroupResp, GroupDetailResp, SourceBrief,
)
from app.services.group_service import GroupService
from app.services.source_service import SourceService
from app.db.engine import get_session
from app.db.repos import GroupRepo
from app.models.group import TaskKind
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


@router.get("", response_model=list[GroupResp])
def list_groups():
    svc = GroupService()
    groups = svc.list()
    # 查每组的 source_count
    with get_session() as s:
        repo = GroupRepo(s)
        counts = {g.id: repo.source_count(g.id) for g in groups}
    return [_to_resp(g, counts.get(g.id, 0)) for g in groups]


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
