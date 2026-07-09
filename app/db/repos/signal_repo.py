from __future__ import annotations
from typing import Optional
from sqlmodel import Session, select

from app.db.schema import GroupContent, Signal


class SignalRepo:
    """观点信号（去重判定结果）的持久化操作"""

    def __init__(self, session: Session):
        self.session = session

    def create(
        self,
        source_id: int,
        content_id: str,
        *,
        global_content_id: Optional[int] = None,
        group_id: Optional[int] = None,
        is_new: bool = False,
        summary: str = "",
        matched_points: Optional[list] = None,
        new_points: Optional[list] = None,
    ) -> Signal:
        """upsert：共享采集后同一 global_content_id 只保留一条信号。

        迁移期兼容旧数据：global_content_id 为空时继续按 (source_id, content_id)。
        """
        if global_content_id is not None:
            existing = self.session.exec(
                select(Signal).where(Signal.global_content_id == global_content_id)
            ).first()
        else:
            existing = self.session.exec(
                select(Signal).where(
                    Signal.source_id == source_id,
                    Signal.content_id == content_id,
                )
            ).first()
        if existing:
            existing.global_content_id = global_content_id if global_content_id is not None else existing.global_content_id
            existing.group_id = group_id if group_id is not None else existing.group_id
            existing.is_new = is_new
            existing.summary = summary
            existing.matched_points = matched_points if matched_points is not None else existing.matched_points
            existing.new_points = new_points if new_points is not None else existing.new_points
            self.session.add(existing)
        else:
            existing = Signal(
                global_content_id=global_content_id,
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

    def get_by_content(
        self,
        source_id: int,
        content_id: str,
        *,
        global_content_id: Optional[int] = None,
    ) -> Optional[Signal]:
        if global_content_id is not None:
            found = self.session.exec(
                select(Signal).where(Signal.global_content_id == global_content_id)
            ).first()
            if found:
                return found
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
        stmt = (
            select(Signal)
            .join(GroupContent, GroupContent.global_content_id == Signal.global_content_id)
            .where(GroupContent.group_id == group_id)
        )
        if is_new is not None:
            stmt = stmt.where(Signal.is_new == is_new)
        stmt = stmt.order_by(Signal.created_at.desc()).limit(limit)
        rows = list(self.session.exec(stmt).all())
        if rows:
            deduped: list[Signal] = []
            seen: set[int] = set()
            for row in rows:
                if row.id in seen:
                    continue
                seen.add(row.id)
                deduped.append(row)
            rows = deduped[:limit]
        if rows:
            return rows
        # 兼容尚未迁移的旧库/测试数据。
        legacy = select(Signal).where(Signal.group_id == group_id)
        if is_new is not None:
            legacy = legacy.where(Signal.is_new == is_new)
        return list(self.session.exec(legacy.order_by(Signal.created_at.desc()).limit(limit)).all())

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
        stmt = (
            select(Signal)
            .join(GroupContent, GroupContent.global_content_id == Signal.global_content_id)
            .where(GroupContent.group_id.in_(group_ids))
        )
        if is_new is not None:
            stmt = stmt.where(Signal.is_new == is_new)
        stmt = stmt.order_by(Signal.created_at.desc()).limit(limit)
        rows = list(self.session.exec(stmt).all())
        if rows:
            deduped: list[Signal] = []
            seen: set[int] = set()
            for row in rows:
                if row.id in seen:
                    continue
                seen.add(row.id)
                deduped.append(row)
            return deduped[:limit]
        legacy = select(Signal).where(Signal.group_id.in_(group_ids))
        if is_new is not None:
            legacy = legacy.where(Signal.is_new == is_new)
        return list(self.session.exec(legacy.order_by(Signal.created_at.desc()).limit(limit)).all())

    def list_new_by_group(self, group_id: int, *, limit: int = 100) -> list[Signal]:
        """组内所有「新观点」信号（日报/前端重点展示用）"""
        return self.list_by_group(group_id, is_new=True, limit=limit)
