from __future__ import annotations
from datetime import datetime
from typing import Optional
from sqlalchemy import delete
from sqlmodel import Session, select

from app.db.schema import (
    AnalyzedContent,
    AskConversation,
    AskMessage,
    ContentItem,
    GroupContent,
    KnowledgeGroup,
    RefreshRun,
    Report,
    Signal,
    Source,
    SourceContent,
    Task,
)


class GroupRepo:
    def __init__(self, session: Session):
        self.session = session

    def list_all(self) -> list[KnowledgeGroup]:
        return list(self.session.exec(select(KnowledgeGroup).order_by(KnowledgeGroup.id)).all())

    def list_by_owner(self, owner_id: int) -> list[KnowledgeGroup]:
        return list(self.session.exec(
            select(KnowledgeGroup)
            .where(KnowledgeGroup.owner_id == owner_id)
            .order_by(KnowledgeGroup.id)
        ).all())

    def get(self, group_id: int) -> Optional[KnowledgeGroup]:
        return self.session.get(KnowledgeGroup, group_id)

    def get_by_slug(self, slug: str, owner_id: Optional[int] = None) -> Optional[KnowledgeGroup]:
        stmt = select(KnowledgeGroup).where(KnowledgeGroup.slug == slug)
        if owner_id is not None:
            stmt = stmt.where(KnowledgeGroup.owner_id == owner_id)
        return self.session.exec(stmt).first()

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
            source_ids = [s.id for s in sources if s.id is not None]
            conversations = self.session.exec(
                select(AskConversation.id).where(AskConversation.group_id == group_id)
            ).all()
            conversation_ids = [cid for cid in conversations if cid is not None]

            if conversation_ids:
                self.session.exec(delete(AskMessage).where(AskMessage.conversation_id.in_(conversation_ids)))
            self.session.exec(delete(AskConversation).where(AskConversation.group_id == group_id))

            self.session.exec(delete(Report).where(Report.group_id == group_id))
            self.session.exec(delete(RefreshRun).where(RefreshRun.group_id == group_id))
            self.session.exec(delete(Signal).where(Signal.group_id == group_id))
            self.session.exec(delete(ContentItem).where(ContentItem.group_id == group_id))
            self.session.exec(delete(GroupContent).where(GroupContent.group_id == group_id))

            if source_ids:
                self.session.exec(delete(SourceContent).where(SourceContent.source_id.in_(source_ids)))
                self.session.exec(delete(RefreshRun).where(RefreshRun.source_id.in_(source_ids)))
                self.session.exec(delete(Signal).where(Signal.source_id.in_(source_ids)))
                self.session.exec(delete(ContentItem).where(ContentItem.source_id.in_(source_ids)))
                self.session.exec(delete(AnalyzedContent).where(AnalyzedContent.source_id.in_(source_ids)))
                self.session.exec(delete(Task).where(Task.source_id.in_(source_ids)))

            self.session.exec(delete(Task).where(Task.group_id == group_id))
            self.session.exec(delete(Source).where(Source.group_id == group_id))
        self.session.delete(group)
        self.session.commit()

    def source_count(self, group_id: int) -> int:
        return len(self.session.exec(select(Source).where(Source.group_id == group_id)).all())
