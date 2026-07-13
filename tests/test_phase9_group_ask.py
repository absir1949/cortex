"""Phase 9 测试：问听风（专题内问答）"""
from __future__ import annotations
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.db.engine import get_engine
from app.db.schema import AskConversation, AskMessage, GlobalContent, GroupContent, KnowledgeGroup, Source, SourceContent
from app.db.repos import GroupRepo, SourceRepo, SignalRepo
from app.models.content import Comment, Content, ContentType
from app.models.group import SourceType
from app.platforms import Capability
from app.services.knowledge_service import KnowledgeService
from app.services.research_service import ResearchService
from app.storage.fs import GlobalStorage
from tests.auth_helpers import auth_headers


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
        global_item = GlobalContent(
            platform="douyin",
            content_id="c1",
            creator_id=source.creator_id,
            title="低价之后怎么做",
            url="https://example.com/c1",
            author_name="张三",
            create_time="2026-07-08T10:00:00",
        )
        s.add(global_item)
        s.commit()
        s.refresh(global_item)
        s.add(SourceContent(source_id=source.id, global_content_id=global_item.id))
        s.add(GroupContent(group_id=group.id, global_content_id=global_item.id))
        s.commit()
        SignalRepo(s).create(
            source.id,
            "c1",
            global_content_id=global_item.id,
            group_id=group.id,
            is_new=True,
            summary="张三强调低价供给正在转向内容种草",
            new_points=["低价供给转内容种草", "达人会更看重可讲故事的品"],
        )
        group_id, source_id, creator_id = group.id, source.id, source.creator_id
    storage = GlobalStorage("douyin", creator_id)
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
    client = TestClient(app, headers=auth_headers())
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
    client = TestClient(app, headers=auth_headers())
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
    client = TestClient(app, headers=auth_headers())
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
    client = TestClient(app, headers=auth_headers())
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


def test_external_ask_creates_conversation_and_enqueues_task(monkeypatch):
    from app.main import app
    from app.models.group import TaskKind
    client = TestClient(app, headers=auth_headers())
    grp, _ = _make_group_with_material()
    calls = []

    class FakeRunner:
        def enqueue(self, kind, params=None, *, group_id=None, source_id=None):
            calls.append({"kind": kind, "params": params or {}, "group_id": group_id, "source_id": source_id})
            return "task-external-123"

    def fail_answer(self, group_id, question, *, days=30, limit=12):
        raise AssertionError("external ask should not call sync internal LLM")

    monkeypatch.setattr("app.api.ask.get_runner", lambda: FakeRunner())
    monkeypatch.setattr(KnowledgeService, "answer_group_question", fail_answer)

    r = client.post(
        f"/api/groups/{grp}/ask/conversations",
        json={
            "question": "去外面看看最近怎么说",
            "use_internal": True,
            "use_external": True,
            "external_days": 5,
            "external_limit": 8,
            "comment_top_n": 12,
            "platforms": ["douyin"],
        },
    )

    assert r.status_code == 201
    detail = r.json()
    assert [m["role"] for m in detail["messages"]] == ["user", "assistant"]
    task_ev = detail["messages"][1]["evidence"][0]
    assert task_ev["kind"] == "external_search_task"
    assert task_ev["task_id"] == "task-external-123"
    assert calls[0]["kind"] == TaskKind.RESEARCH
    assert calls[0]["group_id"] == grp
    assert calls[0]["params"]["ask_conversation_id"] == detail["id"]
    assert calls[0]["params"]["use_internal"] is True
    assert calls[0]["params"]["days"] == 5
    assert calls[0]["params"]["search_limit"] == 8


def test_research_service_persists_external_material(monkeypatch):
    grp, _ = _make_group_with_material()

    class FakeSearchAdapter:
        platform = "fake"

        def capabilities(self):
            return {Capability.SEARCH, Capability.FETCH_COMMENTS}

        def has(self, cap):
            return cap in self.capabilities()

        def search(self, query, limit=20, days=7):
            return [Content(
                content_id="ext-1",
                platform="fake",
                content_type=ContentType.NOTE,
                title="外部讨论",
                text="外部材料正在讨论保证金变化。",
                author_name="外部作者",
                author_id="author-ext",
                url="https://example.com/ext-1",
                create_time="2026-07-09T12:00:00",
            )]

        def fetch_comments(self, content_id, top_n=20, fetch_replies=True, creator_id=""):
            return [Comment(comment_id="cm1", author="读者", text="这个变化很重要", likes=6)]

    def fake_get_adapter(platform):
        assert platform == "fake"
        return FakeSearchAdapter()

    def fake_answer(self, question, evidence, *, group_id=None):
        assert any(ev.get("content_id") == "ext-1" for ev in evidence)
        assert any("外部材料" in (ev.get("text") or "") for ev in evidence)
        return "外部搜索答案"

    monkeypatch.setattr("app.services.research_service.get_adapter", fake_get_adapter)
    monkeypatch.setattr(KnowledgeService, "answer_question", fake_answer)

    result = ResearchService().run(
        "保证金有什么变化？",
        group_id=grp,
        task_id="task-ext-test",
        platforms=["fake"],
        days=7,
        search_limit=3,
        comment_top_n=5,
    )

    assert result["answer"] == "外部搜索答案"
    assert result["external_evidence_count"] == 1
    with _session() as s:
        global_item = s.exec(
            select(GlobalContent).where(
                GlobalContent.platform == "fake",
                GlobalContent.content_id == "ext-1",
            )
        ).first()
        assert global_item is not None
        group_content = s.exec(
            select(GroupContent).where(
                GroupContent.group_id == grp,
                GroupContent.global_content_id == global_item.id,
            )
        ).first()
        assert group_content is not None
    storage = GlobalStorage("fake", None)
    assert "外部材料" in (storage.get_transcript("ext-1") or "")
    assert storage.get_comments("ext-1")[0]["text"] == "这个变化很重要"


def test_continue_conversation_checks_group_before_llm(monkeypatch):
    from app.main import app
    client = TestClient(app, headers=auth_headers())
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
    client = TestClient(app, headers=auth_headers())
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
    client = TestClient(app, headers=auth_headers())
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
