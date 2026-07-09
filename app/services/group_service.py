"""知识组 CRUD"""
from __future__ import annotations
from typing import Optional
from app.db.engine import get_session
from app.db.repos import GroupRepo
from app.db.schema import KnowledgeGroup
from app.storage.paths import slugify


class GroupService:

    def list(self, owner_id: Optional[int] = None) -> list[KnowledgeGroup]:
        with get_session() as s:
            repo = GroupRepo(s)
            return repo.list_by_owner(owner_id) if owner_id is not None else repo.list_all()

    def get(self, group_id: int) -> Optional[KnowledgeGroup]:
        with get_session() as s:
            return GroupRepo(s).get(group_id)

    def get_by_slug(self, slug: str, owner_id: Optional[int] = None) -> Optional[KnowledgeGroup]:
        with get_session() as s:
            return GroupRepo(s).get_by_slug(slug, owner_id=owner_id)

    def create(
        self,
        name: str,
        *,
        slug: Optional[str] = None,
        description: str = "",
        defaults: Optional[dict] = None,
        prompt_overrides: Optional[dict] = None,
        owner_id: Optional[int] = None,
    ) -> KnowledgeGroup:
        with get_session() as s:
            repo = GroupRepo(s)
            final_slug = slug or slugify(name)
            existing = repo.get_by_slug(final_slug, owner_id=owner_id)
            if existing:
                raise ValueError(f"知识组 slug '{final_slug}' 已存在")
            g = KnowledgeGroup(
                owner_id=owner_id,
                name=name,
                slug=final_slug,
                description=description,
                defaults=defaults or {},
                prompt_overrides=prompt_overrides or {},
            )
            return repo.create(g)

    def update(
        self,
        group_id: int,
        *,
        name: Optional[str] = None,
        description: Optional[str] = None,
        enabled: Optional[bool] = None,
        defaults: Optional[dict] = None,
        prompt_overrides: Optional[dict] = None,
    ) -> Optional[KnowledgeGroup]:
        with get_session() as s:
            repo = GroupRepo(s)
            g = repo.get(group_id)
            if not g:
                return None
            if name is not None:
                g.name = name
            if description is not None:
                g.description = description
            if enabled is not None:
                g.enabled = enabled
            if defaults is not None:
                g.defaults = defaults
            if prompt_overrides is not None:
                g.prompt_overrides = prompt_overrides
            return repo.update(g)

    def delete(self, group_id: int, cascade: bool = False) -> None:
        with get_session() as s:
            GroupRepo(s).delete(group_id, cascade=cascade)
