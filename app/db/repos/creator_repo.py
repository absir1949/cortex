from __future__ import annotations
from typing import Optional
from sqlmodel import Session, select

from app.db.schema import Creator, CreatorAlias, Source
from app.storage.paths import slugify


class CreatorRepo:
    """博主（跨平台聚合身份）的持久化操作"""

    def __init__(self, session: Session):
        self.session = session

    def get(self, creator_id: int) -> Optional[Creator]:
        return self.session.get(Creator, creator_id)

    def get_by_slug(self, slug: str) -> Optional[Creator]:
        return self.session.exec(select(Creator).where(Creator.slug == slug)).first()

    def list_all(self) -> list[Creator]:
        return list(self.session.exec(select(Creator).order_by(Creator.name)).all())

    def find_by_platform_uid(self, platform: str, platform_uid: str) -> Optional[Creator]:
        """按平台账号查 creator（用于 source 创建时关联）"""
        row = self.session.exec(
            select(CreatorAlias.creator_id).where(
                CreatorAlias.platform == platform,
                CreatorAlias.platform_uid == platform_uid,
            )
        ).first()
        if row is None:
            return None
        return self.get(row)

    def get_or_create(
        self,
        platform: str,
        platform_uid: str,
        display_name: str = "",
    ) -> Creator:
        """按平台账号找 creator，没有就新建 creator + alias。

        同一博主即使被多个组关注，也只创建一次 creator。
        """
        existing = self.find_by_platform_uid(platform, platform_uid)
        if existing:
            # 已存在：若 display_name 变了，更新 alias 的 display_name
            alias = self.session.exec(
                select(CreatorAlias).where(
                    CreatorAlias.platform == platform,
                    CreatorAlias.platform_uid == platform_uid,
                )
            ).first()
            if alias and display_name and alias.display_name != display_name:
                alias.display_name = display_name
                self.session.add(alias)
                self.session.commit()
            return existing

        # 新建：slug 用 display_name，重复时加后缀
        name = display_name or f"creator-{platform_uid[:8]}"
        base_slug = slugify(name)
        slug = base_slug
        i = 2
        while self.session.exec(select(Creator).where(Creator.slug == slug)).first():
            slug = f"{base_slug}-{i}"
            i += 1
        creator = Creator(name=name, slug=slug)
        self.session.add(creator)
        self.session.flush()
        self.session.add(CreatorAlias(
            creator_id=creator.id,
            platform=platform,
            platform_uid=platform_uid,
            display_name=display_name,
        ))
        self.session.commit()
        self.session.refresh(creator)
        return creator

    def aliases_for(self, creator_id: int) -> list[CreatorAlias]:
        """某博主的所有平台账号"""
        return list(self.session.exec(
            select(CreatorAlias).where(CreatorAlias.creator_id == creator_id)
        ).all())

    def sources_for(self, creator_id: int) -> list[Source]:
        """某博主被哪些组关注（所有关联的 source）"""
        return list(self.session.exec(
            select(Source).where(Source.creator_id == creator_id)
        ).all())
