"""Phase 9 测试：问听风（专题内问答）"""
from __future__ import annotations
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.db.engine import get_engine
from app.db.schema import AskConversation, AskMessage, KnowledgeGroup, Source
from app.db.repos import GroupRepo, SourceRepo, SignalRepo
from app.models.group import SourceType
from app.services.knowledge_service import KnowledgeService
from app.storage.fs import StorageManager


def _session() -> Session:
    return Session(get_engine())


@pytest.fixture(autouse=True)
def _isolated_dirs(tmp_path: Path, monkeypatch):
    from app.settings import settings
    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")
    monkeypatch.setattr(settings, "knowledge_dir", tmp_path / "knowledge")


def _make_group_with_material():
    with _session() as s:
        group = GroupRepo(s).create(KnowledgeGroup(name="微信小店", slug="ask-test"))
        source = SourceRepo(s).create(Source(
            group_id=group.id,
            type=SourceType.CREATOR.value,
            platform="douyin",
            identifier="a1",
            display_name="张三",
            directory="ask-test/a1",
        ))
        SignalRepo(s).create(
            source.id,
            "c1",
            group_id=group.id,
            is_new=True,
            summary="张三强调低价供给正在转向内容种草",
            new_points=["低价供给转内容种草", "达人会更看重可讲故事的品"],
        )
        group_id, source_id = group.id, source.id
    storage = StorageManager("ask-test/a1")
    storage.save_metadata("c1", {
        "content_id": "c1",
        "title": "低价之后怎么做",
        "url": "https://example.com/c1",
        "create_time": "2026-07-08T10:00:00",
    })
    storage.save_transcript("c1", "不要只卷低价，接下来要把商品讲成内容，达人种草才会带动转化。", "2026-07-08T10:00:00")
    storage.save_comments("c1", [{"author": "观众", "text": "内容种草确实比单纯低价稳", "likes": 3}], "2026-07-08T10:00:00")
    return group_id, source_id


def test_answer_group_question_uses_internal_material(monkeypatch):
    grp, _ = _make_group_with_material()
    svc = KnowledgeService()

    def fake_chat(messages, *, config):
        text = messages[-1].content
        assert "低价供给转内容种草" in text
        assert "不要只卷低价" in text
        return "结论：最近在强调从低价供给转向内容种草。"

    monkeypatch.setattr(svc.llm, "chat", fake_chat)
    result = svc.answer_group_question(grp, "最近这些人在强调什么？", days=30, limit=5)

    assert result["scope"] == "internal"
    assert "内容种草" in result["answer"]
    assert result["evidence_count"] == 1
    assert result["evidence"][0]["author"] == "张三"


def test_answer_group_question_group_not_found():
    with pytest.raises(ValueError):
        KnowledgeService().answer_group_question(99999, "问一下")


def test_group_ask_api_endpoint(monkeypatch):
    from app.main import app
    client = TestClient(app)
    grp, _ = _make_group_with_material()

    def fake_answer(self, group_id, question, *, days=30, limit=12):
        return {
            "answer": f"回答：{question}",
            "evidence": [],
            "scope": "internal",
            "days": days,
            "evidence_count": 0,
        }

    monkeypatch.setattr(KnowledgeService, "answer_group_question", fake_answer)
    r = client.post(f"/api/groups/{grp}/ask", json={"question": "最近在讲什么？"})

    assert r.status_code == 200
    assert r.json()["scope"] == "internal"
    assert r.json()["answer"].startswith("回答")


def test_source_summary_api_counts_recent_material():
    from app.main import app
    client = TestClient(app)
    grp, _ = _make_group_with_material()

    r = client.get(f"/api/groups/{grp}/sources/summary?days=7")

    assert r.status_code == 200
    data = r.json()
    assert len(data) == 1
    assert data[0]["recent_content_count"] == 1
    assert data[0]["recent_new_signal_count"] == 1
    assert data[0]["display_name"] == "张三"


