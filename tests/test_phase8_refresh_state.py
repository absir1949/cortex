"""Phase 8 测试：刷新状态机（content_items + refresh_runs）"""
from __future__ import annotations
import pytest
from sqlmodel import Session
from sqlmodel import select

from app.db.engine import get_engine
from app.db.schema import KnowledgeGroup, RefreshRun, Source
from app.db.repos import ContentRepo, GroupRepo, SignalRepo, SourceRepo
from app.models.content import Content, ContentType
from app.models.group import SourceType
from app.platforms.base import Capability
from app.services.ingest_service import IngestService
from app.storage.fs import StorageManager


def _session() -> Session:
    return Session(get_engine())


@pytest.fixture(autouse=True)
def _isolated_dirs(tmp_path, monkeypatch):
    from app.settings import settings
    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")
    monkeypatch.setattr(settings, "knowledge_dir", tmp_path / "knowledge")


class FakeAdapter:
    platform = "fake"

    def __init__(self, contents: list[Content]):
        self.contents = contents

    def has(self, cap: Capability) -> bool:
        return cap in self.capabilities()

    def capabilities(self) -> set[Capability]:
        return {Capability.FETCH_CREATOR, Capability.FETCH_COMMENTS}

    def fetch_creator_content(self, creator_id: str, limit: int = 50, days: int | None = None):
        return self.contents[:limit]

    def fetch_comments(self, *args, **kwargs):
        return []


def _make_source(directory: str = "g/a1") -> Source:
    with _session() as s:
        group = GroupRepo(s).create(KnowledgeGroup(name="专题", slug="g"))
        return SourceRepo(s).create(Source(
            group_id=group.id,
            type=SourceType.CREATOR.value,
            platform="fake",
            identifier="creator-1",
            display_name="作者A",
            directory=directory,
        ))


def _patch_signal(monkeypatch, *, is_new: bool = True, profile_error: str = ""):
    def fake_evaluate(self, source, content_id, transcript, comments=None, create_time=None, raise_on_failure=False):
        with _session() as s:
            SignalRepo(s).create(
                source.id,
                content_id,
                group_id=source.group_id,
                is_new=is_new,
                summary="补出的观点",
                matched_points=[] if is_new else ["旧观点"],
                new_points=["新观点"] if is_new else [],
            )
        return {
            "is_new": is_new,
            "summary": "补出的观点",
            "matched_points": [] if is_new else ["旧观点"],
            "new_points": ["新观点"] if is_new else [],
            "profile_updated": is_new and not profile_error,
            "profile_error": profile_error,
        }

    monkeypatch.setattr("app.services.signal_service.SignalService.evaluate", fake_evaluate)


def test_refresh_source_records_state_for_new_text_content(monkeypatch):
    src = _make_source()
    content = Content(
        content_id="c-new",
        platform="fake",
        content_type=ContentType.NOTE,
        title="新内容",
        text="这是一条文本内容",
        create_time="2026-07-07T10:00:00",
    )
    monkeypatch.setattr("app.services.ingest_service.get_adapter", lambda platform: FakeAdapter([content]))
    _patch_signal(monkeypatch, is_new=True)

    result = IngestService().refresh_source(src, force=True)

    assert result["status"] == "succeeded"
    assert result["counts"]["new_contents"] == 1
    assert result["counts"]["transcribed"] == 1
    assert result["counts"]["signaled"] == 1
    assert result["counts"]["profile_updated"] == 1

    with _session() as s:
        item = ContentRepo(s).get(src.id, "c-new")
        assert item is not None
        assert item.transcript_status == "succeeded"
        assert item.signal_status == "succeeded"
        assert item.profile_status == "succeeded"
        assert SignalRepo(s).get_by_content(src.id, "c-new") is not None
        assert s.get(RefreshRun, result["refresh_run_id"]).status == "succeeded"


def test_refresh_source_backfills_existing_transcript_missing_signal(monkeypatch):
    src = _make_source(directory="g/backfill")
    storage = StorageManager(src.directory)
    storage.save_transcript("c-old", "已有转录，但之前没有观点判定", create_time="2026-07-06T10:00:00")
    storage.save_metadata("c-old", {
        "content_id": "c-old",
        "title": "历史内容",
        "platform": "fake",
        "create_time": "2026-07-06T10:00:00",
    })
    monkeypatch.setattr("app.services.ingest_service.get_adapter", lambda platform: FakeAdapter([]))
    _patch_signal(monkeypatch, is_new=True)

    result = IngestService().refresh_source(src, force=True)

    assert result["status"] == "succeeded"
    assert result["counts"]["new_contents"] == 0
    assert result["counts"]["signaled"] == 1

    with _session() as s:
        item = ContentRepo(s).get(src.id, "c-old")
        assert item is not None
        assert item.transcript_status == "succeeded"
        assert item.signal_status == "succeeded"
        assert SignalRepo(s).get_by_content(src.id, "c-old") is not None
        runs = s.exec(select(RefreshRun).where(RefreshRun.source_id == src.id)).all()
        assert len(runs) == 1


def test_refresh_source_repairs_failed_profile_projection(monkeypatch):
    src = _make_source(directory="g/profile-repair")
    storage = StorageManager(src.directory)
    storage.save_transcript("c-profile", "已有转录，需要修复观点档案", create_time="2026-07-06T10:00:00")
    storage.save_metadata("c-profile", {
        "content_id": "c-profile",
        "title": "档案失败内容",
        "platform": "fake",
        "create_time": "2026-07-06T10:00:00",
    })
    monkeypatch.setattr("app.services.ingest_service.get_adapter", lambda platform: FakeAdapter([]))

    # 第一次：Signal 写入成功，但 profile 投影失败。
    _patch_signal(monkeypatch, is_new=True, profile_error="profile boom")
    update_calls = {"n": 0}

    def fail_update(self, source, new_points, summary, *, date=None):
        update_calls["n"] += 1
        raise RuntimeError("profile boom")

    monkeypatch.setattr("app.services.profile_service.ProfileManager.update", fail_update)
    first = IngestService().refresh_source(src, force=True)
    assert first["status"] == "partial_failed"

    with _session() as s:
        item = ContentRepo(s).get(src.id, "c-profile")
        assert item.signal_status == "succeeded"
        assert item.profile_status == "failed"

    # 第二次：不重跑 Signal，单独修复 profile 投影。
    def ok_update(self, source, new_points, summary, *, date=None):
        update_calls["n"] += 1
        return "# 观点档案\n\n- 新观点\n"

    monkeypatch.setattr("app.services.profile_service.ProfileManager.update", ok_update)
    second = IngestService().refresh_source(src, force=True)
    assert second["status"] == "succeeded"
    assert second["counts"]["signaled"] == 0
    assert second["counts"]["profile_updated"] == 1

    with _session() as s:
        item = ContentRepo(s).get(src.id, "c-profile")
        assert item.signal_status == "succeeded"
        assert item.profile_status == "succeeded"
        assert item.profile_error == ""
        assert update_calls["n"] == 2


def test_refresh_source_marks_run_canceled(monkeypatch):
    src = _make_source(directory="g/cancel")
    monkeypatch.setattr("app.services.ingest_service.get_adapter", lambda platform: FakeAdapter([]))

    from app.tasks.runner import CancelledError
    with pytest.raises(CancelledError):
        IngestService().refresh_source(src, force=True, is_cancelled=lambda: True)

    with _session() as s:
        run = s.exec(select(RefreshRun).where(RefreshRun.source_id == src.id)).first()
        assert run.status == "canceled"
        refreshed = SourceRepo(s).get(src.id)
        assert refreshed.last_error == "canceled"
