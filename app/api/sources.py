from __future__ import annotations
from fastapi import APIRouter, HTTPException

from app.api.schemas import SourceCreateReq, SourceBrief
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


@router.post("", response_model=SourceBrief, status_code=201)
def create_source(group_id: int, req: SourceCreateReq):
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


@router.delete("/{source_id}", status_code=204)
def delete_source(group_id: int, source_id: int):
    svc = SourceService()
    src = svc.get(source_id)
    if not src or src.group_id != group_id:
        raise HTTPException(404, "source not found")
    svc.delete(source_id)
    return None


@router.post("/{source_id}/run", status_code=202)
def run_source(group_id: int, source_id: int):
    """手动触发单个源采集 - 返回 task_id"""
    svc = SourceService()
    src = svc.get(source_id)
    if not src or src.group_id != group_id:
        raise HTTPException(404, "source not found")
    task_id = get_runner().enqueue(
        TaskKind.INGEST,
        params={"source_id": source_id, "analyze": False, "group_id": group_id},
        group_id=group_id,
        source_id=source_id,
    )
    return {"task_id": task_id, "status": "pending"}
