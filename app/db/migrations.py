"""版本号驱动的数据库迁移

每个迁移是一个函数，版本号从 1 开始连续。
幂等：已应用的版本会被 SchemaVersion 表记录，不重复执行。
"""
from __future__ import annotations
from datetime import datetime
from typing import Callable
from sqlmodel import Session, select, SQLModel

from app.db.engine import get_engine
from app.db import schema as _schema  # noqa: F401 注册模型


# (版本号, 描述, 执行函数)
_migrations: list[tuple[int, str, Callable[[Session], None]]] = []


def register(version: int, note: str):
    def decorator(fn):
        _migrations.append((version, note, fn))
        return fn
    return decorator


# ============ Migration 001: 初始化全部表 ============

@register(1, "001_init: 创建全部基础表")
def _mig_001_init(session: Session) -> None:
    SQLModel.metadata.create_all(get_engine())


# ============ Migration 003: 新增 signals 表 ============
# （version 2 被根目录 migrations/002_*.py 一次性数据迁移占用，这里从 3 起）
# create_all 幂等：已存在的表跳过，只建新增的 signals 表

@register(3, "003_signals: 新增观点信号表（观点去重判定结果）")
def _mig_003_signals(session: Session) -> None:
    SQLModel.metadata.create_all(get_engine())


# ============ Migration 004: 博主实体（跨平台聚合） ============
# 新增 creators / creator_aliases 表，给 sources 加 creator_id 列。
# 迁移会把老 source（creator 类型）关联到新建的 creator + alias，
# 并把观点档案从 profiles/{source_id}.md 迁移到 profiles/{creator_id}.md。

@register(4, "004_creators: 博主实体 + 平台别名映射 + source.creator_id")
def _mig_004_creators(session: Session) -> None:
    from sqlalchemy import text, inspect
    engine = get_engine()

    # 1. 建新表（create_all 幂等，已存在的跳过）
    SQLModel.metadata.create_all(engine)

    # 2. 给 sources 加 creator_id 列（SQLite ADD COLUMN，IF NOT EXISTS 不支持，先检查）
    inspector = inspect(engine)
    source_cols = {c["name"] for c in inspector.get_columns("sources")}
    if "creator_id" not in source_cols:
        with engine.connect() as conn:
            conn.execute(text("ALTER TABLE sources ADD COLUMN creator_id INTEGER REFERENCES creators(id)"))
            conn.commit()

    # 3. 回填：为每个 creator 类型的老 source 创建 creator + alias
    from app.db.schema import Creator, CreatorAlias, Source
    from app.storage.paths import slugify
    rows = session.execute(text(
        "SELECT id, platform, identifier, display_name FROM sources WHERE type = 'creator' AND creator_id IS NULL"
    )).all()
    used_slugs: set[str] = set()
    for sid, platform, identifier, display_name in rows:
        sid = sid  # 标量解包
        # 先查 alias 是否已存在（同一博主被多个组关注的情况）
        existing = session.execute(
            text("SELECT creator_id FROM creator_aliases WHERE platform = :p AND platform_uid = :u"),
            {"p": platform, "u": identifier},
        ).first()
        if existing:
            creator_id = existing[0]
        else:
            # 新建 creator
            base_slug = slugify(display_name or f"creator-{identifier[:8]}")
            slug = base_slug
            i = 2
            while slug in used_slugs or session.execute(
                text("SELECT 1 FROM creators WHERE slug = :s"), {"s": slug}
            ).first():
                slug = f"{base_slug}-{i}"
                i += 1
            used_slugs.add(slug)
            creator = Creator(name=display_name or identifier, slug=slug)
            session.add(creator)
            session.flush()
            creator_id = creator.id
            session.add(CreatorAlias(
                creator_id=creator_id,
                platform=platform,
                platform_uid=identifier,
                display_name=display_name,
            ))
        # 关联 source
        session.execute(text("UPDATE sources SET creator_id = :c WHERE id = :s"), {"c": creator_id, "s": sid})
    session.commit()

    # 4. 迁移观点档案：旧的 group 级路径 → 全局 creator 级路径
    #    knowledge/{group_slug}/profiles/{source_id}.md → knowledge/profiles/{creator_id}.md
    from app.settings import settings
    global_profiles_dir = settings.knowledge_dir / "profiles"
    global_profiles_dir.mkdir(parents=True, exist_ok=True)
    for sid, cid in session.execute(text("SELECT id, creator_id FROM sources WHERE creator_id IS NOT NULL")).all():
        if not cid:
            continue
        grp_slug_row = session.execute(
            text("SELECT kg.slug FROM sources s JOIN knowledge_groups kg ON s.group_id = kg.id WHERE s.id = :sid"),
            {"sid": sid},
        ).first()
        if not grp_slug_row:
            continue
        grp_slug = grp_slug_row[0]
        old_path = settings.knowledge_dir / grp_slug / "profiles" / f"{sid}.md"
        new_path = global_profiles_dir / f"{cid}.md"
        if old_path.exists() and not new_path.exists():
            old_path.rename(new_path)


# ============ 通用运行器 ============

def current_version(session: Session) -> int:
    rows = session.exec(select(_schema.SchemaVersion).order_by(_schema.SchemaVersion.version.desc())).all()
    return rows[0].version if rows else 0


def run_migrations(verbose: bool = True) -> list[int]:
    """按版本号顺序执行未应用的 migration，返回本次应用的版本列表"""
    from app.db.engine import get_engine
    # 第一次运行时 schema_version 表还不存在，先 create_all 一次
    SQLModel.metadata.create_all(get_engine())

    applied: list[int] = []
    with Session(get_engine()) as session:
        cur = current_version(session)
        for version, note, fn in sorted(_migrations, key=lambda x: x[0]):
            if version <= cur:
                continue
            if verbose:
                print(f"[migrate] applying v{version}: {note}")
            fn(session)
            session.add(_schema.SchemaVersion(
                version=version,
                applied_at=datetime.now().isoformat(),
                note=note,
            ))
            session.commit()
            applied.append(version)
    return applied


if __name__ == "__main__":
    applied = run_migrations()
    if applied:
        print(f"[migrate] applied: {applied}")
    else:
        print("[migrate] already up to date")
