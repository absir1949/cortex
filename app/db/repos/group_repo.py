from __future__ import annotations
from datetime import datetime
from typing import Optional
from sqlmodel import Session, select

from app.db.schema import KnowledgeGroup, Source


class GroupRepo:
    def __init__(self, session: Session):
        self.session = session

    def list_all(self) -> list[KnowledgeGroup]:
        return list(self.session.exec(select(KnowledgeGroup).order_by(KnowledgeGroup.id)).all())

    def get(self, group_id: int) -> Optional[KnowledgeGroup]:
        return self.session.get(KnowledgeGroup, group_id)

    def get_by_slug(self, slug: str) -> Optional[KnowledgeGroup]:
        return self.session.exec(select(KnowledgeGroup).where(KnowledgeGroup.slug == slug)).first()

    def create(self, group: KnowledgeGroup) -> KnowledgeGroup:
        self.session.add(group)
        self.session.commit()
        self.session.refresh(group)
        return group

    def update(self, group: KnowledgeGroup) -> KnowledgeGroup:
        group.updated_at = datetime.now().isoformat()
        self.session.add(group)
        self.session.commit()
        self.session.refresh(group)
        return group

    def delete(self, group_id: int, cascade: bool = False) -> None:
        group = self.session.get(KnowledgeGroup, group_id)
        if not group:
            return
        if cascade:
            sources = self.session.exec(select(Source).where(Source.group_id == group_id)).all()
            for s in sources:
                self.session.delete(s)
        self.session.delete(group)
        self.session.commit()

    def source_count(self, group_id: int) -> int:
        return len(self.session.exec(select(Source).where(Source.group_id == group_id)).all())
