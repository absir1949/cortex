from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import func
from sqlmodel import Session, select

from app.db.schema import (
    Creator,
    GlobalContent,
    GroupContent,
    IngestTarget,
    Source,
    SourceContent,
)
from app.models.content import Content


def _now() -> str:
    return datetime.now().isoformat()


def _content_type_value(content: Content) -> str:
    raw = content.content_type
    return str(raw.value if hasattr(raw, "value") else raw)


def _normalize_target_key(value: str) -> str:
    return " ".join((value or "").strip().split())


class GlobalContentRepo:
    def __init__(self, session: Session):
        self.session = session

    def get(self, global_content_id: int) -> Optional[GlobalContent]:
        return self.session.get(GlobalContent, global_content_id)

    def get_by_platform_content(self, platform: str, content_id: str) -> Optional[GlobalContent]:
        return self.session.exec(
            select(GlobalContent).where(
                GlobalContent.platform == platform,
                GlobalContent.content_id == content_id,
            )
        ).first()

    def known_ids(self, platform: str, content_ids: list[str]) -> set[str]:
        if not content_ids:
            return set()
        rows = self.session.exec(
            select(GlobalContent.content_id).where(
                GlobalContent.platform == platform,
                GlobalContent.content_id.in_(content_ids),
            )
        ).all()
        return {str(r) for r in rows}

    def upsert_from_content(self, content: Content, *, creator_id: Optional[int] = None) -> GlobalContent:
        now = _now()
        item = self.get_by_platform_content(content.platform, content.content_id)
        if not item:
            item = GlobalContent(
                platform=content.platform,
                content_id=content.content_id,
                creator_id=creator_id,
                first_seen_at=now,
            )
        if creator_id is not None:
            item.creator_id = creator_id
        item.content_type = _content_type_value(content)
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

    def update_stage(self, global_content_id: int, **kwargs) -> Optional[GlobalContent]:
        item = self.session.get(GlobalContent, global_content_id)
        if not item:
            return None
        for key, value in kwargs.items():
            if value is not None and hasattr(item, key):
                setattr(item, key, value)
        item.updated_at = _now()
        self.session.add(item)
        self.session.commit()
        self.session.refresh(item)
        return item

    def list_by_ids(self, ids: list[int]) -> dict[int, GlobalContent]:
        if not ids:
            return {}
        rows = self.session.exec(select(GlobalContent).where(GlobalContent.id.in_(ids))).all()
        return {int(r.id): r for r in rows if r.id is not None}


class SourceContentRepo:
    def __init__(self, session: Session):
        self.session = session

    def upsert(
        self,
        *,
        source_id: int,
        global_content_id: int,
        ingest_target_id: Optional[int] = None,
        matched_query: str = "",
    ) -> SourceContent:
        row = self.session.exec(
            select(SourceContent).where(
                SourceContent.source_id == source_id,
                SourceContent.global_content_id == global_content_id,
            )
        ).first()
        if not row:
            row = SourceContent(
                source_id=source_id,
                global_content_id=global_content_id,
                first_seen_at=_now(),
            )
        row.ingest_target_id = ingest_target_id
        row.matched_query = matched_query or row.matched_query or ""
        self.session.add(row)
        self.session.commit()
        self.session.refresh(row)
        return row

    def list_global_ids_for_source(self, source_id: int, *, limit: int = 1000) -> list[int]:
        rows = self.session.exec(
            select(SourceContent.global_content_id)
            .where(SourceContent.source_id == source_id)
            .order_by(SourceContent.id.desc())
            .limit(limit)
        ).all()
        return [int(r) for r in rows if r is not None]

    def sources_for_global_in_group(self, group_id: int, global_content_id: int) -> list[Source]:
        stmt = (
            select(Source)
            .join(SourceContent, SourceContent.source_id == Source.id)
            .where(Source.group_id == group_id)
            .where(SourceContent.global_content_id == global_content_id)
            .order_by(Source.id)
        )
        return list(self.session.exec(stmt).all())


