"""Phase 10 测试：共享采集 runtime"""
from __future__ import annotations

from pathlib import Path

import pytest
from sqlmodel import Session, select

from app.db.engine import get_engine, get_session
from app.db.repos import GroupRepo, SignalRepo
from app.db.schema import GlobalContent, GroupContent, KnowledgeGroup, Signal, SourceContent
from app.models.content import Content, ContentType
from app.models.group import SourceType
from app.platforms.base import Capability
from app.services.ingest_service import IngestService
from app.services.knowledge_service import KnowledgeService
from app.services.source_service import SourceService


@pytest.fixture(autouse=True)
def _isolated_dirs(tmp_path: Path, monkeypatch):
    from app.settings import settings
    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")
    monkeypatch.setattr(settings, "knowledge_dir", tmp_path / "knowledge")


class FakeAdapter:
    platform = "douyin"
    calls = 0

    def capabilities(self):
        return {Capability.FETCH_CREATOR}

    def has(self, cap):
        return cap in self.capabilities()

    def fetch_creator_content(self, creator_id: str, limit: int = 50, days: int | None = None):
        self.calls += 1
        return [
            Content(
                content_id="shared-1",
                platform="douyin",
                content_type=ContentType.POST,
                author_id=creator_id,
                author_name="共享作者",
                title="同一条内容",
                text="这是一条会被多个专题复用的内容。",
                create_time="2026-07-09T10:00:00",
                url="https://example.com/shared-1",
            )
        ]


def _make_group(name: str) -> KnowledgeGroup:
    with Session(get_engine()) as s:
        return GroupRepo(s).create(KnowledgeGroup(name=name, slug=name))


def _fake_signal_evaluate(self, source, content_id, transcript, comments=None, create_time=None, raise_on_failure=False, global_content_id=None):
    with get_session() as s:
        SignalRepo(s).create(
            source_id=source.id,
            content_id=content_id,
            global_content_id=global_content_id,
            group_id=source.group_id,
            is_new=True,
            summary="共享内容产生了新观点",
            new_points=["共享采集只判定一次"],
        )
    return {
        "is_new": True,
        "summary": "共享内容产生了新观点",
        "matched_points": [],
        "new_points": ["共享采集只判定一次"],
        "profile_updated": True,
        "profile_error": "",
    }


def test_two_groups_same_creator_fetch_once_and_share_content(monkeypatch):
    adapter = FakeAdapter()
    monkeypatch.setattr("app.services.ingest_service.get_adapter", lambda platform: adapter)
    monkeypatch.setattr("app.services.signal_service.SignalService.evaluate", _fake_signal_evaluate)

    g1 = _make_group("g1")
    g2 = _make_group("g2")
    svc = SourceService()
    s1 = svc.create(g1.id, type=SourceType.CREATOR, platform="douyin", identifier="creator-a", display_name="A")
    s2 = svc.create(g2.id, type=SourceType.CREATOR, platform="douyin", identifier="creator-a", display_name="A")

    result = IngestService().run_group(g1.id, force=True)

    assert result["status"] == "succeeded"
    assert adapter.calls == 1
    with Session(get_engine()) as s:
        global_items = s.exec(select(GlobalContent)).all()
        assert len(global_items) == 1
        gid = global_items[0].id
        source_links = s.exec(select(SourceContent).where(SourceContent.global_content_id == gid)).all()
        group_links = s.exec(select(GroupContent).where(GroupContent.global_content_id == gid)).all()
        signals = s.exec(select(Signal).where(Signal.global_content_id == gid)).all()

    assert {link.source_id for link in source_links} == {s1.id, s2.id}
    assert {link.group_id for link in group_links} == {g1.id, g2.id}
    assert len(signals) == 1


def test_new_subscription_backfills_existing_global_content(monkeypatch):
    adapter = FakeAdapter()
    monkeypatch.setattr("app.services.ingest_service.get_adapter", lambda platform: adapter)
    monkeypatch.setattr("app.services.signal_service.SignalService.evaluate", _fake_signal_evaluate)

    g1 = _make_group("g1")
    SourceService().create(g1.id, type="creator", platform="douyin", identifier="creator-a", display_name="A")
    IngestService().run_group(g1.id, force=True)

    g2 = _make_group("g2")
    src2 = SourceService().create(g2.id, type="creator", platform="douyin", identifier="creator-a", display_name="A")

    with Session(get_engine()) as s:
        global_item = s.exec(select(GlobalContent)).one()
        source_link = s.exec(
            select(SourceContent).where(
                SourceContent.source_id == src2.id,
                SourceContent.global_content_id == global_item.id,
            )
        ).first()
        group_link = s.exec(
            select(GroupContent).where(
                GroupContent.group_id == g2.id,
                GroupContent.global_content_id == global_item.id,
            )
        ).first()
    assert source_link is not None
    assert group_link is not None


def test_delete_subscription_removes_only_that_group_watermark(monkeypatch):
    adapter = FakeAdapter()
    monkeypatch.setattr("app.services.ingest_service.get_adapter", lambda platform: adapter)
    monkeypatch.setattr("app.services.signal_service.SignalService.evaluate", _fake_signal_evaluate)

    g1 = _make_group("g1")
    g2 = _make_group("g2")
    svc = SourceService()
    svc.create(g1.id, type="creator", platform="douyin", identifier="creator-a", display_name="A")
    src2 = svc.create(g2.id, type="creator", platform="douyin", identifier="creator-a", display_name="A")
    IngestService().run_group(g1.id, force=True)

    svc.delete(src2.id)

    with Session(get_engine()) as s:
        global_item = s.exec(select(GlobalContent)).one()
        group_links = s.exec(select(GroupContent).where(GroupContent.global_content_id == global_item.id)).all()
        global_count = len(s.exec(select(GlobalContent)).all())
    assert global_count == 1
    assert {link.group_id for link in group_links} == {g1.id}


def test_report_marks_group_content_analyzed(monkeypatch):
    adapter = FakeAdapter()
    monkeypatch.setattr("app.services.ingest_service.get_adapter", lambda platform: adapter)
    monkeypatch.setattr("app.services.signal_service.SignalService.evaluate", _fake_signal_evaluate)

    g1 = _make_group("g1")
    SourceService().create(g1.id, type="creator", platform="douyin", identifier="creator-a", display_name="A")
    IngestService().run_group(g1.id, force=True)

    svc = KnowledgeService()
    monkeypatch.setattr(svc.llm, "chat", lambda messages, *, config: "报告正文")
    result = svc.analyze_group(g1.id)

    assert result["report_id"] is not None
    with Session(get_engine()) as s:
        group_content = s.exec(select(GroupContent).where(GroupContent.group_id == g1.id)).one()
    assert group_content.analyzed_at is not None
