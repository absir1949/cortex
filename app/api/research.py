from __future__ import annotations
from fastapi import APIRouter, HTTPException

from app.api.schemas import ResearchReq
from app.services.group_service import GroupService
from app.tasks import get_runner
from app.models.group import TaskKind


router = APIRouter(prefix="/api/groups/{group_id}/research", tags=["research"])


@router.post("", status_code=202)
def create_research(group_id: int, req: ResearchReq):
    group = GroupService().get(group_id)
    if not group:
        raise HTTPException(404, "group not found")
    if not req.question.strip():
        raise HTTPException(400, "question is required")

    task_id = get_runner().enqueue(
        TaskKind.RESEARCH,
        params=req.model_dump(exclude_none=True),
        group_id=group_id,
    )
    return {"task_id": task_id, "status": "pending"}