def test_group_summary_api_counts_recent_material():
    from app.main import app
    client = TestClient(app)
    grp, _ = _make_group_with_material()

    r = client.get("/api/groups/summary?days=7")

    assert r.status_code == 200
    rows = r.json()
    row = next(x for x in rows if x["id"] == grp)
    assert row["source_count"] == 1
    assert row["recent_content_count"] == 1
    assert row["recent_new_signal_count"] == 1
    assert row["failed_source_count"] == 0


def test_group_ask_conversation_flow(monkeypatch):
    from app.main import app
    client = TestClient(app)
    grp, _ = _make_group_with_material()

    def fake_answer(self, group_id, question, *, days=30, limit=12):
        return {
            "answer": f"回答：{question}",
            "evidence": [{
                "content_id": "c1",
                "source_id": 1,
                "author": "张三",
                "title": "低价之后怎么做",
                "url": "",
                "create_time": "",
                "signal_summary": "内容种草",
                "new_points": ["内容种草"],
                "snippet": "不要只卷低价",
            }],
            "scope": "internal",
            "days": days,
            "evidence_count": 1,
        }

    monkeypatch.setattr(KnowledgeService, "answer_group_question", fake_answer)

    r = client.post(f"/api/groups/{grp}/ask/conversations", json={"question": "最近强调什么？"})
    assert r.status_code == 201
    detail = r.json()
    assert detail["title"] == "最近强调什么？"
    assert [m["role"] for m in detail["messages"]] == ["user", "assistant"]
    conv_id = detail["id"]

    r = client.post(f"/api/groups/{grp}/ask/conversations/{conv_id}/messages", json={"question": "继续说"})
    assert r.status_code == 200
    assert len(r.json()["messages"]) == 4

    r = client.get(f"/api/groups/{grp}/ask/conversations")
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 1
    assert rows[0]["message_count"] == 4
    assert rows[0]["evidence_count"] == 1


def test_continue_conversation_checks_group_before_llm(monkeypatch):
    from app.main import app
    client = TestClient(app)
    grp, _ = _make_group_with_material()
    with _session() as s:
        other = GroupRepo(s).create(KnowledgeGroup(name="另一个专题", slug="ask-other"))
        conv = AskConversation(group_id=grp, title="已有对话")
        s.add(conv)
        s.commit()
        s.refresh(conv)
        other_id, conv_id = other.id, conv.id

    called = []

    def fake_answer(self, group_id, question, *, days=30, limit=12):
        called.append((group_id, question))
        return {"answer": "不应调用", "evidence": [], "scope": "internal", "days": days, "evidence_count": 0}

    monkeypatch.setattr(KnowledgeService, "answer_group_question", fake_answer)

    r = client.post(f"/api/groups/{other_id}/ask/conversations/{conv_id}/messages", json={"question": "继续说"})

    assert r.status_code == 404
    assert called == []


def test_create_conversation_checks_group_before_llm(monkeypatch):
    from app.main import app
    client = TestClient(app)
    called = []

    def fake_answer(self, group_id, question, *, days=30, limit=12):
        called.append((group_id, question))
        return {"answer": "不应调用", "evidence": [], "scope": "internal", "days": days, "evidence_count": 0}

    monkeypatch.setattr(KnowledgeService, "answer_group_question", fake_answer)

    r = client.post("/api/groups/999999/ask/conversations", json={"question": "最近强调什么？"})

    assert r.status_code == 404
    assert called == []


def test_delete_group_cascades_ask_conversations():
    from app.main import app
    client = TestClient(app)
    grp, _ = _make_group_with_material()
    with _session() as s:
        conv = AskConversation(group_id=grp, title="待删除对话")
        s.add(conv)
        s.commit()
        s.refresh(conv)
        msg = AskMessage(conversation_id=conv.id, role="user", content="问题")
        s.add(msg)
        s.commit()
        conv_id, msg_id = conv.id, msg.id

    r = client.delete(f"/api/groups/{grp}?cascade=true")

    assert r.status_code == 204
    with _session() as s:
        assert s.get(AskConversation, conv_id) is None
        assert s.get(AskMessage, msg_id) is None
