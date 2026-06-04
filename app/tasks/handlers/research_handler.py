"""按需研究 handler"""
from __future__ import annotations
from app.db.schema import Task
from app.models.group import TaskKind
from app.services.research_service import ResearchService
from app.tasks.registry import register_handler
from app.tasks.runner import TaskContext


@register_handler(TaskKind.RESEARCH)
def handle_research(task: Task, ctx: TaskContext) -> dict:
    """
    params:
      {
        "question": str,
        "platforms": list[str]?,
        "days": int?,
        "search_limit": int?,
        "comment_top_n": int?,
      }
    """
    params = task.params or {}
    question = (params.get("question") or "").strip()
    if not question:
        raise ValueError("question is required")

    svc = ResearchService()
    return svc.run(
        question,
        group_id=task.group_id,
        task_id=task.id,
        platforms=params.get("platforms"),
        days=params.get("days", 7),
        search_limit=params.get("search_limit"),
        comment_top_n=params.get("comment_top_n"),
        progress_cb=ctx.progress,
        log_cb=lambda m: ctx.log(m),
        is_cancelled=ctx.is_cancelled,
    )
