"""测试：认证 + 多租户 + 共享采集表 + 迁移安全性

验证项：
  1. 全新 DB：迁移跑通，所有新表存在，auth 接口工作
  2. 旧 DB 模拟：有旧数据和旧 schema，迁移不破坏数据
  3. JWT 签发/解析/过期
  4. 验证码校验
  5. knowledge_groups slug 联合唯一（A、B 各建同名 slug 不冲突）

注意：conftest.py 的 autouse fixture 已 reset_engine + create_all。
本文件在此基础上额外跑 run_migrations 来验证迁移链。
"""
from __future__ import annotations
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlmodel import Session, select


@pytest.fixture(autouse=True)
def auth_test_settings():
    from app.settings import settings
    old_secret = settings.jwt_secret
    old_dev_mode = settings.auth_dev_mode
    old_public_register = settings.allow_public_register
    settings.jwt_secret = "test-secret-for-phase6-auth-and-migration-32bytes"
    settings.auth_dev_mode = True
    settings.allow_public_register = True
    yield
    settings.jwt_secret = old_secret
    settings.auth_dev_mode = old_dev_mode
    settings.allow_public_register = old_public_register


def _run_migrations():
    """跑全部迁移（在 conftest 的 create_all 基础上）"""
    from app.db.migrations import run_migrations
    run_migrations(verbose=False)


def _get_engine():
    from app.db.engine import get_engine
    return get_engine()


@pytest.fixture
def migrated_db():
    """DB 已跑完全部迁移（含 v7）"""
    _run_migrations()
    return _get_engine()


@pytest.fixture
def client(migrated_db):
    """TestClient，DB 已迁移"""
    from app.main import create_app
    app = create_app()
    return TestClient(app)


# ============ 1. 迁移：全新 DB ============

class TestFreshMigration:
    def test_all_new_tables_exist(self, migrated_db):
        from sqlalchemy import inspect
        inspector = inspect(migrated_db)
        tables = set(inspector.get_table_names())
        for expected in ["users", "global_content", "source_content",
                         "group_content", "ingest_targets", "knowledge_groups"]:
            assert expected in tables, f"missing table: {expected}"

    def test_default_admin_created(self, migrated_db):
        """迁移应自动建一个 admin 用户"""
        with Session(migrated_db) as s:
            from app.db.schema import User
            admins = s.exec(select(User).where(User.role == "admin")).all()
            assert len(admins) >= 1
            assert admins[0].plan == "pro"

    def test_knowledge_groups_has_owner_id(self, migrated_db):
        from sqlalchemy import inspect
        cols = {c["name"] for c in inspect(migrated_db).get_columns("knowledge_groups")}
        assert "owner_id" in cols

    def test_migration_idempotent(self, migrated_db):
        """再跑一次迁移，不应报错，不应重复建 admin"""
        _run_migrations()  # 第二次
        with Session(migrated_db) as s:
            from app.db.schema import User
            admins = s.exec(select(User).where(User.role == "admin")).all()
            assert len(admins) == 1  # 不重复


# ============ 2. 迁移：旧 DB（模拟有数据）============

class TestMigrationSafety:
    def test_existing_groups_get_owner_id(self):
        """模拟旧 DB：有 group 无 owner_id，迁移后回填 admin"""
        from app.db.engine import get_engine
        from app.db.schema import KnowledgeGroup
        from app.storage.paths import slugify

        # conftest 已 create_all（表已建），先塞一条无 owner_id 的旧数据
        with Session(get_engine()) as s:
            g = KnowledgeGroup(name="测试专题", slug=slugify("测试专题"), enabled=True)
            s.add(g)
            s.commit()
            old_id = g.id
            old_name = g.name

        # 跑迁移到 v7
        _run_migrations()

        # 验证旧数据还在，且 owner_id 被回填
        with Session(get_engine()) as s:
            from app.db.schema import User
            g = s.get(KnowledgeGroup, old_id)
            assert g is not None, "旧 group 不应丢失"
            assert g.name == old_name, "旧数据不应被改"
            assert g.owner_id is not None, "owner_id 应被回填"
            admin = s.get(User, g.owner_id)
            assert admin is not None
            assert admin.role == "admin"

    def test_legacy_slug_unique_table_with_child_fk_migrates(self, tmp_path):
        """真实旧 DB：knowledge_groups 有 UNIQUE(slug)，sources 外键引用它。"""
        from app.db.engine import reset_engine_for_tests, get_engine
        from app.db.migrations import run_migrations

        reset_engine_for_tests(tmp_path / "legacy-v6.db")
        engine = get_engine()
        with engine.begin() as conn:
            conn.execute(text(
                "CREATE TABLE schema_version (version INTEGER PRIMARY KEY, applied_at VARCHAR, note VARCHAR)"
            ))
            conn.execute(text(
                "INSERT INTO schema_version (version, applied_at, note) "
                "VALUES (6, '2026-01-01T00:00:00', 'pre-v7')"
            ))
            conn.execute(text("""
                CREATE TABLE knowledge_groups (
                    id INTEGER PRIMARY KEY,
                    name VARCHAR,
                    slug VARCHAR UNIQUE,
                    description VARCHAR DEFAULT '',
                    enabled BOOLEAN DEFAULT 1,
                    defaults JSON,
                    prompt_overrides JSON,
                    created_at VARCHAR,
                    updated_at VARCHAR
                )
            """))
            conn.execute(text("""
                CREATE TABLE sources (
                    id INTEGER PRIMARY KEY,
                    group_id INTEGER REFERENCES knowledge_groups(id),
                    name VARCHAR
                )
            """))
            conn.execute(text("""
                INSERT INTO knowledge_groups
                    (id, name, slug, description, enabled, defaults, prompt_overrides, created_at, updated_at)
                VALUES
                    (1, '旧专题', 'old-topic', '', 1, '{}', '{}', '2026-01-01', '2026-01-01')
            """))
            conn.execute(text("INSERT INTO sources (id, group_id, name) VALUES (1, 1, '旧源')"))

        applied = run_migrations(verbose=False)
        assert 7 in applied
        with engine.connect() as conn:
            violations = conn.execute(text("PRAGMA foreign_key_check")).all()
            assert violations == []
            group_row = conn.execute(text(
                "SELECT owner_id, slug FROM knowledge_groups WHERE id = 1"
            )).first()
            assert group_row is not None
            assert group_row[0] is not None
            source_row = conn.execute(text("SELECT group_id FROM sources WHERE id = 1")).first()
            assert source_row[0] == 1


