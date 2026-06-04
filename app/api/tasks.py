from __future__ import annotations
from typing import Optional
from fastapi import APIRouter, HTTPException, Query

from app.api.schemas import TaskResp
from app.services.task_service import TaskService
from app.tasks import get_runner


router = APIRouter(prefix="/api/tasks", tags=["tasks"])


def _to_resp(t) -> TaskResp:
    return TaskResp(
        id=t.id, kind=t.kind, status=t.status,
        group_id=t.group_id, source_id=t.source_id,
        params=t.params or {}, progress=t.progress or {},
        logs=list(t.logs or []), result=t.result or {}, error=t.error,
        created_at=t.created_at, started_at=t.started_at, finished_at=t.finished_at,
    )


@router.get("", response_model=list[TaskResp])
def list_tasks(
    kind: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=500),
):
    tasks = TaskService().list(kind=kind, status=status, limit=limit)
    return [_to_resp(t) for t in tasks]


@router.get("/{task_id}", response_model=TaskResp)
def get_task(task_id: str):
    t = TaskService().get(task_id)
    if not t:
        raise HTTPException(404, "task not found")
    return _to_resp(t)


@router.post("/{task_id}/cancel")
def cancel_task(task_id: str):
    ok = get_runner().cancel(task_id)
    if not ok:
        raise HTTPException(404, "task not running or not found")
    return {"ok": True}
