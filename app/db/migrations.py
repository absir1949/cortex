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


# ============ Migration 008: 共享采集 runtime 回填 ============

@register(8, "008_shared_ingest_runtime: 回填全局内容、水位、采集目标和全局信号键")
def _mig_008_shared_ingest_runtime(session: Session) -> None:
    from sqlalchemy import text, inspect

    engine = get_engine()
    SQLModel.metadata.create_all(engine)
    inspector = inspect(engine)

    signal_cols = {c["name"] for c in inspector.get_columns("signals")}
    if "global_content_id" not in signal_cols:
        with engine.connect() as conn:
            conn.execute(text("ALTER TABLE signals ADD COLUMN global_content_id INTEGER REFERENCES global_content(id)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_signals_global_content_id ON signals (global_content_id)"))
            conn.commit()

    # 某些真实/测试旧库的 sources 表可能停在更早版本，create_all 不会给既有表补列。
    source_cols = {c["name"] for c in inspector.get_columns("sources")}
    source_add_columns = {
        "creator_id": "INTEGER REFERENCES creators(id)",
        "type": "VARCHAR DEFAULT ''",
        "platform": "VARCHAR DEFAULT ''",
        "identifier": "VARCHAR DEFAULT ''",
        "display_name": "VARCHAR DEFAULT ''",
        "enabled": "BOOLEAN DEFAULT 1",
        "interval_hours": "INTEGER",
        "days": "INTEGER",
        "content_limit": "INTEGER",
        "comment_top_n": "INTEGER",
        "directory": "VARCHAR DEFAULT ''",
        "last_check": "VARCHAR",
        "last_error": "VARCHAR",
        "created_at": "VARCHAR",
    }
    missing_source_cols = {k: v for k, v in source_add_columns.items() if k not in source_cols}
    if missing_source_cols:
        with engine.connect() as conn:
            for col, ddl in missing_source_cols.items():
                conn.execute(text(f"ALTER TABLE sources ADD COLUMN {col} {ddl}"))
            conn.commit()
        inspector = inspect(engine)

    # 1. ContentItem -> GlobalContent，按 (platform, content_id) 去重。
    rows = session.execute(text("""
        SELECT
            ci.platform,
            ci.content_id,
            MAX(COALESCE(ci.creator_id, s.creator_id)) AS creator_id,
            MAX(ci.content_type) AS content_type,
            MAX(ci.title) AS title,
            MAX(ci.author_id) AS author_id,
            MAX(ci.author_name) AS author_name,
            MAX(ci.url) AS url,
            MAX(ci.create_time) AS create_time,
            MIN(ci.first_seen_at) AS first_seen_at,
            MAX(ci.last_seen_at) AS last_seen_at,
            MAX(ci.updated_at) AS updated_at,
            MAX(ci.media_status) AS media_status,
            MAX(ci.transcript_status) AS transcript_status,
            MAX(ci.comments_status) AS comments_status,
            MAX(ci.signal_status) AS signal_status,
            MAX(ci.profile_status) AS profile_status,
            MAX(ci.media_error) AS media_error,
            MAX(ci.transcript_error) AS transcript_error,
            MAX(ci.comments_error) AS comments_error,
            MAX(ci.signal_error) AS signal_error,
            MAX(ci.profile_error) AS profile_error,
            MAX(ci.file_size) AS file_size,
            MAX(ci.statistics) AS statistics
        FROM content_items ci
        LEFT JOIN sources s ON s.id = ci.source_id
        WHERE ci.platform IS NOT NULL AND ci.platform != '' AND ci.content_id IS NOT NULL AND ci.content_id != ''
        GROUP BY ci.platform, ci.content_id
    """)).mappings().all()
    for row in rows:
        existing = session.execute(text("""
            SELECT id FROM global_content WHERE platform = :platform AND content_id = :content_id
        """), row).first()
        payload = dict(row)
        payload["now"] = datetime.now().isoformat()
        if existing:
            payload["id"] = existing[0]
            session.execute(text("""
                UPDATE global_content
                SET creator_id = COALESCE(:creator_id, creator_id),
                    content_type = COALESCE(NULLIF(:content_type, ''), content_type),
                    title = COALESCE(NULLIF(:title, ''), title),
                    author_id = COALESCE(NULLIF(:author_id, ''), author_id),
                    author_name = COALESCE(NULLIF(:author_name, ''), author_name),
                    url = COALESCE(NULLIF(:url, ''), url),
                    create_time = COALESCE(NULLIF(:create_time, ''), create_time),
                    last_seen_at = COALESCE(:last_seen_at, last_seen_at),
                    updated_at = :now,
                    media_status = COALESCE(NULLIF(:media_status, ''), media_status),
                    transcript_status = COALESCE(NULLIF(:transcript_status, ''), transcript_status),
                    comments_status = COALESCE(NULLIF(:comments_status, ''), comments_status),
                    signal_status = COALESCE(NULLIF(:signal_status, ''), signal_status),
                    profile_status = COALESCE(NULLIF(:profile_status, ''), profile_status),
                    media_error = :media_error,
                    transcript_error = :transcript_error,
                    comments_error = :comments_error,
                    signal_error = :signal_error,
                    profile_error = :profile_error,
                    file_size = COALESCE(:file_size, file_size),
                    statistics = COALESCE(:statistics, statistics)
                WHERE id = :id
            """), payload)
        else:
            session.execute(text("""
                INSERT INTO global_content (
                    platform, content_id, creator_id, content_type, title, author_id, author_name, url, create_time,
                    first_seen_at, last_seen_at, updated_at, media_status, transcript_status, comments_status,
                    signal_status, profile_status, media_error, transcript_error, comments_error, signal_error,
                    profile_error, file_size, statistics
                ) VALUES (
                    :platform, :content_id, :creator_id, COALESCE(:content_type, ''), COALESCE(:title, ''),
                    COALESCE(:author_id, ''), COALESCE(:author_name, ''), COALESCE(:url, ''),
                    COALESCE(:create_time, ''), COALESCE(:first_seen_at, :now), COALESCE(:last_seen_at, :now),
                    COALESCE(:updated_at, :now), COALESCE(:media_status, 'pending'),
                    COALESCE(:transcript_status, 'pending'), COALESCE(:comments_status, 'pending'),
                    COALESCE(:signal_status, 'pending'), COALESCE(:profile_status, 'pending'),
                    :media_error, :transcript_error, :comments_error, :signal_error, :profile_error,
                    COALESCE(:file_size, 0), COALESCE(:statistics, '{}')
                )
            """), payload)
    session.commit()

    # 2. Sources -> IngestTarget，按 target 聚合并取最激进参数。
    # 确保 admin_paused 列存在（migration 009 才正式加，这里提前补防 INSERT 失败）
    inspector = inspect(get_engine())
    target_cols = {c["name"] for c in inspector.get_columns("ingest_targets")}
    if "admin_paused" not in target_cols:
        with get_engine().connect() as conn:
            conn.execute(text("ALTER TABLE ingest_targets ADD COLUMN admin_paused BOOLEAN NOT NULL DEFAULT 0"))
            conn.commit()

    target_rows = session.execute(text("""
        SELECT
            platform,
            type AS kind,
            TRIM(identifier) AS target_key,
            MIN(COALESCE(interval_hours, 48)) AS interval_hours,
            MAX(COALESCE(days, 7)) AS days,
            MAX(COALESCE(content_limit, 50)) AS content_limit,
            MAX(COALESCE(comment_top_n, 20)) AS comment_top_n,
            MAX(last_check) AS last_check,
            MAX(last_error) AS last_error,
            MAX(CASE WHEN enabled THEN 1 ELSE 0 END) AS enabled
        FROM sources
        WHERE platform IS NOT NULL AND platform != '' AND type IS NOT NULL AND type != '' AND identifier IS NOT NULL AND identifier != ''
        GROUP BY platform, type, TRIM(identifier)
    """)).mappings().all()
    for row in target_rows:
        payload = dict(row)
        payload["now"] = datetime.now().isoformat()
        existing = session.execute(text("""
            SELECT id FROM ingest_targets WHERE platform = :platform AND kind = :kind AND target_key = :target_key
        """), payload).first()
        if existing:
            payload["id"] = existing[0]
            session.execute(text("""
                UPDATE ingest_targets
                SET enabled = :enabled,
                    interval_hours = :interval_hours,
                    days = :days,
                    content_limit = :content_limit,
                    comment_top_n = :comment_top_n,
                    last_check = COALESCE(last_check, :last_check),
                    last_error = COALESCE(last_error, :last_error),
                    updated_at = :now
                WHERE id = :id
            """), payload)
        else:
            session.execute(text("""
                INSERT INTO ingest_targets (
                    platform, kind, target_key, enabled, admin_paused, interval_hours, days, content_limit, comment_top_n,
                    last_check, last_error, created_at, updated_at
                ) VALUES (
                    :platform, :kind, :target_key, :enabled, 0, :interval_hours, :days, :content_limit, :comment_top_n,
                    :last_check, :last_error, :now, :now
                )
            """), payload)
    session.commit()

    # 3. ContentItem -> SourceContent + GroupContent，并映射已分析水位。
    link_rows = session.execute(text("""
        SELECT
            ci.source_id,
            ci.group_id,
            gc.id AS global_content_id,
            it.id AS ingest_target_id,
            s.type AS source_type,
            s.identifier AS source_identifier,
            ac.id AS analyzed_id
        FROM content_items ci
        JOIN global_content gc ON gc.platform = ci.platform AND gc.content_id = ci.content_id
        JOIN sources s ON s.id = ci.source_id
        LEFT JOIN ingest_targets it ON it.platform = s.platform AND it.kind = s.type AND it.target_key = TRIM(s.identifier)
        LEFT JOIN analyzed_content ac ON ac.source_id = ci.source_id AND ac.content_id = ci.content_id
        WHERE ci.source_id IS NOT NULL AND ci.group_id IS NOT NULL
    """)).mappings().all()
    for row in link_rows:
        payload = dict(row)
        payload["matched_query"] = row["source_identifier"] if row["source_type"] == "keyword" else ""
        payload["now"] = datetime.now().isoformat()
        session.execute(text("""
            INSERT OR IGNORE INTO source_content (source_id, global_content_id, ingest_target_id, matched_query, first_seen_at)
            VALUES (:source_id, :global_content_id, :ingest_target_id, :matched_query, :now)
        """), payload)
        session.execute(text("""
            UPDATE source_content
            SET ingest_target_id = COALESCE(:ingest_target_id, ingest_target_id),
                matched_query = COALESCE(NULLIF(:matched_query, ''), matched_query)
            WHERE source_id = :source_id AND global_content_id = :global_content_id
        """), payload)
        analyzed_at = payload["now"] if row["analyzed_id"] else None
        session.execute(text("""
            INSERT OR IGNORE INTO group_content (group_id, global_content_id, first_seen_at, analyzed_at)
            VALUES (:group_id, :global_content_id, :now, :analyzed_at)
        """), {**payload, "analyzed_at": analyzed_at})
        if analyzed_at:
            session.execute(text("""
                UPDATE group_content
                SET analyzed_at = COALESCE(analyzed_at, :analyzed_at)
                WHERE group_id = :group_id AND global_content_id = :global_content_id
            """), {**payload, "analyzed_at": analyzed_at})
    session.commit()

    # 4. Signal -> global_content_id，随后按 global_content_id 去重。
    session.execute(text("""
        UPDATE signals
        SET global_content_id = (
            SELECT gc.id
            FROM global_content gc
            JOIN sources s ON s.id = signals.source_id
            WHERE gc.platform = s.platform AND gc.content_id = signals.content_id
            LIMIT 1
        )
        WHERE global_content_id IS NULL
    """))
    session.commit()

    dup_ids = session.execute(text("""
        SELECT global_content_id
        FROM signals
        WHERE global_content_id IS NOT NULL
        GROUP BY global_content_id
        HAVING COUNT(*) > 1
    """)).all()
    for (gid,) in dup_ids:
        rows = session.execute(text("""
            SELECT id, is_new, LENGTH(COALESCE(summary, '')) AS summary_len
            FROM signals
            WHERE global_content_id = :gid
            ORDER BY is_new DESC, summary_len DESC, id ASC
        """), {"gid": gid}).all()
        keep_id = rows[0][0]
        session.execute(text("""
            DELETE FROM signals WHERE global_content_id = :gid AND id != :keep_id
        """), {"gid": gid, "keep_id": keep_id})
    session.commit()

    with engine.connect() as conn:
        conn.execute(text("""
            CREATE UNIQUE INDEX IF NOT EXISTS uq_signal_global_content
            ON signals (global_content_id)
            WHERE global_content_id IS NOT NULL
        """))
        conn.commit()


