"""问听风外部搜索 handler"""
from __future__ import annotations
from datetime import datetime

from app.db.engine import get_session
from app.db.schema import Task
from app.models.group import TaskKind
from app.db.schema import AskConversation, AskMessage
from app.services.knowledge_service import KnowledgeService
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

    conversation_id = params.get("ask_conversation_id")
    message_id = params.get("ask_message_id")
    internal_evidence: list[dict] = []
    if params.get("use_internal") and task.group_id:
        internal_evidence = KnowledgeService().collect_group_evidence(
            task.group_id,
            question=question,
            days=int(params.get("internal_days") or 30),
            limit=int(params.get("internal_limit") or 12),
        )

    svc = ResearchService()
    try:
        result = svc.run(
            question,
            group_id=task.group_id,
            task_id=task.id,
            platforms=params.get("platforms"),
            days=params.get("days", 7),
            search_limit=params.get("search_limit"),
            comment_top_n=params.get("comment_top_n"),
            internal_evidence=internal_evidence,
            progress_cb=ctx.progress,
            log_cb=lambda m: ctx.log(m),
            is_cancelled=ctx.is_cancelled,
        )
    except Exception as exc:
        if conversation_id and message_id:
            _update_ask_message(
                int(conversation_id),
                int(message_id),
                content=f"外部搜索失败：{exc}",
                evidence=[{
                    "kind": "external_search_task",
                    "task_id": task.id,
                    "status": "failed",
                    "author": "听风",
                    "title": "外部资料搜索",
                    "snippet": str(exc),
                }],
            )
        raise

    if conversation_id and message_id:
        _update_ask_message(
            int(conversation_id),
            int(message_id),
            content=result.get("answer", ""),
            evidence=result.get("evidence", []),
        )
    return result


def _update_ask_message(conversation_id: int, message_id: int, *, content: str, evidence: list[dict]) -> None:
    with get_session() as session:
        conv = session.get(AskConversation, conversation_id)
        msg = session.get(AskMessage, message_id)
        if not conv or not msg or msg.conversation_id != conversation_id:
            return
        msg.content = content
        msg.evidence = evidence
        conv.updated_at = datetime.now().isoformat()
        session.add(conv)
        session.add(msg)
        session.commit()
