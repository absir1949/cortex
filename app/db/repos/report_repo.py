from __future__ import annotations
from typing import Optional
from sqlmodel import Session, select

from app.db.schema import Report


class ReportRepo:
    def __init__(self, session: Session):
        self.session = session

    def create(self, report: Report) -> Report:
        self.session.add(report)
        self.session.commit()
        self.session.refresh(report)
        return report

    def get(self, report_id: int) -> Optional[Report]:
        return self.session.get(Report, report_id)

    def list_by_group(self, group_id: int, limit: int = 20, offset: int = 0) -> list[Report]:
        stmt = (
            select(Report)
            .where(Report.group_id == group_id)
            .order_by(Report.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(self.session.exec(stmt).all())

    def list_recent(self, limit: int = 10) -> list[Report]:
        stmt = select(Report).order_by(Report.created_at.desc()).limit(limit)
        return list(self.session.exec(stmt).all())

    def list_recent_by_group_ids(self, group_ids: list[int], limit: int = 10) -> list[Report]:
        if not group_ids:
            return []
        stmt = (
            select(Report)
            .where(Report.group_id.in_(group_ids))
            .order_by(Report.created_at.desc())
            .limit(limit)
        )
        return list(self.session.exec(stmt).all())
