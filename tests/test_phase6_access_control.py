"""Phase 6 access-control regression tests."""
from __future__ import annotations
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.auth import create_token
from app.db.engine import get_engine
from app.db.schema import ContentItem, KnowledgeGroup, Report, Signal, Source, Task, User
from app.main import create_app
from app.storage.fs import StorageManager


@pytest.fixture(autouse=True)
def auth_settings(tmp_path: Path):
    from app.settings import settings
    old_secret = settings.jwt_secret
    old_data_dir = settings.data_dir
    old_knowledge_dir = settings.knowledge_dir
    settings.jwt_secret = "test-secret-for-access-control-32bytes"
    settings.data_dir = tmp_path / "data"
    settings.knowledge_dir = tmp_path / "knowledge"
    yield
    settings.jwt_secret = old_secret
    settings.data_dir = old_data_dir
    settings.knowledge_dir = old_knowledge_dir


def _client() -> TestClient:
    return TestClient(create_app())


def _headers(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_token(user['id'], user['phone'], user['role'])}"}


def _seed_two_users():
    with Session(get_engine()) as s:
        admin = User(phone="13000000000", nickname="admin", role="admin", plan="pro")
        a = User(phone="13100000000", nickname="A", role="user", plan="pro")
        b = User(phone="13200000000", nickname="B", role="user", plan="pro")
        s.add_all([admin, a, b])
        s.commit()
        s.refresh(admin)
        s.refresh(a)
        s.refresh(b)

        ga = KnowledgeGroup(owner_id=a.id, name="A 专题", slug="topic-a")
        gb = KnowledgeGroup(owner_id=b.id, name="B 专题", slug="topic-b")
        s.add_all([ga, gb])
        s.commit()
        s.refresh(ga)
        s.refresh(gb)

        src = Source(
            group_id=ga.id,
            type="creator",
            platform="douyin",
            identifier="creator-a",
            display_name="A 作者",
            directory=f"{ga.id}/creator-a",
        )
        s.add(src)
        s.commit()
        s.refresh(src)

        s.add(Signal(
            group_id=ga.id,
            source_id=src.id,
            content_id="content-a",
            is_new=True,
            summary="A 的新信号",
            matched_points=[],
            new_points=["a"],
        ))
        s.add(Report(
            group_id=ga.id,
            kind="scheduled",
            title="A 报告",
            summary="A summary",
            content_md_path=str(Path("missing.md")),
            content_json_path=None,
            sources_used=[],
        ))
        s.add(Task(
            id="task-a",
            kind="ingest",
            status="succeeded",
            group_id=ga.id,
            source_id=src.id,
        ))
        s.add(ContentItem(
            group_id=ga.id,
            source_id=src.id,
            platform="douyin",
            content_id="content-a",
            transcript_status="succeeded",
        ))
        s.commit()

        StorageManager(src.directory).save_transcript(
            "content-a",
            "A 用户专题里的转录",
            "2026-07-09T10:00:00",
        )
        return (
            {"id": admin.id, "phone": admin.phone, "role": admin.role},
            {"id": a.id, "phone": a.phone, "role": a.role},
            {"id": b.id, "phone": b.phone, "role": b.role},
            {"id": ga.id},
            {"id": gb.id},
        )


def test_default_lock_and_admin_gate():
    admin, a, _, _, _ = _seed_two_users()
    with _client() as client:
        assert client.get("/api/health").status_code == 200
        assert client.get("/api/groups").status_code == 401
        assert client.post("/api/auth/code", json={"phone": "13900000000"}).status_code == 200

        assert client.get("/api/config", headers=_headers(a)).status_code == 403
        assert client.get("/api/config", headers=_headers(admin)).status_code == 200


def test_owner_isolation_for_core_reads():
    _, a, b, ga, gb = _seed_two_users()
    a_headers = _headers(a)
    b_headers = _headers(b)

    with _client() as client:
        groups = client.get("/api/groups", headers=b_headers)
        assert groups.status_code == 200
        assert [g["id"] for g in groups.json()] == [gb["id"]]

        assert client.get(f"/api/groups/{ga['id']}", headers=b_headers).status_code == 403
        assert client.get(f"/api/groups/{ga['id']}", headers=a_headers).status_code == 200

        signals = client.get("/api/signals/recent", headers=b_headers)
        assert signals.status_code == 200
        assert signals.json() == []

        reports = client.get("/api/reports/recent", headers=b_headers)
        assert reports.status_code == 200
        assert reports.json() == []

        tasks = client.get("/api/tasks", headers=b_headers)
        assert tasks.status_code == 200
        assert tasks.json() == []

        transcript_b = client.get(
            "/api/contents/content-a/transcript?platform=douyin",
            headers=b_headers,
        )
        assert transcript_b.status_code == 404

        transcript_a = client.get(
            "/api/contents/content-a/transcript?platform=douyin",
            headers=a_headers,
        )
        assert transcript_a.status_code == 200
        assert "A 用户专题里的转录" in transcript_a.text
