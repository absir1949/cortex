"""Phase 6 测试：观点信号系统（SignalRepo + SignalService + ProfileManager + API）

覆盖：
  - Signal 表迁移（v3）
  - SignalRepo CRUD（create/upsert/list/过滤）
  - SignalService JSON 解析逻辑（直接/代码块/杂文本）
  - ProfileManager 档案读写（mock LLM）
  - ProfileManager 降级追加（LLM 失败时）
  - signals API 端点
"""
from __future__ import annotations
import pytest
from sqlmodel import Session

from app.db.engine import get_engine
from app.db.schema import KnowledgeGroup, Source, Signal
from app.db.repos import GroupRepo, SourceRepo, SignalRepo
from app.models.group import SourceType
from app.services.signal_service import SignalService
from app.services.profile_service import ProfileManager


@pytest.fixture(autouse=True)
def _isolated_knowledge_dir(tmp_path, monkeypatch):
    """把观点档案/知识报告重定向到临时目录，避免污染真实 knowledge/"""
    from app.settings import settings
    monkeypatch.setattr(settings, "knowledge_dir", tmp_path / "knowledge")


def _session() -> Session:
    return Session(get_engine())


def _make_group_and_source(slug: str = "wx-shop"):
    """造一个 group + source + creator 的辅助。返回 (group_id, source_id)。

    slug 用于隔离档案文件路径。每个测试用不同 slug 避免污染。
    source 会关联到一个 creator（观点档案按 creator_id 全局存储）。
    """
    from app.db.repos import CreatorRepo
    with _session() as s:
        group = GroupRepo(s).create(KnowledgeGroup(name="微信小店", slug=slug))
        # 给每个测试唯一的 identifier，避免 creator 冲突
        identifier = f"MS4_test_{slug}"
        creator = CreatorRepo(s).get_or_create(
            platform="douyin",
            platform_uid=identifier,
            display_name="测试博主",
        )
        src = SourceRepo(s).create(Source(
            group_id=group.id,
            creator_id=creator.id,
            type=SourceType.CREATOR.value,
            platform="douyin",
            identifier=identifier,
            display_name="测试博主",
            directory=f"{slug}/creator-test",
        ))
        return group.id, src.id


def _get_source(source_id: int) -> Source:
    """按 id 重新取 source 对象（在测试自己的 session 里）"""
    with _session() as s:
        return SourceRepo(s).get(source_id)


# ---------- Signal 迁移 ----------

def test_signal_table_exists_after_migration():
    """signals 表能创建并写入"""
    from app.db.migrations import run_migrations
    run_migrations(verbose=False)
    grp, src = _make_group_and_source()
    with _session() as s:
        sig = Signal(source_id=src, group_id=grp, content_id="c1", is_new=True, summary="x", new_points=["p1"])
        s.add(sig)
        s.commit()
        assert sig.id is not None


# ---------- SignalRepo CRUD ----------

def test_signal_repo_create_and_upsert():
    _, src = _make_group_and_source()
    with _session() as s:
        repo = SignalRepo(s)
        sig = repo.create(
            src, "c1",
            group_id=src,
            is_new=True,
            summary="新打法",
            new_points=["私域转公域", "选品决定成败"],
        )
        assert sig.id is not None
        assert sig.is_new is True
        assert len(sig.new_points) == 2

        # upsert：同 (source_id, content_id) 更新而非新建
        repo.create(src, "c1", is_new=False, summary="改判重复", matched_points=["已有"])
        from sqlmodel import select
        rows = list(s.exec(select(Signal).where(
            Signal.source_id == src, Signal.content_id == "c1"
        )).all())
        assert len(rows) == 1
        assert rows[0].is_new is False
        assert rows[0].summary == "改判重复"


def test_signal_repo_list_filters():
    grp, src = _make_group_and_source()
    with _session() as s:
        repo = SignalRepo(s)
        repo.create(src, "c1", group_id=grp, is_new=True, summary="新1", new_points=["a"])
        repo.create(src, "c2", group_id=grp, is_new=False, summary="旧1", matched_points=["x"])
        repo.create(src, "c3", group_id=grp, is_new=True, summary="新2", new_points=["b"])

        assert len(repo.list_by_group(grp)) == 3
        assert len(repo.list_by_group(grp, is_new=True)) == 2
        assert len(repo.list_by_group(grp, is_new=False)) == 1
        assert len(repo.list_new_by_group(grp)) == 2
        assert len(repo.list_by_source(src)) == 3
        # recent 不限 group
        assert len(repo.list_recent()) == 3
        assert len(repo.list_recent(is_new=True)) == 2


