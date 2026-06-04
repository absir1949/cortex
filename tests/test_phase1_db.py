"""Phase 1 冒烟测试：migration + repos CRUD 能跑通"""
from __future__ import annotations
from sqlmodel import Session

from app.db.engine import get_engine
from app.db.schema import KnowledgeGroup, Source, Task, Report
from app.db.repos import GroupRepo, SourceRepo, ConfigRepo, TaskRepo, ReportRepo, AnalyzedRepo
from app.models.group import SourceType, TaskStatus, TaskKind


def _session() -> Session:
    return Session(get_engine())


def test_migration_creates_schema_from_empty():
    """从零应用 migration，SchemaVersion 正确记录"""
    from app.db.migrations import run_migrations, current_version

    applied = run_migrations(verbose=False)
    # 首次跑应有至少 v1 被应用（或通过 create_all 预建后版本号已是 1）
    with _session() as s:
        # 要么本次 applied，要么之前已 applied
        assert current_version(s) >= 1 or applied == [1]


def test_group_crud():
    with _session() as s:
        repo = GroupRepo(s)
        g = repo.create(KnowledgeGroup(name="测试组", slug="test", description="冒烟"))
        assert g.id is not None

        got = repo.get_by_slug("test")
        assert got is not None
        assert got.name == "测试组"

        got.description = "已更新"
        repo.update(got)
        assert repo.get(got.id).description == "已更新"

        assert repo.source_count(g.id) == 0

        assert len(repo.list_all()) == 1
        repo.delete(g.id)
        assert repo.list_all() == []


def test_source_crud_and_last_check():
    with _session() as s:
        group = GroupRepo(s).create(KnowledgeGroup(name="组", slug="g1"))
        src_repo = SourceRepo(s)

        src = src_repo.create(Source(
            group_id=group.id,
            type=SourceType.CREATOR.value,
            platform="douyin",
            identifier="MS4wLjAB_test",
            display_name="测试博主",
            directory="g1/creator-test",
        ))
        assert src.id is not None

        assert src_repo.find(group.id, "douyin", "MS4wLjAB_test") is not None
        assert len(src_repo.list_by_group(group.id)) == 1

        src_repo.mark_checked(src.id, ok=True)
        refreshed = src_repo.get(src.id)
        assert refreshed.last_check is not None
        assert refreshed.last_error is None

        src_repo.mark_checked(src.id, ok=False, error="boom")
        assert src_repo.get(src.id).last_error == "boom"


def test_config_kv_roundtrip():
    with _session() as s:
        repo = ConfigRepo(s)
        repo.set("llm_model", "deepseek-chat")
        repo.set("comment_top_n", 30)
        repo.set("llm_prompt", {"analysis": "some-text", "version": 2})

        assert repo.get("llm_model") == "deepseek-chat"
        assert repo.get("comment_top_n") == 30
        assert repo.get("llm_prompt") == {"analysis": "some-text", "version": 2}

        all_items = repo.get_all()
        assert set(all_items.keys()) == {"llm_model", "comment_top_n", "llm_prompt"}

        repo.delete("llm_model")
        assert repo.get("llm_model") is None


def test_task_lifecycle():
    with _session() as s:
        repo = TaskRepo(s)
        t = repo.create(Task(
            id="task-1",
            kind=TaskKind.RESEARCH.value,
            status=TaskStatus.PENDING.value,
            params={"question": "x"},
        ))
        assert t.id == "task-1"

        repo.set_status("task-1", TaskStatus.RUNNING)
        assert repo.get("task-1").started_at is not None
        assert repo.get("task-1").finished_at is None

        repo.update_progress("task-1", {"stage": "downloading", "done": 1, "total": 5})
        assert repo.get("task-1").progress["stage"] == "downloading"

        repo.append_log("task-1", {"ts": "2026-04-24T10:00:00", "level": "info", "text": "hi"})
        repo.append_log("task-1", {"ts": "2026-04-24T10:00:01", "level": "info", "text": "hi2"})
        assert len(repo.get("task-1").logs) == 2

        repo.set_status("task-1", TaskStatus.SUCCEEDED, result={"report_id": 42})
        t = repo.get("task-1")
        assert t.status == TaskStatus.SUCCEEDED.value
        assert t.finished_at is not None
        assert t.result["report_id"] == 42

        assert len(repo.list(kind=TaskKind.RESEARCH.value)) == 1
        assert len(repo.list(status=TaskStatus.SUCCEEDED.value)) == 1
        assert len(repo.list(status=TaskStatus.RUNNING.value)) == 0


def test_task_reset_running_to_failed():
    with _session() as s:
        repo = TaskRepo(s)
        repo.create(Task(id="t1", kind=TaskKind.INGEST.value, status=TaskStatus.RUNNING.value))
        repo.create(Task(id="t2", kind=TaskKind.INGEST.value, status=TaskStatus.SUCCEEDED.value))

        n = repo.reset_running_to_failed("test")
        assert n == 1
        assert repo.get("t1").status == TaskStatus.FAILED.value
        assert repo.get("t2").status == TaskStatus.SUCCEEDED.value


def test_report_list_by_group():
    with _session() as s:
        group = GroupRepo(s).create(KnowledgeGroup(name="g", slug="g"))
        repo = ReportRepo(s)
        repo.create(Report(
            group_id=group.id,
            kind="scheduled",
            title="首期",
            content_md_path="/tmp/1.md",
        ))
        repo.create(Report(
            group_id=group.id,
            kind="research",
            title="二期",
            content_md_path="/tmp/2.md",
        ))
        lst = repo.list_by_group(group.id)
        assert len(lst) == 2


def test_analyzed_content_incremental():
    with _session() as s:
        group = GroupRepo(s).create(KnowledgeGroup(name="g", slug="g"))
        src = SourceRepo(s).create(Source(
            group_id=group.id,
            type=SourceType.CREATOR.value,
            platform="douyin",
            identifier="x",
            display_name="x",
            directory="g/x",
        ))

        repo = AnalyzedRepo(s)
        assert not repo.is_analyzed(src.id, "v1")
        repo.mark(src.id, "v1")
        assert repo.is_analyzed(src.id, "v1")

        repo.mark(src.id, "v1")  # 幂等
        repo.mark_many(src.id, ["v2", "v3", "v1"])  # v1 重复
        ids = repo.get_analyzed_ids(src.id)
        assert ids == {"v1", "v2", "v3"}
