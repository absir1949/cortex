from __future__ import annotations
from pathlib import Path
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

from app.api.schemas import ReportBrief, ReportDetail
from app.services.report_service import ReportService


router = APIRouter(prefix="/api", tags=["reports"])


@router.get("/groups/{group_id}/reports", response_model=list[ReportBrief])
def list_group_reports(group_id: int, limit: int = Query(20), offset: int = Query(0)):
    svc = ReportService()
    reports = svc.list_by_group(group_id, limit=limit, offset=offset)
    return [ReportBrief(
        id=r.id, group_id=r.group_id, task_id=r.task_id,
        kind=r.kind, title=r.title, summary=r.summary, created_at=r.created_at,
    ) for r in reports]


@router.get("/reports/recent", response_model=list[ReportBrief])
def list_recent_reports(limit: int = Query(10)):
    reports = ReportService().list_recent(limit=limit)
    return [ReportBrief(
        id=r.id, group_id=r.group_id, task_id=r.task_id,
        kind=r.kind, title=r.title, summary=r.summary, created_at=r.created_at,
    ) for r in reports]


@router.get("/reports/{report_id}", response_model=ReportDetail)
def get_report(report_id: int):
    svc = ReportService()
    r = svc.get(report_id)
    if not r:
        raise HTTPException(404, "report not found")
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
def download_report(report_id: int, format: str = Query("md", pattern="^(md|json)$")):
    svc = ReportService()
    r = svc.get(report_id)
    if not r:
        raise HTTPException(404, "report not found")
    path = r.content_md_path if format == "md" else r.content_json_path
    if not path or not Path(path).exists():
        raise HTTPException(404, "file not found")
    return FileResponse(path, filename=Path(path).name)