class GroupContentRepo:
    def __init__(self, session: Session):
        self.session = session

    def upsert(self, *, group_id: int, global_content_id: int) -> GroupContent:
        row = self.session.exec(
            select(GroupContent).where(
                GroupContent.group_id == group_id,
                GroupContent.global_content_id == global_content_id,
            )
        ).first()
        if not row:
            row = GroupContent(
                group_id=group_id,
                global_content_id=global_content_id,
                first_seen_at=_now(),
            )
            self.session.add(row)
            self.session.commit()
            self.session.refresh(row)
        return row

    def list_global_ids_by_group(self, group_id: int, *, limit: int = 1000) -> list[int]:
        rows = self.session.exec(
            select(GroupContent.global_content_id)
            .where(GroupContent.group_id == group_id)
            .order_by(GroupContent.first_seen_at.desc())
            .limit(limit)
        ).all()
        return [int(r) for r in rows if r is not None]

    def list_unanalyzed_by_group(self, group_id: int, *, limit: int = 500) -> list[GroupContent]:
        return list(self.session.exec(
            select(GroupContent)
            .where(GroupContent.group_id == group_id)
            .where(GroupContent.analyzed_at.is_(None))
            .order_by(GroupContent.first_seen_at.desc())
            .limit(limit)
        ).all())

    def mark_analyzed(self, group_id: int, global_content_ids: list[int]) -> None:
        if not global_content_ids:
            return
        rows = self.session.exec(
            select(GroupContent).where(
                GroupContent.group_id == group_id,
                GroupContent.global_content_id.in_(global_content_ids),
            )
        ).all()
        now = _now()
        for row in rows:
            row.analyzed_at = now
            self.session.add(row)
        self.session.commit()

    def delete_if_unlinked(self, *, group_id: int, global_content_id: int) -> None:
        remaining = self.session.exec(
            select(SourceContent.id)
            .join(Source, Source.id == SourceContent.source_id)
            .where(Source.group_id == group_id)
            .where(SourceContent.global_content_id == global_content_id)
            .limit(1)
        ).first()
        if remaining:
            return
        row = self.session.exec(
            select(GroupContent).where(
                GroupContent.group_id == group_id,
                GroupContent.global_content_id == global_content_id,
            )
        ).first()
        if row:
            self.session.delete(row)
            self.session.commit()


