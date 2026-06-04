from __future__ import annotations
from sqlmodel import Session, select

from app.db.schema import AnalyzedContent


class AnalyzedRepo:
    def __init__(self, session: Session):
        self.session = session

    def mark(self, source_id: int, content_id: str) -> None:
        """幂等：重复调用不报错"""
        existing = self.session.exec(
            select(AnalyzedContent).where(
                AnalyzedContent.source_id == source_id,
                AnalyzedContent.content_id == content_id,
            )
        ).first()
        if existing:
            return
        self.session.add(AnalyzedContent(source_id=source_id, content_id=content_id))
        self.session.commit()

    def mark_many(self, source_id: int, content_ids: list[str]) -> None:
        existing = set(
            self.session.exec(
                select(AnalyzedContent.content_id).where(
                    AnalyzedContent.source_id == source_id
                )
            ).all()
        )
        added = False
        for cid in content_ids:
            if cid in existing:
                continue
            self.session.add(AnalyzedContent(source_id=source_id, content_id=cid))
            added = True
        if added:
            self.session.commit()

    def is_analyzed(self, source_id: int, content_id: str) -> bool:
        return self.session.exec(
            select(AnalyzedContent).where(
                AnalyzedContent.source_id == source_id,
                AnalyzedContent.content_id == content_id,
            )
        ).first() is not None

    def get_analyzed_ids(self, source_id: int) -> set[str]:
        rows = self.session.exec(
            select(AnalyzedContent.content_id).where(AnalyzedContent.source_id == source_id)
        ).all()
        return set(rows)
