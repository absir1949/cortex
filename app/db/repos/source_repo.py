from __future__ import annotations
from datetime import datetime
from typing import Optional
from sqlalchemy import delete
from sqlmodel import Session, select

from app.db.schema import AnalyzedContent, ContentItem, RefreshRun, Signal, Source, SourceContent, Task


class SourceRepo:
    def __init__(self, session: Session):
        self.session = session

    def list_by_group(self, group_id: int, enabled_only: bool = False) -> list[Source]:
        stmt = select(Source).where(Source.group_id == group_id)
        if enabled_only:
            stmt = stmt.where(Source.enabled == True)  # noqa: E712
        return list(self.session.exec(stmt.order_by(Source.id)).all())

    def list_all_enabled(self) -> list[Source]:
        return list(self.session.exec(
            select(Source).where(Source.enabled == True).order_by(Source.id)  # noqa: E712
        ).all())

    def get(self, source_id: int) -> Optional[Source]:
        return self.session.get(Source, source_id)

    def find(self, group_id: int, platform: str, identifier: str) -> Optional[Source]:
        return self.session.exec(
            select(Source).where(
                Source.group_id == group_id,
                Source.platform == platform,
                Source.identifier == identifier,
            )
        ).first()

    def create(self, source: Source) -> Source:
        self.session.add(source)
        self.session.commit()
        self.session.refresh(source)
        return source

    def update(self, source: Source) -> Source:
        self.session.add(source)
        self.session.commit()
        self.session.refresh(source)
        return source

    def delete(self, source_id: int) -> None:
        source = self.session.get(Source, source_id)
        if source:
            self.session.exec(delete(Signal).where(Signal.source_id == source_id))
            self.session.exec(delete(SourceContent).where(SourceContent.source_id == source_id))
            self.session.exec(delete(RefreshRun).where(RefreshRun.source_id == source_id))
            self.session.exec(delete(ContentItem).where(ContentItem.source_id == source_id))
            self.session.exec(delete(AnalyzedContent).where(AnalyzedContent.source_id == source_id))
            self.session.exec(delete(Task).where(Task.source_id == source_id))
            self.session.delete(source)
            self.session.commit()

    def mark_checked(self, source_id: int, ok: bool, error: Optional[str] = None) -> None:
        source = self.session.get(Source, source_id)
        if not source:
            return
        source.last_check = datetime.now().isoformat()
        source.last_error = None if ok else (error or "unknown")
        self.session.add(source)
        self.session.commit()
