from __future__ import annotations
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse

from app.api.schemas import ReportBrief, ReportDetail
from app.auth import get_current_user
from app.authz import assert_group_owner, assert_report_owner, owned_group_ids
from app.db.engine import get_session
from app.services.report_service import ReportService


router = APIRouter(prefix="/api", tags=["reports"])


@router.get("/groups/{group_id}/reports", response_model=list[ReportBrief])
def list_group_reports(
    group_id: int,
    limit: int = Query(20),
    offset: int = Query(0),
    current_user: dict = Depends(get_current_user),
):
    with get_session() as s:
        assert_group_owner(s, group_id, current_user)
    svc = ReportService()
    reports = svc.list_by_group(group_id, limit=limit, offset=offset)
    return [ReportBrief(
        id=r.id, group_id=r.group_id, task_id=r.task_id,
        kind=r.kind, title=r.title, summary=r.summary, created_at=r.created_at,
    ) for r in reports]


@router.get("/reports/recent", response_model=list[ReportBrief])
def list_recent_reports(limit: int = Query(10), current_user: dict = Depends(get_current_user)):
    with get_session() as s:
        group_ids = owned_group_ids(s, current_user)
    reports = ReportService().list_recent_by_group_ids(group_ids, limit=limit)
    return [ReportBrief(
        id=r.id, group_id=r.group_id, task_id=r.task_id,
        kind=r.kind, title=r.title, summary=r.summary, created_at=r.created_at,
    ) for r in reports]


@router.get("/reports/{report_id}", response_model=ReportDetail)
def get_report(report_id: int, current_user: dict = Depends(get_current_user)):
    svc = ReportService()
    with get_session() as s:
        r = assert_report_owner(s, report_id, current_user)
    content = svc.get_content(report_id) or ""
    return ReportDetail(
        id=r.id, group_id=r.group_id, task_id=r.task_id,
        kind=r.kind, title=r.title, summary=r.summary, created_at=r.created_at,
        content_md=content,
        content_md_path=r.content_md_path,
        content_json_path=r.content_json_path,
        sources_used=list(r.sources_used or []),
    )


@router.get("/reports/{report_id}/download")
def download_report(
    report_id: int,
    format: str = Query("md", pattern="^(md|json)$"),
    current_user: dict = Depends(get_current_user),
):
    with get_session() as s:
        r = assert_report_owner(s, report_id, current_user)
    path = r.content_md_path if format == "md" else r.content_json_path
    if not path or not Path(path).exists():
        raise HTTPException(404, "file not found")
    return FileResponse(path, filename=Path(path).name)
