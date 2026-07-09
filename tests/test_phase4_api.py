"""Phase 4 冒烟测试：REST API + TaskRunner"""
from __future__ import annotations
from fastapi.testclient import TestClient

from app.main import create_app
from tests.auth_helpers import auth_headers


def _client() -> TestClient:
    app = create_app()
    # 使用 lifespan
    return TestClient(app, headers=auth_headers())


def test_health():
    with _client() as client:
        resp = client.get("/api/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


def test_groups_crud_via_api():
    with _client() as client:
        # 空列表
        r = client.get("/api/groups")
        assert r.status_code == 200
        initial_count = len(r.json())

        # 创建
        r = client.post("/api/groups", json={"name": "微信小店", "slug": "wechat-shop"})
        assert r.status_code == 201
        group = r.json()
        assert group["slug"] == "wechat-shop"
        gid = group["id"]

        # 列表
        r = client.get("/api/groups")
        assert len(r.json()) == initial_count + 1

        # 详情
        r = client.get(f"/api/groups/{gid}")
        assert r.status_code == 200
        assert r.json()["sources"] == []

        # 改
        r = client.patch(f"/api/groups/{gid}", json={"description": "更新"})
        assert r.json()["description"] == "更新"

        # 加源
        r = client.post(f"/api/groups/{gid}/sources", json={
            "type": "creator",
            "platform": "douyin",
            "identifier": "MS4w_xxx",
            "display_name": "狼教授",
        })
        assert r.status_code == 201
        src = r.json()
        assert src["type"] == "creator"

        # 详情含源
        r = client.get(f"/api/groups/{gid}")
        assert len(r.json()["sources"]) == 1

        # 重复报错
        r = client.post(f"/api/groups/{gid}/sources", json={
            "type": "creator", "platform": "douyin", "identifier": "MS4w_xxx", "display_name": "dup",
        })
        assert r.status_code == 400

        # 删源
        r = client.delete(f"/api/groups/{gid}/sources/{src['id']}")
        assert r.status_code == 204

        # 删组
        r = client.delete(f"/api/groups/{gid}?cascade=true")
        assert r.status_code == 204


def test_config_api():
    with _client() as client:
        r = client.get("/api/config")
        assert r.status_code == 200
        body = r.json()
        assert "values" in body and "schema" in body
        assert "llm_model" in body["values"]
        # schema 存在
        assert "llm_base_url" in body["schema"]

        r = client.patch("/api/config", json={"values": {"llm_model": "test-model", "comment_top_n": 33}})
        assert r.status_code == 200
        values = r.json()["values"]
        assert values["llm_model"] == "test-model"
        assert values["comment_top_n"] == 33


def test_prompts_api():
    with _client() as client:
        r = client.get("/api/config/prompts")
        assert r.status_code == 200
        assert "analysis_prompt_template" in r.json()

        r = client.patch("/api/config/prompts/analysis_prompt_template", json={"content": "NEW {creator_name}"})
        assert r.status_code == 200

        r = client.get("/api/config/prompts")
        assert "NEW" in r.json()["analysis_prompt_template"]


def test_tasks_empty():
    with _client() as client:
        r = client.get("/api/tasks")
        assert r.status_code == 200
        assert isinstance(r.json(), list)


def test_research_endpoint_requires_valid_group():
    with _client() as client:
        r = client.post("/api/groups/999/research", json={"question": "q"})
        assert r.status_code == 404


def test_scheduler_endpoints():
    with _client() as client:
        r = client.get("/api/scheduler/jobs")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

        r = client.post("/api/scheduler/reload")
        assert r.status_code == 200


def test_task_runner_enqueue_and_status():
    """注册一个假 handler，验证任务能跑通"""
    from app.tasks import get_runner
    from app.tasks.registry import register_handler
    from app.models.group import TaskKind
    from app.services.task_service import TaskService

    @register_handler("test_echo")
    def echo_handler(task, ctx):
        ctx.log("running echo")
        ctx.progress({"stage": "working"})
        return {"echoed": task.params.get("msg", "")}

    with _client() as client:
        runner = get_runner()
        task_id = runner.enqueue("test_echo", params={"msg": "hello"})

        # 等完成（最多 3 秒）
        import time
        for _ in range(30):
            t = TaskService().get(task_id)
            if t and t.status in ("succeeded", "failed", "canceled"):
                break
            time.sleep(0.1)

        r = client.get(f"/api/tasks/{task_id}")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "succeeded"
        assert body["result"]["echoed"] == "hello"
