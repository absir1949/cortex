from __future__ import annotations
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import select

from app.api.schemas import (
    AskConversationBrief,
    AskConversationDetail,
    AskMessageResp,
    GroupAskReq,
    GroupAskResp,
)
from app.auth import get_current_user
from app.authz import assert_group_owner
from app.db.engine import get_session
from app.db.schema import AskConversation, AskMessage
from app.models.group import TaskKind
from app.services.knowledge_service import KnowledgeService
from app.tasks import get_runner


router = APIRouter(prefix="/api/groups/{group_id}/ask", tags=["ask"])


def _question_text(req: GroupAskReq) -> str:
    question = req.question.strip()
    if not question:
        raise HTTPException(400, "question is required")
    return question


def _validate_sources(req: GroupAskReq) -> None:
    if not req.use_internal and not req.use_external:
        raise HTTPException(400, "at least one evidence source is required")
    if len(req.platforms) > 5:
        raise HTTPException(400, "too many platforms")


def _ensure_conversation_in_group(group_id: int, conversation_id: int) -> None:
    with get_session() as s:
        conv = s.get(AskConversation, conversation_id)
        if not conv or conv.group_id != group_id:
            raise HTTPException(404, "conversation not found")


def _evidence_count(msg: AskMessage) -> int:
    return len(msg.evidence or []) if msg.role == "assistant" else 0


def _message_resp(msg: AskMessage) -> AskMessageResp:
    return AskMessageResp(
        id=msg.id or 0,
        role=msg.role,
        content=msg.content,
        evidence=msg.evidence or [],
        created_at=msg.created_at,
    )


def _conversation_messages(session, conversation_id: int) -> list[AskMessage]:
    return session.exec(
        select(AskMessage)
        .where(AskMessage.conversation_id == conversation_id)
        .order_by(AskMessage.created_at)
    ).all()


def _conversation_detail(conv: AskConversation, messages: list[AskMessage]) -> AskConversationDetail:
    return AskConversationDetail(
        id=conv.id or 0,
        group_id=conv.group_id,
        title=conv.title,
        messages=[_message_resp(m) for m in messages],
        created_at=conv.created_at,
        updated_at=conv.updated_at,
    )


def _external_task_evidence(task_id: str, status: str = "running") -> list[dict]:
    return [{
        "kind": "external_search_task",
        "task_id": task_id,
        "status": status,
        "author": "听风",
        "title": "外部资料搜索",
        "snippet": "正在搜索外部来源并整理证据。",
    }]


def _ask_internal(group_id: int, req: GroupAskReq) -> dict:
    question = _question_text(req)
    try:
        return KnowledgeService().answer_group_question(
            group_id,
            question,
            days=req.days,
            limit=req.limit,
        )
    except ValueError as e:
        raise HTTPException(404, str(e))
    except RuntimeError as e:
        raise HTTPException(502, str(e))


def _enqueue_external_ask(
    *,
    group_id: int,
    req: GroupAskReq,
    conversation_id: int,
    placeholder_id: int,
) -> str:
    params = {
        "question": _question_text(req),
        "platforms": req.platforms,
        "days": req.external_days,
        "search_limit": req.external_limit,
        "comment_top_n": req.comment_top_n,
        "ask_conversation_id": conversation_id,
        "ask_message_id": placeholder_id,
        "use_internal": req.use_internal,
        "internal_days": req.days,
        "internal_limit": req.limit,
    }
    return get_runner().enqueue(TaskKind.RESEARCH, params=params, group_id=group_id)


@router.post("", response_model=GroupAskResp)
def ask_group(group_id: int, req: GroupAskReq, current_user: dict = Depends(get_current_user)):
    """基于专题内已有材料即时回答。外部搜索需要创建对话承载异步结果。"""
    _validate_sources(req)
    if req.use_external:
        raise HTTPException(400, "external search must be created as a conversation")
    if not req.use_internal:
        raise HTTPException(400, "internal source is disabled")
    with get_session() as s:
        assert_group_owner(s, group_id, current_user)
    return _ask_internal(group_id, req)


@router.get("/conversations", response_model=list[AskConversationBrief])
def list_conversations(group_id: int, current_user: dict = Depends(get_current_user)):
    with get_session() as s:
        assert_group_owner(s, group_id, current_user)
        conversations = s.exec(
            select(AskConversation)
            .where(AskConversation.group_id == group_id)
            .order_by(AskConversation.updated_at.desc())
            .limit(50)
        ).all()
        out: list[AskConversationBrief] = []
        for conv in conversations:
            messages = s.exec(
                select(AskMessage)
                .where(AskMessage.conversation_id == conv.id)
                .order_by(AskMessage.created_at)
            ).all()
            latest_answer = next((m.content for m in reversed(messages) if m.role == "assistant"), "")
            evidence_count = next((_evidence_count(m) for m in reversed(messages) if m.role == "assistant"), 0)
            out.append(AskConversationBrief(
                id=conv.id or 0,
                group_id=conv.group_id,
                title=conv.title,
                latest_answer=latest_answer,
                evidence_count=evidence_count,
                message_count=len(messages),
                created_at=conv.created_at,
                updated_at=conv.updated_at,
            ))
        return out


