from __future__ import annotations
from datetime import datetime
from typing import Optional
from sqlmodel import Session, select

from app.db.schema import ContentItem, Source
from app.models.content import Content


class ContentRepo:
    """内容处理状态的持久化操作"""

    def __init__(self, session: Session):
        self.session = session

    def get(self, source_id: int, content_id: str) -> Optional[ContentItem]:
        return self.session.exec(
            select(ContentItem).where(
                ContentItem.source_id == source_id,
                ContentItem.content_id == content_id,
            )
        ).first()

    def list_by_platform_content(self, platform: str, content_id: str) -> list[ContentItem]:
        return list(self.session.exec(
            select(ContentItem).where(
                ContentItem.platform == platform,
                ContentItem.content_id == content_id,
            )
        ).all())

    def known_ids(self, source_id: int) -> set[str]:
        rows = self.session.exec(
            select(ContentItem.content_id).where(ContentItem.source_id == source_id)
        ).all()
        return {str(r) for r in rows}

    def upsert_from_content(self, source: Source, content: Content) -> ContentItem:
        now = datetime.now().isoformat()
        item = self.get(source.id, content.content_id)
        if not item:
            item = ContentItem(
                group_id=source.group_id,
                source_id=source.id,
                creator_id=source.creator_id,
                platform=content.platform,
                content_id=content.content_id,
                first_seen_at=now,
            )

        item.group_id = source.group_id
        item.creator_id = source.creator_id
        item.platform = content.platform
        item.content_type = str(content.content_type.value if hasattr(content.content_type, "value") else content.content_type)
        item.title = content.title or item.title
        item.author_id = content.author_id or item.author_id
        item.author_name = content.author_name or item.author_name
        item.url = content.url or item.url
        item.create_time = content.create_time or item.create_time
        item.statistics = content.statistics or item.statistics or {}
        item.last_seen_at = now
        item.updated_at = now
        self.session.add(item)
        self.session.commit()
        self.session.refresh(item)
        return item

    def upsert_from_metadata(self, source: Source, metadata: dict) -> ContentItem:
        now = datetime.now().isoformat()
        content_id = str(metadata.get("content_id") or metadata.get("video_id") or "")
        if not content_id:
            raise ValueError("metadata missing content_id")
        item = self.get(source.id, content_id)
        if not item:
            item = ContentItem(
                group_id=source.group_id,
                source_id=source.id,
                creator_id=source.creator_id,
                platform=metadata.get("platform") or source.platform,
                content_id=content_id,
                first_seen_at=metadata.get("downloaded_at") or now,
            )
        item.group_id = source.group_id
        item.creator_id = source.creator_id
        item.platform = metadata.get("platform") or source.platform
        item.title = metadata.get("title") or item.title
        item.author_id = metadata.get("author_id") or item.author_id
        item.author_name = metadata.get("author") or item.author_name
        item.url = metadata.get("url") or item.url
        item.create_time = metadata.get("create_time") or item.create_time
        item.file_size = int(metadata.get("file_size") or item.file_size or 0)
        item.statistics = metadata.get("statistics") or item.statistics or {}
        item.updated_at = now
        self.session.add(item)
        self.session.commit()
        self.session.refresh(item)
        return item

    def update_stage(
        self,
        source_id: int,
        content_id: str,
        *,
        media_status: Optional[str] = None,
        transcript_status: Optional[str] = None,
        comments_status: Optional[str] = None,
        signal_status: Optional[str] = None,
        profile_status: Optional[str] = None,
        media_error: Optional[str] = None,
        transcript_error: Optional[str] = None,
        comments_error: Optional[str] = None,
        signal_error: Optional[str] = None,
        profile_error: Optional[str] = None,
        file_size: Optional[int] = None,
    ) -> Optional[ContentItem]:
        item = self.get(source_id, content_id)
        if not item:
            return None

        updates = {
            "media_status": media_status,
            "transcript_status": transcript_status,
            "comments_status": comments_status,
            "signal_status": signal_status,
            "profile_status": profile_status,
            "media_error": media_error,
            "transcript_error": transcript_error,
            "comments_error": comments_error,
            "signal_error": signal_error,
            "profile_error": profile_error,
        }
        for key, value in updates.items():
            if value is not None:
                setattr(item, key, value)
        if file_size is not None:
            item.file_size = int(file_size)
        item.updated_at = datetime.now().isoformat()
        self.session.add(item)
        self.session.commit()
        self.session.refresh(item)
        return item

    def list_ready_for_signal(self, source_id: int, *, limit: int = 500) -> list[ContentItem]:
        stmt = (
            select(ContentItem)
            .where(ContentItem.source_id == source_id)
            .where(ContentItem.transcript_status == "succeeded")
            .where(ContentItem.signal_status != "succeeded")
            .order_by(ContentItem.create_time.desc())
            .limit(limit)
        )
        return list(self.session.exec(stmt).all())

    def list_ready_for_profile(self, source_id: int, *, limit: int = 500) -> list[ContentItem]:
        stmt = (
            select(ContentItem)
            .where(ContentItem.source_id == source_id)
            .where(ContentItem.signal_status == "succeeded")
            .where(ContentItem.profile_status.in_(["pending", "failed"]))
            .order_by(ContentItem.create_time.desc())
            .limit(limit)
        )
        return list(self.session.exec(stmt).all())

    def list_by_source(self, source_id: int, *, limit: int = 1000) -> list[ContentItem]:
        stmt = (
            select(ContentItem)
            .where(ContentItem.source_id == source_id)
            .order_by(ContentItem.create_time.desc())
            .limit(limit)
        )
        return list(self.session.exec(stmt).all())
