from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException

from app.api.schemas import ResearchReq
from app.auth import get_current_user
from app.authz import assert_group_owner
from app.db.engine import get_session
from app.tasks import get_runner
from app.models.group import TaskKind


router = APIRouter(prefix="/api/groups/{group_id}/research", tags=["research"])


@router.post("", status_code=202)
def create_research(group_id: int, req: ResearchReq, current_user: dict = Depends(get_current_user)):
    with get_session() as s:
        assert_group_owner(s, group_id, current_user)
    if not req.question.strip():
        raise HTTPException(400, "question is required")

    task_id = get_runner().enqueue(
        TaskKind.RESEARCH,
        params=req.model_dump(exclude_none=True),
        group_id=group_id,
    )
    return {"task_id": task_id, "status": "pending"}
