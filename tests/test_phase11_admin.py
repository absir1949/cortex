from __future__ import annotations

from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlmodel import Session

from app.auth import create_token
from app.db.engine import get_engine
from app.db.schema import (
    GlobalContent,
    GroupContent,
    IngestTarget,
    KnowledgeGroup,
    Report,
    Signal,
    Source,
    Task,
    User,
)
from app.main import create_app


def _headers(user: dict) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_token(user['id'], user['phone'], user['role'])}"}


def _seed_admin_overview():
    with Session(get_engine()) as s:
        admin = User(phone="13000000000", nickname="admin", role="admin", plan="pro")
        user = User(phone="13100000000", nickname="客户A", role="user", plan="pro", expires_at="2099-01-01T00:00:00")
        s.add_all([admin, user])
        s.commit()
        s.refresh(admin)
        s.refresh(user)

        group = KnowledgeGroup(owner_id=user.id, name="微信小店", slug="wechat-shop", enabled=True)
        s.add(group)
        s.commit()
        s.refresh(group)

        source = Source(
            group_id=group.id,
            type="creator",
            platform="douyin",
            identifier="creator-a",
            display_name="九柚米电商",
            enabled=True,
            directory=f"{group.id}/creator-a",
            last_check="2026-07-10T08:00:00",
        )
        s.add(source)
        s.commit()
        s.refresh(source)

        target = IngestTarget(
            platform="douyin",
            kind="creator",
            target_key="creator-a",
            enabled=True,
            interval_hours=24,
            days=7,
            content_limit=50,
            comment_top_n=20,
            last_check="2026-07-10T08:00:00",
            last_error="采集失败",
            running_task_id="stale-task",
            locked_at=datetime.now().isoformat(),
        )
        s.add(target)
        s.commit()
        s.refresh(target)

        content = GlobalContent(
            platform="douyin",
            content_id="content-a",
            title="新内容",
            author_name="九柚米电商",
            first_seen_at="2026-07-10T09:00:00",
            create_time="2026-07-10T09:00:00",
        )
        s.add(content)
        s.commit()
        s.refresh(content)

        s.add(GroupContent(group_id=group.id, global_content_id=content.id))
        s.add(Signal(
            global_content_id=content.id,
            group_id=group.id,
            source_id=source.id,
            content_id="content-a",
            is_new=True,
            summary="新观点",
            matched_points=[],
            new_points=["新观点"],
        ))
        task = Task(
            id="task-admin-overview",
            kind="ingest_target",
            status="failed",
            group_id=group.id,
            source_id=source.id,
            params={"target_id": target.id},
            error="boom",
        )
        s.add(task)
        s.commit()

        s.add(Report(
            group_id=group.id,
            task_id="task-admin-overview",
            kind="scheduled",
            title="微信小店日报",
            summary="摘要",
            content_md_path=str(Path("missing.md")),
            sources_used=[],
        ))
        s.commit()
        return (
            {"id": admin.id, "phone": admin.phone, "role": admin.role},
            {"id": user.id, "phone": user.phone, "role": user.role},
            int(target.id),
            "task-admin-overview",
        )


def test_admin_overview_is_admin_only():
    admin, user, _, _ = _seed_admin_overview()
    with TestClient(create_app()) as client:
        assert client.get("/api/admin/overview", headers=_headers(user)).status_code == 403
        resp = client.get("/api/admin/overview", headers=_headers(admin))
        assert resp.status_code == 200

    data = resp.json()
    assert "reports" not in data
    assert data["stats"]["users"] == 2
    assert data["stats"]["groups"] == 1
    assert data["stats"]["active_targets"] == 1
    assert data["stats"]["new_signals"] == 1
    assert data["stats"]["tasks"] == 1

    customer = next(row for row in data["users"] if row["phone"] == "13100000000")
    assert customer["group_count"] == 1
    assert customer["source_count"] == 1
    assert customer["content_count"] == 1
    assert customer["new_signal_count"] == 1
    assert customer["report_count"] == 1

    target = data["targets"][0]
    assert target["target_key"] == "creator-a"
    assert target["subscriber_count"] == 1
    assert target["group_count"] == 1
    assert target["admin_paused"] is False

    task = data["tasks"][0]
    assert task["id"] == "task-admin-overview"
    assert task["group_name"] == "微信小店"
    assert task["owner_phone"] == "13100000000"