# ============ 3. JWT ============

class TestJWT:
    def test_create_and_decode(self):
        from app.auth import create_token, decode_token
        token = create_token(42, "13800000000", "user")
        payload = decode_token(token)
        assert payload["sub"] == "42"
        assert payload["phone"] == "13800000000"
        assert payload["role"] == "user"

    def test_invalid_token_raises(self):
        from app.auth import decode_token
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            decode_token("garbage.token.here")
        assert exc.value.status_code == 401

    def test_expired_token_raises(self):
        from app.auth import decode_token
        from fastapi import HTTPException
        import jwt
        from app.settings import settings
        expired = jwt.encode(
            {"sub": "1", "phone": "138", "role": "user",
             "exp": datetime.now(timezone.utc) - timedelta(hours=1)},
            settings.jwt_secret, algorithm="HS256",
        )
        with pytest.raises(HTTPException) as exc:
            decode_token(expired)
        assert exc.value.status_code == 401


# ============ 4. 验证码 ============

class TestVerifyCode:
    def test_correct_code(self):
        from app.auth import verify_code
        assert verify_code("13800000000", "0000") is True

    def test_wrong_code(self):
        from app.auth import verify_code
        assert verify_code("13800000000", "1234") is False


# ============ 5. Auth API ============

class TestAuthAPI:
    def test_send_code(self, client):
        resp = client.post("/api/auth/code", json={"phone": "13800000000"})
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_register_and_login(self, client):
        # 注册
        resp = client.post("/api/auth/register", json={"phone": "13900000000", "code": "0000"})
        assert resp.status_code == 200
        data = resp.json()
        assert "token" in data
        assert data["user"]["phone"] == "13900000000"
        assert data["user"]["role"] == "user"

        # 重复注册 → 409
        resp = client.post("/api/auth/register", json={"phone": "13900000000", "code": "0000"})
        assert resp.status_code == 409

        # 登录
        resp = client.post("/api/auth/login", json={"phone": "13900000000", "code": "0000"})
        assert resp.status_code == 200
        assert "token" in resp.json()

    def test_login_unregistered(self, client):
        resp = client.post("/api/auth/login", json={"phone": "13700000000", "code": "0000"})
        assert resp.status_code == 404

    def test_wrong_code(self, client):
        resp = client.post("/api/auth/register", json={"phone": "13600000000", "code": "9999"})
        assert resp.status_code == 400

    def test_me_without_token(self, client):
        resp = client.get("/api/auth/me")
        assert resp.status_code == 401

    def test_me_with_token(self, client):
        # 注册拿 token
        resp = client.post("/api/auth/register", json={"phone": "13500000000", "code": "0000"})
        token = resp.json()["token"]
        # 带 token 访问
        resp = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        assert resp.json()["phone"] == "13500000000"


# ============ 6. slug 联合唯一 ============

class TestSlugUniqueness:
    def test_same_slug_different_owners(self, migrated_db):
        """两个不同用户各建同名 group，不应冲突"""
        with Session(migrated_db) as s:
            from app.db.schema import User, KnowledgeGroup
            u1 = User(phone="13800000001", nickname="A", role="user", plan="pro")
            u2 = User(phone="13800000002", nickname="B", role="user", plan="pro")
            s.add_all([u1, u2])
            s.commit()

            g1 = KnowledgeGroup(owner_id=u1.id, name="电商", slug="dianshang")
            g2 = KnowledgeGroup(owner_id=u2.id, name="电商", slug="dianshang")
            s.add_all([g1, g2])
            s.commit()  # 不应报 IntegrityError

            assert g1.id != g2.id
            assert g1.slug == g2.slug  # 同名 OK，因为 owner 不同

    def test_same_slug_same_owner_conflicts(self, migrated_db):
        with Session(migrated_db) as s:
            from sqlalchemy.exc import IntegrityError
            from app.db.schema import User, KnowledgeGroup
            u1 = User(phone="13800000003", nickname="A", role="user", plan="pro")
            s.add(u1)
            s.commit()

            s.add(KnowledgeGroup(owner_id=u1.id, name="电商", slug="dianshang"))
            s.commit()
            s.add(KnowledgeGroup(owner_id=u1.id, name="电商 2", slug="dianshang"))
            with pytest.raises(IntegrityError):
                s.commit()