@router.post("/conversations", response_model=AskConversationDetail, status_code=201)
def create_conversation(
    group_id: int,
    req: GroupAskReq,
    current_user: dict = Depends(get_current_user),
):
    _validate_sources(req)
    question = _question_text(req)
    with get_session() as s:
        assert_group_owner(s, group_id, current_user)
    title = question[:80]

    if req.use_external:
        with get_session() as s:
            conv = AskConversation(group_id=group_id, title=title)
            s.add(conv)
            s.commit()
            s.refresh(conv)
            user_msg = AskMessage(conversation_id=conv.id, role="user", content=question)
            placeholder = AskMessage(
                conversation_id=conv.id,
                role="assistant",
                content="正在搜索外部资料，完成后会在这条对话里给出答案。",
                evidence=[],
            )
            conv.updated_at = datetime.now().isoformat()
            s.add(conv)
            s.add(user_msg)
            s.add(placeholder)
            s.commit()
            s.refresh(conv)
            s.refresh(placeholder)
            task_id = _enqueue_external_ask(
                group_id=group_id,
                req=req,
                conversation_id=conv.id or 0,
                placeholder_id=placeholder.id or 0,
            )
            placeholder.evidence = _external_task_evidence(task_id)
            s.add(placeholder)
            s.commit()
            messages = _conversation_messages(s, conv.id or 0)
            return _conversation_detail(conv, messages)

    answer = _ask_internal(group_id, req)
    with get_session() as s:
        conv = AskConversation(group_id=group_id, title=title)
        s.add(conv)
        s.commit()
        s.refresh(conv)
        user_msg = AskMessage(conversation_id=conv.id, role="user", content=question)
        assistant_msg = AskMessage(
            conversation_id=conv.id,
            role="assistant",
            content=answer["answer"],
            evidence=answer.get("evidence", []),
        )
        s.add(user_msg)
        s.add(assistant_msg)
        s.commit()
        messages = _conversation_messages(s, conv.id or 0)
        return _conversation_detail(conv, messages)


@router.get("/conversations/{conversation_id}", response_model=AskConversationDetail)
def get_conversation(
    group_id: int,
    conversation_id: int,
    current_user: dict = Depends(get_current_user),
):
    with get_session() as s:
        assert_group_owner(s, group_id, current_user)
        conv = s.get(AskConversation, conversation_id)
        if not conv or conv.group_id != group_id:
            raise HTTPException(404, "conversation not found")
        messages = s.exec(
            select(AskMessage)
            .where(AskMessage.conversation_id == conversation_id)
            .order_by(AskMessage.created_at)
        ).all()
        return _conversation_detail(conv, messages)


@router.post("/conversations/{conversation_id}/messages", response_model=AskConversationDetail)
def continue_conversation(
    group_id: int,
    conversation_id: int,
    req: GroupAskReq,
    current_user: dict = Depends(get_current_user),
):
    _validate_sources(req)
    question = _question_text(req)
    with get_session() as s:
        assert_group_owner(s, group_id, current_user)
    _ensure_conversation_in_group(group_id, conversation_id)

    if req.use_external:
        with get_session() as s:
            conv = s.get(AskConversation, conversation_id)
            if not conv or conv.group_id != group_id:
                raise HTTPException(404, "conversation not found")
            user_msg = AskMessage(conversation_id=conv.id, role="user", content=question)
            placeholder = AskMessage(
                conversation_id=conv.id,
                role="assistant",
                content="正在搜索外部资料，完成后会在这条对话里给出答案。",
                evidence=[],
            )
            conv.updated_at = datetime.now().isoformat()
            s.add(conv)
            s.add(user_msg)
            s.add(placeholder)
            s.commit()
            s.refresh(conv)
            s.refresh(placeholder)
            task_id = _enqueue_external_ask(
                group_id=group_id,
                req=req,
                conversation_id=conversation_id,
                placeholder_id=placeholder.id or 0,
            )
            placeholder.evidence = _external_task_evidence(task_id)
            s.add(placeholder)
            s.commit()
            messages = _conversation_messages(s, conversation_id)
            return _conversation_detail(conv, messages)

    answer = _ask_internal(group_id, req)
    with get_session() as s:
        conv = s.get(AskConversation, conversation_id)
        if not conv or conv.group_id != group_id:
            raise HTTPException(404, "conversation not found")
        user_msg = AskMessage(conversation_id=conv.id, role="user", content=question)
        assistant_msg = AskMessage(
            conversation_id=conv.id,
            role="assistant",
            content=answer["answer"],
            evidence=answer.get("evidence", []),
        )
        from datetime import datetime
        conv.updated_at = datetime.now().isoformat()
        s.add(conv)
        s.add(user_msg)
        s.add(assistant_msg)
        s.commit()
        s.refresh(conv)
        messages = _conversation_messages(s, conversation_id)
        return _conversation_detail(conv, messages)
