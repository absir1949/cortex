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


# ============ Migration 005: 刷新状态机 ============

@register(5, "005_refresh_state: 内容处理状态 + 刷新运行记录")
def _mig_005_refresh_state(session: Session) -> None:
    # create_all 幂等：只创建 refresh_runs / content_items 等新增表。
    SQLModel.metadata.create_all(get_engine())


# ============ Migration 006: 问听风对话 ============

@register(6, "006_ask_conversations: 问听风对话与消息")
def _mig_006_ask_conversations(session: Session) -> None:
    SQLModel.metadata.create_all(get_engine())


# ============ Migration 007: 用户 + 多租户 + 共享采集表骨架 ============
# 这是上线前最大的 schema 变更：
#   1. users 表（认证）
#   2. knowledge_groups 加 owner_id + slug 改联合唯一（SQLite 需重建表）
#   3. global_content / source_content / group_content / ingest_targets（共享采集表骨架）
#
# 注意：SQLite 不支持直接 DROP CONSTRAINT / 改 UNIQUE。
# slug 从 unique=True → (owner_id, slug) 联合唯一，需重建 knowledge_groups 表。

@register(7, "007_go_live: 用户表 + 多租户 owner_id + 共享采集表骨架")
def _mig_007_go_live(session: Session) -> None:
    from sqlalchemy import text, inspect
    engine = get_engine()

    # --- 1. 建新表（create_all 幂等，已存在的跳过）---
    SQLModel.metadata.create_all(engine)
    admin_id = _ensure_admin_user(session)

    # --- 2. knowledge_groups: 加 owner_id 列 ---
    inspector = inspect(engine)
    kg_cols = {c["name"] for c in inspector.get_columns("knowledge_groups")}
    if "owner_id" not in kg_cols:
        with engine.connect() as conn:
            conn.execute(text(
                "ALTER TABLE knowledge_groups ADD COLUMN owner_id INTEGER REFERENCES users(id)"
            ))
            conn.commit()

    # 先回填 owner_id，再改唯一约束，避免 nullable owner_id 让 slug 唯一性失真。
    session.execute(text(
        "UPDATE knowledge_groups SET owner_id = :admin_id WHERE owner_id IS NULL"
    ), {"admin_id": admin_id})
    session.commit()

    # --- 3. knowledge_groups: slug 唯一约束从 global → (owner_id, slug) ---
    # SQLite 自动 UNIQUE 索引不能 DROP INDEX；旧库若是 UNIQUE(slug)，只能重建表。
    if _has_unique_index(engine, "knowledge_groups", ("slug",)):
        _rebuild_knowledge_groups_drop_slug_unique(engine)

    # 如果联合唯一索引不存在（全新表或刚重建），创建它。
    if not _has_unique_index(engine, "knowledge_groups", ("owner_id", "slug")):
        with engine.connect() as conn:
            conn.execute(text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_group_owner_slug "
                "ON knowledge_groups (owner_id, slug)"
            ))
            conn.commit()

    # --- 4. 再次回填 owner_id（幂等，防止重建前后连接状态差异） ---
    session.execute(text(
        "UPDATE knowledge_groups SET owner_id = :admin_id WHERE owner_id IS NULL"
    ), {"admin_id": admin_id})
    session.commit()


def _ensure_admin_user(session: Session) -> int:
    from sqlalchemy import text
    from app.settings import settings

    admin_phone = getattr(settings, "admin_phone", None) or "00000000000"
    existing_admin = session.execute(
        text("SELECT id FROM users WHERE role = 'admin' LIMIT 1")
    ).first()
    if existing_admin:
        return int(existing_admin[0])

    existing_phone = session.execute(
        text("SELECT id FROM users WHERE phone = :phone LIMIT 1"),
        {"phone": admin_phone},
    ).first()
    if existing_phone:
        session.execute(text(
            "UPDATE users SET role = 'admin', plan = 'pro' WHERE id = :id"
        ), {"id": existing_phone[0]})
        session.commit()
        return int(existing_phone[0])

    session.execute(text(
        "INSERT INTO users (phone, nickname, role, plan, created_at) "
        "VALUES (:phone, '管理员', 'admin', 'pro', :ts)"
    ), {"phone": admin_phone, "ts": datetime.now().isoformat()})
    session.commit()
    row = session.execute(
        text("SELECT id FROM users WHERE phone = :phone LIMIT 1"),
        {"phone": admin_phone},
    ).first()
    return int(row[0])


def _has_unique_index(engine, table_name: str, expected_columns: tuple[str, ...]) -> bool:
    with engine.connect() as conn:
        indexes = conn.exec_driver_sql(f"PRAGMA index_list('{table_name}')").fetchall()
        for idx in indexes:
            # PRAGMA index_list: seq, name, unique, origin, partial
            if not bool(idx[2]):
                continue
            name = str(idx[1])
            safe_name = name.replace("'", "''")
            cols = conn.exec_driver_sql(f"PRAGMA index_info('{safe_name}')").fetchall()
            col_names = tuple(str(col[2]) for col in cols)
            if col_names == expected_columns:
                return True
    return False


def _rebuild_knowledge_groups_drop_slug_unique(engine) -> None:
    """重建 knowledge_groups 表，去掉 slug 的全局 UNIQUE，保留数据。

    SQLite 重建表的标准流程：
      1. 用新 schema 建临时表 _kg_new
      2. INSERT INTO _kg_new SELECT * FROM knowledge_groups
      3. DROP TABLE knowledge_groups
      4. ALTER TABLE _kg_new RENAME TO knowledge_groups
      5. 重建索引
    """
    with engine.connect() as conn:
        conn.commit()
        conn.exec_driver_sql("PRAGMA foreign_keys=OFF")
        try:
            # 新表结构：去掉 slug 的 unique=True（index 保留）
            conn.exec_driver_sql("DROP TABLE IF EXISTS _kg_new")
            conn.exec_driver_sql("""
            CREATE TABLE _kg_new (
                id INTEGER PRIMARY KEY,
                owner_id INTEGER REFERENCES users(id),
                name VARCHAR,
                slug VARCHAR,
                description VARCHAR DEFAULT '',
                enabled BOOLEAN DEFAULT 1,
                defaults JSON,
                prompt_overrides JSON,
                created_at VARCHAR,
                updated_at VARCHAR
            )
        """)
            # 迁移数据
            conn.exec_driver_sql("""
            INSERT INTO _kg_new (id, owner_id, name, slug, description, enabled, defaults, prompt_overrides, created_at, updated_at)
            SELECT id, owner_id, name, slug, description, enabled, defaults, prompt_overrides, created_at, updated_at
            FROM knowledge_groups
        """)
            conn.exec_driver_sql("DROP TABLE knowledge_groups")
            conn.exec_driver_sql("ALTER TABLE _kg_new RENAME TO knowledge_groups")
            # 重建索引
            conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_knowledge_groups_name ON knowledge_groups (name)")
            conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_knowledge_groups_slug ON knowledge_groups (slug)")
            conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_knowledge_groups_owner_id ON knowledge_groups (owner_id)")
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.exec_driver_sql("PRAGMA foreign_keys=ON")
            violations = conn.exec_driver_sql("PRAGMA foreign_key_check").fetchall()
            if violations:
                raise RuntimeError(f"foreign key check failed after knowledge_groups rebuild: {violations[:5]}")


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
