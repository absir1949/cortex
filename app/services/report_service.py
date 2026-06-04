"""报告服务"""
from __future__ import annotations
from pathlib import Path
from typing import Optional

from app.db.engine import get_session
from app.db.repos import ReportRepo
from app.db.schema import Report


class ReportService:

    def get(self, report_id: int) -> Optional[Report]:
        with get_session() as s:
            return ReportRepo(s).get(report_id)

    def list_by_group(self, group_id: int, limit: int = 20, offset: int = 0) -> list[Report]:
        with get_session() as s:
            return ReportRepo(s).list_by_group(group_id, limit=limit, offset=offset)

    def list_recent(self, limit: int = 10) -> list[Report]:
        with get_session() as s:
            return ReportRepo(s).list_recent(limit=limit)

    def get_content(self, report_id: int) -> Optional[str]:
        r = self.get(report_id)
        if not r:
            return None
        path = Path(r.content_md_path)
        if not path.exists():
            return None
        return path.read_text(encoding="utf-8")
