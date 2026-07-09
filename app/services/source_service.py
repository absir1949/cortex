"""订阅源 CRUD"""
from __future__ import annotations
from typing import Optional
from sqlmodel import select

from app.db.engine import get_session
from app.db.repos import (
    GroupContentRepo,
    GroupRepo,
    IngestTargetRepo,
    SourceContentRepo,
    SourceRepo,
    CreatorRepo,
)
from app.db.schema import GlobalContent, Source, SourceContent
from app.platforms import get_adapter
from app.platforms.base import Capability
from app.models.group import SourceType
from app.storage.paths import slugify


class SourceService:

    def list_by_group(self, group_id: int, enabled_only: bool = False) -> list[Source]:
        with get_session() as s:
            return SourceRepo(s).list_by_group(group_id, enabled_only=enabled_only)

    def get(self, source_id: int) -> Optional[Source]:
        with get_session() as s:
            return SourceRepo(s).get(source_id)

    def create(
        self,
        group_id: int,
        *,
        type: SourceType | str,
        platform: str,
        identifier: str,
        display_name: str = "",
        interval_hours: Optional[int] = None,
        days: Optional[int] = None,
        content_limit: Optional[int] = None,
        comment_top_n: Optional[int] = None,
        directory: Optional[str] = None,
        resolve_creator: bool = False,
    ) -> Source:
        type_value = type.value if isinstance(type, SourceType) else type
        resolved_identifier = identifier.strip()
        resolved_name = display_name.strip()
        # 解析用户输入 → 平台唯一 ID（每个平台有自己的解析逻辑）
        if resolve_creator and type_value == SourceType.CREATOR.value:
            adapter = get_adapter(platform)
            if adapter and adapter.has(Capability.RESOLVE_IDENTIFIER):
                resolved_identifier, resolved_name = adapter.resolve_identifier(
                    resolved_identifier, resolved_name,
                )
        with get_session() as s:
            group = GroupRepo(s).get(group_id)
            if not group:
                raise ValueError(f"group {group_id} not found")
            # 重复检查
            existing = SourceRepo(s).find(group_id, platform, resolved_identifier)
            if existing:
                raise ValueError(f"source 已存在: {platform}/{identifier}")

            # 目录命名
            if not directory:
                name_part = slugify(resolved_name or resolved_identifier[:8])
                directory = f"{group.id}/{type_value}-{name_part}"

            # creator 类型：先建/关联全局博主身份，再带 creator_id 建 source（原子化）
            creator_id = None
            if type_value == SourceType.CREATOR.value:
                creator = CreatorRepo(s).get_or_create(
                    platform=platform,
                    platform_uid=resolved_identifier,
                    display_name=resolved_name or resolved_identifier,
                )
                creator_id = creator.id

            src = Source(
                group_id=group_id,
                creator_id=creator_id,
                type=type_value,
                platform=platform,
                identifier=resolved_identifier,
                display_name=resolved_name or resolved_identifier,
                enabled=True,
                interval_hours=interval_hours,
                days=days,
                content_limit=content_limit,
                comment_top_n=comment_top_n,
                directory=directory,
            )
            created = SourceRepo(s).create(src)

        self._reconcile_source_created(created.id)
        with get_session() as s:
            refreshed = SourceRepo(s).get(created.id)
            if not refreshed:
                raise ValueError("source 创建后读取失败")
            return refreshed

    def update(self, source_id: int, **fields) -> Optional[Source]:
        with get_session() as s:
            repo = SourceRepo(s)
            src = repo.get(source_id)
            if not src:
                return None
            for k, v in fields.items():
                if hasattr(src, k) and v is not None:
                    setattr(src, k, v)
            updated = repo.update(src)
        self._reconcile_source_updated(source_id)
        return updated

    def delete(self, source_id: int) -> None:
        self._reconcile_source_deleted(source_id)

    # ============ shared-ingest lifecycle ============

    def _reconcile_source_created(self, source_id: int) -> None:
        """新订阅：确保 target，并从已有全局内容回填 SourceContent/GroupContent。"""
        with get_session() as s:
            source = SourceRepo(s).get(source_id)
            if not source:
                return
            target = IngestTargetRepo(s).ensure_for_source(source)
            global_items = self._history_for_source(s, source, target.id)
            source_content_repo = SourceContentRepo(s)
            group_content_repo = GroupContentRepo(s)
            for item in global_items:
                source_content_repo.upsert(
                    source_id=source.id,
                    global_content_id=item.id,
                    ingest_target_id=target.id,
                    matched_query=source.identifier if source.type == SourceType.KEYWORD.value else "",
                )
                group_content_repo.upsert(group_id=source.group_id, global_content_id=item.id)
            IngestTargetRepo(s).recompute_params(target.id)

    def _reconcile_source_updated(self, source_id: int) -> None:
        with get_session() as s:
            source = SourceRepo(s).get(source_id)
            if not source:
                return
            target = IngestTargetRepo(s).ensure_for_source(source)
            IngestTargetRepo(s).recompute_params(target.id)

    def _reconcile_source_deleted(self, source_id: int) -> None:
        with get_session() as s:
            source = SourceRepo(s).get(source_id)
            if not source:
                return
            target = IngestTargetRepo(s).ensure_for_source(source)
            global_ids = SourceContentRepo(s).list_global_ids_for_source(source_id, limit=10000)
            SourceRepo(s).delete(source_id)
            group_content_repo = GroupContentRepo(s)
            for global_id in global_ids:
                group_content_repo.delete_if_unlinked(group_id=source.group_id, global_content_id=global_id)
            IngestTargetRepo(s).recompute_params(target.id)

    @staticmethod
    def _history_for_source(session, source: Source, target_id: int | None) -> list[GlobalContent]:
        if source.type == SourceType.CREATOR.value and source.creator_id:
            return list(session.exec(
                select(GlobalContent).where(
                    GlobalContent.platform == source.platform,
                    GlobalContent.creator_id == source.creator_id,
                ).order_by(GlobalContent.create_time.desc())
            ).all())
        if source.type == SourceType.KEYWORD.value and target_id:
            ids = session.exec(
                select(GlobalContent.id)
                .join(SourceContent, SourceContent.global_content_id == GlobalContent.id)
                .where(SourceContent.ingest_target_id == target_id)
                .order_by(GlobalContent.create_time.desc())
            ).all()
            if not ids:
                return []
            return list(session.exec(
                select(GlobalContent).where(GlobalContent.id.in_([int(i) for i in ids]))
            ).all())
        return []