def test_admin_user_update_plan():
    admin, user, _, _ = _seed_admin_overview()
    with TestClient(create_app()) as client:
        resp = client.patch(
            f"/api/admin/users/{user['id']}",
            headers=_headers(admin),
            json={"plan": "none", "expires_at": None},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["plan"] == "none"
        assert body["expires_at"] is None


def test_admin_cannot_change_own_role():
    admin, _, _, _ = _seed_admin_overview()
    with TestClient(create_app()) as client:
        resp = client.patch(
            f"/api/admin/users/{admin['id']}",
            headers=_headers(admin),
            json={"role": "user"},
        )
        assert resp.status_code == 400


def test_admin_target_clear_error():
    admin, _, target_id, _ = _seed_admin_overview()
    with TestClient(create_app()) as client:
        resp = client.post(f"/api/admin/targets/{target_id}/clear-error", headers=_headers(admin))
        assert resp.status_code == 200
        body = resp.json()
        assert body["last_error"] is None
        assert body["running_task_id"] is None
        assert body["locked_at"] is None


def test_admin_target_pause_and_resume():
    admin, _, target_id, _ = _seed_admin_overview()
    with TestClient(create_app()) as client:
        pause = client.patch(
            f"/api/admin/targets/{target_id}",
            headers=_headers(admin),
            json={"enabled": False},
        )
        assert pause.status_code == 200
        assert pause.json()["admin_paused"] is True
        assert pause.json()["enabled"] is False

        resume = client.patch(
            f"/api/admin/targets/{target_id}",
            headers=_headers(admin),
            json={"enabled": True},
        )
        assert resume.status_code == 200
        assert resume.json()["admin_paused"] is False
        assert resume.json()["enabled"] is True


def test_admin_target_run_rejects_locked_target():
    admin, _, target_id, _ = _seed_admin_overview()
    with TestClient(create_app()) as client:
        resp = client.post(f"/api/admin/targets/{target_id}/run", headers=_headers(admin))
        assert resp.status_code == 409


def test_admin_target_run_after_clear_error():
    admin, _, target_id, _ = _seed_admin_overview()
    with TestClient(create_app()) as client, patch("app.api.admin.get_runner") as mock_runner:
        mock_runner.return_value.enqueue.return_value = "new-task-id"
        assert client.post(f"/api/admin/targets/{target_id}/clear-error", headers=_headers(admin)).status_code == 200
        resp = client.post(f"/api/admin/targets/{target_id}/run", headers=_headers(admin))
        assert resp.status_code == 200
        assert resp.json() == {"ok": True, "task_id": "new-task-id"}


def test_admin_task_retry():
    admin, _, _, task_id = _seed_admin_overview()
    with TestClient(create_app()) as client, patch("app.api.admin.get_runner") as mock_runner:
        mock_runner.return_value.enqueue.return_value = "retry-task-id"
        resp = client.post(f"/api/admin/tasks/{task_id}/retry", headers=_headers(admin))
        assert resp.status_code == 200
        assert resp.json() == {"ok": True, "task_id": "retry-task-id"}


def test_admin_mutations_forbidden_for_user():
    _, user, target_id, task_id = _seed_admin_overview()
    with TestClient(create_app()) as client:
        assert client.patch(
            f"/api/admin/users/{user['id']}",
            headers=_headers(user),
            json={"plan": "pro"},
        ).status_code == 403
        assert client.post(
            f"/api/admin/targets/{target_id}/clear-error",
            headers=_headers(user),
        ).status_code == 403
        assert client.post(
            f"/api/admin/tasks/{task_id}/retry",
            headers=_headers(user),
        ).status_code == 403
