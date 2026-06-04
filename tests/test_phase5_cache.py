"""ContentCache：按 content_id 查找已有转录/评论/视频"""
from __future__ import annotations
import json
from pathlib import Path

import pytest

from app.settings import settings
from app.storage.cache import ContentCache


@pytest.fixture
def sandbox(tmp_path: Path, monkeypatch):
    data_dir = tmp_path / "data"
    research_dir = tmp_path / "research"
    data_dir.mkdir()
    research_dir.mkdir()
    monkeypatch.setattr(settings, "data_dir", data_dir)
    monkeypatch.setattr(settings, "research_dir", research_dir)
    yield tmp_path


def _touch(path: Path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_transcript_hit_from_data(sandbox: Path):
    _touch(sandbox / "data/g/src1/2026-01-01_ABC.txt", "转录正文")
    cache = ContentCache()
    assert cache.get_transcript("ABC") == "转录正文"


def test_transcript_hit_from_research(sandbox: Path):
    _touch(sandbox / "research/task_x/transcripts/DEF.txt", "研究转录")
    cache = ContentCache()
    assert cache.get_transcript("DEF") == "研究转录"


def test_transcript_miss(sandbox: Path):
    cache = ContentCache()
    assert cache.get_transcript("NOEXIST") is None


def test_transcript_data_wins_over_research(sandbox: Path):
    """data/ 订阅的结果优先于 research/ 攒的"""
    _touch(sandbox / "data/g/src1/2026-01-01_XYZ.txt", "订阅版")
    _touch(sandbox / "research/task_y/transcripts/XYZ.txt", "研究版")
    cache = ContentCache()
    assert cache.get_transcript("XYZ") == "订阅版"


def test_comments_hit_from_data(sandbox: Path):
    _touch(
        sandbox / "data/g/src1/2026-01-01_CID.comments.json",
        json.dumps([{"comment_id": "c1", "text": "好"}], ensure_ascii=False),
    )
    cache = ContentCache()
    got = cache.get_comments("CID")
    assert got and got[0]["comment_id"] == "c1"


def test_comments_miss(sandbox: Path):
    cache = ContentCache()
    assert cache.get_comments("NONE") is None


def test_comments_hit_from_research(sandbox: Path):
    _touch(
        sandbox / "research/task_z/comments/CID2.json",
        json.dumps([{"comment_id": "r1"}]),
    )
    cache = ContentCache()
    got = cache.get_comments("CID2")
    assert got and got[0]["comment_id"] == "r1"


def test_video_path_requires_sufficient_size(sandbox: Path):
    """损坏/过小的视频文件不应被复用"""
    tiny = sandbox / "data/g/src1/2026-01-01_VID1.mp4"
    tiny.parent.mkdir(parents=True)
    tiny.write_bytes(b"x" * 100)  # 太小
    assert ContentCache().get_video_path("VID1") is None

    ok = sandbox / "data/g/src1/2026-01-01_VID2.mp4"
    ok.write_bytes(b"x" * 20000)  # > 10000
    assert ContentCache().get_video_path("VID2") == ok


def test_metadata_lookup_skips_comments_json(sandbox: Path):
    """get_metadata 不能把 *.comments.json 误当成元数据"""
    _touch(
        sandbox / "data/g/src/2026-01-01_M.json",
        json.dumps({"title": "标题"}, ensure_ascii=False),
    )
    _touch(
        sandbox / "data/g/src/2026-01-01_M.comments.json",
        json.dumps([{"comment_id": "x"}]),
    )
    got = ContentCache().get_metadata("M")
    assert got and got["title"] == "标题"
