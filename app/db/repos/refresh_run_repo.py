from __future__ import annotations
from datetime import datetime
from typing import Optional
from sqlmodel import Session, select

from app.db.schema import RefreshRun


class RefreshRunRepo:
    """作者/专题刷新运行记录"""

    def __init__(self, session: Session):
        self.session = session

    def start(
        self,
        *,
        scope: str,
        mode: str = "refresh",
        group_id: Optional[int] = None,
        source_id: Optional[int] = None,
        parent_run_id: Optional[int] = None,
        task_id: Optional[str] = None,
        lookback_days: Optional[int] = None,
    ) -> RefreshRun:
        run = RefreshRun(
            scope=scope,
            mode=mode,
            status="running",
            group_id=group_id,
            source_id=source_id,
            parent_run_id=parent_run_id,
            task_id=task_id,
            lookback_days=lookback_days,
            counts={},
            errors=[],
        )
        self.session.add(run)
        self.session.commit()
        self.session.refresh(run)
        return run

    def finish(
        self,
        run_id: int,
        *,
        status: str,
        counts: Optional[dict] = None,
        errors: Optional[list] = None,
    ) -> Optional[RefreshRun]:
        run = self.session.get(RefreshRun, run_id)
        if not run:
            return None
        run.status = status
        run.counts = counts or {}
        run.errors = errors or []
        run.finished_at = datetime.now().isoformat()
        self.session.add(run)
        self.session.commit()
        self.session.refresh(run)
        return run

    def get(self, run_id: int) -> Optional[RefreshRun]:
        return self.session.get(RefreshRun, run_id)

    def list_by_group(self, group_id: int, *, limit: int = 20) -> list[RefreshRun]:
        stmt = (
            select(RefreshRun)
            .where(RefreshRun.group_id == group_id)
            .order_by(RefreshRun.started_at.desc())
            .limit(limit)
        )
        return list(self.session.exec(stmt).all())