class IngestTargetRepo:
    def __init__(self, session: Session):
        self.session = session

    @staticmethod
    def target_key_for_source(source: Source) -> str:
        return _normalize_target_key(source.identifier)

    def get(self, target_id: int) -> Optional[IngestTarget]:
        return self.session.get(IngestTarget, target_id)

    def find(self, platform: str, kind: str, target_key: str) -> Optional[IngestTarget]:
        return self.session.exec(
            select(IngestTarget).where(
                IngestTarget.platform == platform,
                IngestTarget.kind == kind,
                IngestTarget.target_key == _normalize_target_key(target_key),
            )
        ).first()

    def ensure_for_source(self, source: Source) -> IngestTarget:
        target_key = self.target_key_for_source(source)
        target = self.find(source.platform, source.type, target_key)
        if not target:
            target = IngestTarget(
                platform=source.platform,
                kind=source.type,
                target_key=target_key,
                enabled=True,
            )
        target.enabled = True
        self.session.add(target)
        self.session.commit()
        self.session.refresh(target)
        return self.recompute_params(target.id)

    def sources_for_target(self, target_id: int, *, enabled_only: bool = True) -> list[Source]:
        target = self.get(target_id)
        if not target:
            return []
        stmt = select(Source).where(
            Source.platform == target.platform,
            Source.type == target.kind,
            func.trim(Source.identifier) == target.target_key,
        )
        if enabled_only:
            stmt = stmt.where(Source.enabled == True)  # noqa: E712
        return list(self.session.exec(stmt.order_by(Source.id)).all())

    def target_ids_for_group(self, group_id: int, *, enabled_only: bool = True) -> list[int]:
        stmt = select(Source).where(Source.group_id == group_id)
        if enabled_only:
            stmt = stmt.where(Source.enabled == True)  # noqa: E712
        sources = self.session.exec(stmt).all()
        ids: list[int] = []
        for source in sources:
            target = self.ensure_for_source(source)
            if target.id is not None and target.id not in ids:
                ids.append(target.id)
        return ids

    def recompute_params(self, target_id: int) -> IngestTarget:
        target = self.session.get(IngestTarget, target_id)
        if not target:
            raise ValueError(f"ingest target {target_id} not found")
        if target.admin_paused:
            target.enabled = False
            target.updated_at = _now()
            self.session.add(target)
            self.session.commit()
            self.session.refresh(target)
            return target
        sources = self.sources_for_target(target_id, enabled_only=True)
        if not sources:
            target.enabled = False
        else:
            target.enabled = True
            intervals = [s.interval_hours for s in sources if s.interval_hours is not None]
            days = [s.days for s in sources if s.days is not None]
            limits = [s.content_limit for s in sources if s.content_limit is not None]
            comments = [s.comment_top_n for s in sources if s.comment_top_n is not None]
            if intervals:
                target.interval_hours = min(int(v) for v in intervals)
            if days:
                target.days = max(int(v) for v in days)
            if limits:
                target.content_limit = max(int(v) for v in limits)
            if comments:
                target.comment_top_n = max(int(v) for v in comments)
        target.updated_at = _now()
        self.session.add(target)
        self.session.commit()
        self.session.refresh(target)
        return target

    def due_targets(self, *, limit: int = 50, stale_after_minutes: int = 120) -> list[IngestTarget]:
        """扫描 due 的采集目标。

        跳过所有订阅者都已过期的 target（订阅过期停采决策，ARCHITECTURE.md 4.2）：
        只要至少一个订阅者的 owner 未过期，target 仍可采；
        全部过期则跳过，不为过期用户白烧成本。
        """
        from app.db.schema import KnowledgeGroup, User

        now = datetime.now()
        stale_before = (now - timedelta(minutes=stale_after_minutes)).isoformat()
        targets = self.session.exec(
            select(IngestTarget)
            .where(IngestTarget.enabled == True)  # noqa: E712
            .order_by(IngestTarget.last_check.is_not(None), IngestTarget.last_check)
            .limit(limit * 3)
        ).all()
        out: list[IngestTarget] = []
        for target in targets:
            if target.running_task_id and target.locked_at and target.locked_at > stale_before:
                continue
            # 订阅过期检查：该 target 的所有订阅者是否全部过期
            sources = self.sources_for_target(target.id, enabled_only=True)
            if sources and not self._has_active_subscriber(sources, self.session):
                continue
            if not target.last_check:
                out.append(target)
            else:
                try:
                    last = datetime.fromisoformat(target.last_check)
                except ValueError:
                    out.append(target)
                    continue
                if (now - last).total_seconds() >= int(target.interval_hours or 48) * 3600:
                    out.append(target)
            if len(out) >= limit:
                break
        return out

    @staticmethod
    def _has_active_subscriber(sources: list[Source], session: Session) -> bool:
        """检查是否至少有一个订阅者的 owner 未过期（plan=pro 且 expires_at 未过）。"""
        now_iso = datetime.now().isoformat()
        seen_groups: set[int] = set()
        for src in sources:
            if src.group_id in seen_groups:
                continue
            seen_groups.add(src.group_id)
            # 查 group → owner → user
            from app.db.schema import KnowledgeGroup, User
            group = session.get(KnowledgeGroup, src.group_id)
            if not group or not group.owner_id:
                continue
            user = session.get(User, group.owner_id)
            if not user:
                continue
            # admin 永远算活跃（管理员不限）
            if user.role == "admin":
                return True
            # plan=pro 且未过期
            if user.plan == "pro" and user.expires_at and user.expires_at > now_iso:
                return True
        return False

    def mark_checked(self, target_id: int, *, ok: bool, error: Optional[str] = None) -> None:
        target = self.session.get(IngestTarget, target_id)
        if not target:
            return
        target.last_check = _now()
        target.last_error = None if ok else (error or "unknown")
        target.running_task_id = None
        target.locked_at = None
        target.updated_at = _now()
        self.session.add(target)
        self.session.commit()

    def claim(self, target_id: int, task_id: str) -> bool:
        target = self.session.get(IngestTarget, target_id)
        if not target or not target.enabled:
            return False
        target.running_task_id = task_id
        target.locked_at = _now()
        target.updated_at = _now()
        self.session.add(target)
        self.session.commit()
        return True

    def clear_lock_and_error(self, target_id: int) -> Optional[IngestTarget]:
        target = self.session.get(IngestTarget, target_id)
        if not target:
            return None
        target.last_error = None
        target.running_task_id = None
        target.locked_at = None
        target.updated_at = _now()
        self.session.add(target)
        self.session.commit()
        self.session.refresh(target)
        return target

    def set_admin_paused(self, target_id: int, paused: bool) -> Optional[IngestTarget]:
        target = self.session.get(IngestTarget, target_id)
        if not target:
            return None
        target.admin_paused = paused
        target.updated_at = _now()
        self.session.add(target)
        self.session.commit()
        self.session.refresh(target)
        if paused:
            target.enabled = False
            target.updated_at = _now()
            self.session.add(target)
            self.session.commit()
            self.session.refresh(target)
            return target
        return self.recompute_params(target_id)