# ============ Migration 009: 采集目标管理员暂停 ============

@register(9, "009_admin_paused: ingest_targets 管理员暂停调度标记")
def _mig_009_admin_paused(session: Session) -> None:
    from sqlalchemy import inspect, text

    engine = get_engine()
    inspector = inspect(engine)
    cols = {c["name"] for c in inspector.get_columns("ingest_targets")}
    if "admin_paused" not in cols:
        with engine.connect() as conn:
            conn.execute(text("ALTER TABLE ingest_targets ADD COLUMN admin_paused BOOLEAN NOT NULL DEFAULT 0"))
            conn.commit()


# ============ Migration 010: LLM 用量计量 ============

@register(10, "010_llm_usage_metering: LLM 真实成本与用户分摊")
def _mig_010_llm_usage_metering(session: Session) -> None:
    from sqlalchemy import text

    engine = get_engine()
    SQLModel.metadata.create_all(engine)
    with engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS llm_usage_events (
                id INTEGER PRIMARY KEY,
                provider VARCHAR NOT NULL DEFAULT 'openai_compat',
                base_url VARCHAR NOT NULL DEFAULT '',
                model VARCHAR NOT NULL DEFAULT '',
                operation VARCHAR NOT NULL DEFAULT 'unknown',
                metering_status VARCHAR NOT NULL DEFAULT 'ok',
                task_id VARCHAR REFERENCES tasks(id) ON DELETE SET NULL,
                user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
                group_id INTEGER REFERENCES knowledge_groups(id) ON DELETE SET NULL,
                source_id INTEGER REFERENCES sources(id) ON DELETE SET NULL,
                creator_id INTEGER REFERENCES creators(id) ON DELETE SET NULL,
                global_content_id INTEGER REFERENCES global_content(id) ON DELETE SET NULL,
                ingest_target_id INTEGER REFERENCES ingest_targets(id) ON DELETE SET NULL,
                conversation_id INTEGER REFERENCES ask_conversations(id) ON DELETE SET NULL,
                prompt_tokens INTEGER NOT NULL DEFAULT 0,
                completion_tokens INTEGER NOT NULL DEFAULT 0,
                total_tokens INTEGER NOT NULL DEFAULT 0,
                cached_tokens INTEGER NOT NULL DEFAULT 0,
                reasoning_tokens INTEGER NOT NULL DEFAULT 0,
                estimated_total_tokens INTEGER NOT NULL DEFAULT 0,
                request_chars INTEGER NOT NULL DEFAULT 0,
                response_chars INTEGER NOT NULL DEFAULT 0,
                error VARCHAR,
                created_at VARCHAR NOT NULL
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS llm_usage_allocations (
                id INTEGER PRIMARY KEY,
                usage_event_id INTEGER NOT NULL REFERENCES llm_usage_events(id) ON DELETE CASCADE,
                allocation_kind VARCHAR NOT NULL DEFAULT 'direct',
                allocation_ratio FLOAT NOT NULL DEFAULT 1.0,
                user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
                group_id INTEGER REFERENCES knowledge_groups(id) ON DELETE SET NULL,
                source_id INTEGER REFERENCES sources(id) ON DELETE SET NULL,
                creator_id INTEGER REFERENCES creators(id) ON DELETE SET NULL,
                global_content_id INTEGER REFERENCES global_content(id) ON DELETE SET NULL,
                ingest_target_id INTEGER REFERENCES ingest_targets(id) ON DELETE SET NULL,
                allocated_prompt_tokens INTEGER NOT NULL DEFAULT 0,
                allocated_completion_tokens INTEGER NOT NULL DEFAULT 0,
                allocated_total_tokens INTEGER NOT NULL DEFAULT 0,
                allocated_cached_tokens INTEGER NOT NULL DEFAULT 0,
                allocated_reasoning_tokens INTEGER NOT NULL DEFAULT 0,
                allocated_estimated_total_tokens INTEGER NOT NULL DEFAULT 0,
                created_at VARCHAR NOT NULL
            )
        """))
        for table, cols in {
            "llm_usage_events": [
                "created_at", "operation", "model", "metering_status", "task_id",
                "user_id", "group_id", "source_id", "creator_id", "global_content_id", "ingest_target_id",
            ],
            "llm_usage_allocations": [
                "usage_event_id", "created_at", "allocation_kind", "user_id", "group_id",
                "source_id", "creator_id", "global_content_id", "ingest_target_id",
            ],
        }.items():
            for col in cols:
                conn.execute(text(f"CREATE INDEX IF NOT EXISTS ix_{table}_{col} ON {table} ({col})"))
        conn.commit()


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
