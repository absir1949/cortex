from __future__ import annotations
from typing import Optional
from sqlmodel import Session, select

from app.db.schema import Signal


class SignalRepo:
    """观点信号（去重判定结果）的持久化操作"""

    def __init__(self, session: Session):
        self.session = session

    def create(
        self,
        source_id: int,
        content_id: str,
        *,
        group_id: Optional[int] = None,
        is_new: bool = False,
        summary: str = "",
        matched_points: Optional[list] = None,
        new_points: Optional[list] = None,
    ) -> Signal:
        """upsert：同一 (source_id, content_id) 已存在则更新，否则新建"""
        existing = self.session.exec(
            select(Signal).where(
                Signal.source_id == source_id,
                Signal.content_id == content_id,
            )
        ).first()
        if existing:
            existing.group_id = group_id if group_id is not None else existing.group_id
            existing.is_new = is_new
            existing.summary = summary
            existing.matched_points = matched_points if matched_points is not None else existing.matched_points
            existing.new_points = new_points if new_points is not None else existing.new_points
            self.session.add(existing)
        else:
            existing = Signal(
                group_id=group_id,
                source_id=source_id,
                content_id=content_id,
                is_new=is_new,
                summary=summary,
                matched_points=matched_points or [],
                new_points=new_points or [],
            )
            self.session.add(existing)
        self.session.commit()
        self.session.refresh(existing)
        return existing

    def get_by_content(self, source_id: int, content_id: str) -> Optional[Signal]:
        return self.session.exec(
            select(Signal).where(
                Signal.source_id == source_id,
                Signal.content_id == content_id,
            )
        ).first()

    def list_by_group(
        self,
        group_id: int,
        *,
        is_new: Optional[bool] = None,
        limit: int = 100,
    ) -> list[Signal]:
        stmt = select(Signal).where(Signal.group_id == group_id)
        if is_new is not None:
            stmt = stmt.where(Signal.is_new == is_new)
        stmt = stmt.order_by(Signal.created_at.desc()).limit(limit)
        return list(self.session.exec(stmt).all())

    def list_by_source(
        self,
        source_id: int,
        *,
        is_new: Optional[bool] = None,
        limit: int = 100,
    ) -> list[Signal]:
        stmt = select(Signal).where(Signal.source_id == source_id)
        if is_new is not None:
            stmt = stmt.where(Signal.is_new == is_new)
        stmt = stmt.order_by(Signal.created_at.desc()).limit(limit)
        return list(self.session.exec(stmt).all())

    def list_recent(self, *, is_new: Optional[bool] = None, limit: int = 20) -> list[Signal]:
        stmt = select(Signal)
        if is_new is not None:
            stmt = stmt.where(Signal.is_new == is_new)
        stmt = stmt.order_by(Signal.created_at.desc()).limit(limit)
        return list(self.session.exec(stmt).all())

    def list_recent_by_group_ids(
        self,
        group_ids: list[int],
        *,
        is_new: Optional[bool] = None,
        limit: int = 20,
    ) -> list[Signal]:
        if not group_ids:
            return []
        stmt = select(Signal).where(Signal.group_id.in_(group_ids))
        if is_new is not None:
            stmt = stmt.where(Signal.is_new == is_new)
        stmt = stmt.order_by(Signal.created_at.desc()).limit(limit)
        return list(self.session.exec(stmt).all())

    def list_new_by_group(self, group_id: int, *, limit: int = 100) -> list[Signal]:
        """组内所有「新观点」信号（日报/前端重点展示用）"""
        return self.list_by_group(group_id, is_new=True, limit=limit)
