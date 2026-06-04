"""订阅源 CRUD"""
from __future__ import annotations
from typing import Optional
from app.db.engine import get_session
from app.db.repos import GroupRepo, SourceRepo
from app.db.schema import Source, KnowledgeGroup
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
        if resolve_creator and type_value == SourceType.CREATOR.value and platform == "douyin":
            resolved_identifier, resolved_name = self._resolve_douyin_creator(
                resolved_identifier,
                resolved_name,
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
                directory = f"{group.slug}/{type_value}-{name_part}"

            src = Source(
                group_id=group_id,
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

    @staticmethod
    def _resolve_douyin_creator(identifier: str, display_name: str = "") -> tuple[str, str]:
        """Resolve a human-facing Douyin handle/name into sec_uid when possible."""
        if identifier.startswith("MS4w"):
            return identifier, display_name or identifier

        from app.platforms import get_adapter

        adapter = get_adapter("douyin")
        if not adapter:
            return identifier, display_name or identifier

        clean_identifier = identifier.strip().rstrip("/")
        if "/" in clean_identifier:
            clean_identifier = clean_identifier.split("/")[-1] or clean_identifier

        queries: list[str] = []
        if display_name:
            queries.append(f"{display_name} {clean_identifier}".strip())
            queries.append(display_name)
        queries.append(clean_identifier)

        seen: set[str] = set()
        best = None
        for q in queries:
            if not q or q in seen:
                continue
            seen.add(q)
            try:
                results = adapter.search(q, limit=10, days=180)
            except Exception:
                continue
            for item in results:
                if not item.author_id:
                    continue
                if display_name and item.author_name == display_name:
                    return item.author_id, item.author_name
                if display_name and display_name.replace(" ", "") in item.author_name.replace(" ", ""):
                    return item.author_id, item.author_name
                if best is None:
                    best = item
        if best and best.author_id:
            return best.author_id, best.author_name or display_name or identifier
        raise ValueError(f"无法解析抖音作者: {identifier}")

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