def test_signal_repo_get_by_content():
    _, src = _make_group_and_source()
    with _session() as s:
        repo = SignalRepo(s)
        repo.create(src, "c1", is_new=True, summary="x")
        assert repo.get_by_content(src, "c1") is not None
        assert repo.get_by_content(src, "notexist") is None


# ---------- SignalService 解析逻辑（不调 LLM）----------

def test_parse_json_variants():
    """LLM 输出的各种 JSON 形态都能解析"""
    # 直接 JSON
    assert SignalService._parse_json('{"is_new": true, "summary": "x"}') == {"is_new": True, "summary": "x"}
    # 代码块包裹
    assert SignalService._parse_json('```json\n{"is_new": false}\n```') == {"is_new": False}
    assert SignalService._parse_json('```\n{"is_new": true}\n```') == {"is_new": True}
    # 杂文本里的 JSON
    assert SignalService._parse_json('好的，结果如下：\n{"is_new": true, "new_points": ["a"]}\n以上') == {"is_new": True, "new_points": ["a"]}
    # 无效输入
    assert SignalService._parse_json("完全没有 json") is None
    assert SignalService._parse_json("") is None


def test_as_str_list():
    assert SignalService._as_str_list(["a", "", "b", None]) == ["a", "b", "None"]
    assert SignalService._as_str_list("单字符串") == ["单字符串"]
    assert SignalService._as_str_list([]) == []
    assert SignalService._as_str_list(None) == []


def test_build_comments_block():
    comments = [
        {"author": "张三", "text": "说得好", "likes": 100},
        {"author": "李四", "text": "学到了", "likes": 5},
    ]
    block = SignalService._build_comments_block(comments)
    assert "张三" in block and "说得好" in block
    assert SignalService._build_comments_block([]) == ""
    # 截断
    long = [{"author": "x", "text": "y" * 1000, "likes": 0}] * 20
    assert len(SignalService._build_comments_block(long)) <= 1500


# ---------- ProfileManager 档案读写（mock LLM）----------

def test_profile_load_empty_when_missing():
    """没有档案时返回空骨架"""
    _, src = _make_group_and_source(slug="empty-test")
    pm = ProfileManager()
    content = pm.load(_get_source(src))
    assert "核心方法论" in content
    assert "已讲过的点" in content


def test_profile_update_with_mocked_llm(monkeypatch):
    """mock LLM 返回，验证档案写入文件"""
    _, src = _make_group_and_source(slug="update-test")

    pm = ProfileManager()

    def fake_chat(messages, *, config):
        return "# 观点档案\n\n## 核心方法论\n- 私域转公域要先用工具X\n\n## 已讲过的点\n- [2026-01-01] 测试新观点\n"

    monkeypatch.setattr(pm.llm, "chat", fake_chat)

    updated = pm.update(_get_source(src), ["测试新观点"], "测试摘要", date="2026-01-01")
    assert "测试新观点" in updated
    # 文件落盘
    again = pm.load(_get_source(src))
    assert "测试新观点" in again


def test_profile_update_fallback_on_llm_failure(monkeypatch):
    """LLM 失败时降级追加，不丢观点"""
    _, src = _make_group_and_source(slug="fallback-test")
    pm = ProfileManager()

    def fake_chat(messages, *, config):
        raise RuntimeError("LLM 挂了")

    monkeypatch.setattr(pm.llm, "chat", fake_chat)
    updated = pm.update(_get_source(src), ["降级观点A"], "测试", date="2026-02-02")
    assert "降级观点A" in updated
    assert "2026-02-02" in updated


def test_profile_update_noop_when_no_new_points():
    """没新观点时不更新档案"""
    _, src = _make_group_and_source(slug="noop-test")
    pm = ProfileManager()
    src_obj = _get_source(src)
    original = pm.load(src_obj)
    result = pm.update(src_obj, [], "空")
    assert result == original


# ---------- SignalService evaluate（mock LLM，端到端验证 Signal 落表）----------

def test_signal_evaluate_writes_signal_and_updates_profile(monkeypatch):
    """完整流程：LLM 判定新观点 → 落 Signal 表 → 更新档案"""
    grp, src = _make_group_and_source(slug="eval-test")

    svc = SignalService()

    call_count = {"n": 0}

    def fake_chat(messages, *, config):
        call_count["n"] += 1
        # 第一次（evaluate 调用）返回新观点判定
        if call_count["n"] == 1:
            return '{"is_new": true, "summary": "私域新打法", "matched_points": [], "new_points": ["私域转公域用工具X"]}'
        # 第二次（profile.update 调用）返回档案
        return "# 观点档案\n\n## 核心方法论\n- 私域转公域用工具X\n"

    monkeypatch.setattr(svc.llm, "chat", fake_chat)
    monkeypatch.setattr(svc.profiles.llm, "chat", fake_chat)

    result = svc.evaluate(
        _get_source(src), "content-001",
        transcript="今天讲讲私域转公域要用工具X...",
        comments=[{"author": "粉丝", "text": "学到了", "likes": 10}],
        create_time="2026-03-01T10:00:00",
    )

    assert result is not None
    assert result["is_new"] is True
    assert "私域" in result["summary"]

    # Signal 表落库
    with _session() as s:
        sig = SignalRepo(s).get_by_content(src, "content-001")
        assert sig is not None
        assert sig.is_new is True
        assert len(sig.new_points) == 1


