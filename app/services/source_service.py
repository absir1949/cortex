"""订阅源 CRUD"""
from __future__ import annotations
from typing import Optional
from app.db.engine import get_session
from app.db.repos import GroupRepo, SourceRepo, CreatorRepo
from app.db.schema import Source, KnowledgeGroup
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
            return SourceRepo(s).create(src)

    def update(self, source_id: int, **fields) -> Optional[Source]:
        with get_session() as s:
            repo = SourceRepo(s)
            src = repo.get(source_id)
            if not src:
                return None
            for k, v in fields.items():
                if hasattr(src, k) and v is not None:
                    setattr(src, k, v)
            return repo.update(src)

    def delete(self, source_id: int) -> None:
        with get_session() as s:
            SourceRepo(s).delete(source_id)