def test_signal_evaluate_old_repeat_does_not_update_profile(monkeypatch):
    """LLM 判定老调重弹 → 落 Signal 但不更新档案"""
    grp, src = _make_group_and_source()
    svc = SignalService()

    def fake_chat(messages, *, config):
        return '{"is_new": false, "summary": "重复内容", "matched_points": ["选品决定成败"], "new_points": []}'

    monkeypatch.setattr(svc.llm, "chat", fake_chat)

    # 档案更新不该被调用（因为 is_new=False）
    updated_called = {"v": False}
    orig_update = svc.profiles.update

    def spy_update(*args, **kwargs):
        updated_called["v"] = True
        return orig_update(*args, **kwargs)

    monkeypatch.setattr(svc.profiles, "update", spy_update)

    result = svc.evaluate(_get_source(src), "content-002", transcript="又讲了一遍选品", comments=[])
    assert result["is_new"] is False
    assert updated_called["v"] is False

    with _session() as s:
        sig = SignalRepo(s).get_by_content(src, "content-002")
        assert sig is not None
        assert sig.is_new is False


def test_signal_evaluate_returns_none_on_llm_failure(monkeypatch):
    """LLM 失败 → 返回 None，不落 Signal（不阻塞采集）"""
    _, src = _make_group_and_source()
    svc = SignalService()

    def fake_chat(messages, *, config):
        raise RuntimeError("LLM 挂了")

    monkeypatch.setattr(svc.llm, "chat", fake_chat)

    result = svc.evaluate(_get_source(src), "content-003", transcript="xxx", comments=[])
    assert result is None

    with _session() as s:
        assert SignalRepo(s).get_by_content(src, "content-003") is None


def test_signal_evaluate_below_min_new_points(monkeypatch):
    """新观点数低于阈值 signal_min_new_points → 判为旧"""
    _, src = _make_group_and_source()
    svc = SignalService()

    def fake_chat(messages, *, config):
        # is_new=True 但 new_points 为空 → 应被修正为 False
        return '{"is_new": true, "summary": "x", "matched_points": ["old"], "new_points": []}'

    monkeypatch.setattr(svc.llm, "chat", fake_chat)

    result = svc.evaluate(_get_source(src), "content-004", transcript="x", comments=[])
    assert result["is_new"] is False  # 被 signal_min_new_points=1 修正


# ---------- signals API 端点 ----------

def test_signals_api_endpoints():
    from fastapi.testclient import TestClient
    from app.main import app
    client = TestClient(app)

    grp, src = _make_group_and_source()
    # 造两条信号
    with _session() as s:
        SignalRepo(s).create(src, "c1", group_id=grp, is_new=True, summary="新观点A", new_points=["a"])
        SignalRepo(s).create(src, "c2", group_id=grp, is_new=False, summary="重复B", matched_points=["b"])

    # /api/signals/recent
    r = client.get("/api/signals/recent")
    assert r.status_code == 200
    assert len(r.json()) == 2

    # /api/signals/recent?is_new=true
    r = client.get("/api/signals/recent?is_new=true")
    assert len(r.json()) == 1
    assert r.json()[0]["summary"] == "新观点A"

    # /api/groups/{id}/signals
    r = client.get(f"/api/groups/{grp}/signals")
    assert r.status_code == 200
    assert len(r.json()) == 2
    assert r.json()[0]["source_name"] == "测试博主"

    # /api/groups/{id}/signals?is_new=true
    r = client.get(f"/api/groups/{grp}/signals?is_new=true")
    assert len(r.json()) == 1

    # /api/groups/{id}/signals/stats
    r = client.get(f"/api/groups/{grp}/signals/stats")
    assert r.json()["new_signal_count"] == 1
    assert r.json()["repeat_count"] == 1

    # /api/groups/{id}/sources/{source_id}/profile（档案不存在时返回提示）
    r = client.get(f"/api/groups/{grp}/sources/{src}/profile")
    assert r.status_code == 200
    assert "尚未建立档案" in r.text or "观点档案" in r.text


def test_signals_api_group_not_found():
    from fastapi.testclient import TestClient
    from app.main import app
    client = TestClient(app)

    r = client.get("/api/groups/99999/signals")
    assert r.status_code == 404
