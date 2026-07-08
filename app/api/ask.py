from __future__ import annotations
from fastapi import APIRouter, HTTPException
from sqlmodel import select

from app.api.schemas import (
    AskConversationBrief,
    AskConversationDetail,
    AskMessageResp,
    GroupAskReq,
    GroupAskResp,
)
from app.db.engine import get_session
from app.db.repos import GroupRepo
from app.db.schema import AskConversation, AskMessage
from app.services.knowledge_service import KnowledgeService


router = APIRouter(prefix="/api/groups/{group_id}/ask", tags=["ask"])


def _question_text(req: GroupAskReq) -> str:
    question = req.question.strip()
    if not question:
        raise HTTPException(400, "question is required")
    return question


def _ensure_group_exists(group_id: int) -> None:
    with get_session() as s:
        if not GroupRepo(s).get(group_id):
            raise HTTPException(404, "group not found")


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


def _conversation_detail(conv: AskConversation, messages: list[AskMessage]) -> AskConversationDetail:
    return AskConversationDetail(
        id=conv.id or 0,
        group_id=conv.group_id,
        title=conv.title,
        messages=[_message_resp(m) for m in messages],
        created_at=conv.created_at,
        updated_at=conv.updated_at,
    )


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


@router.post("", response_model=GroupAskResp)
def ask_group(group_id: int, req: GroupAskReq):
    """基于专题内已有转录、评论和观点信号回答，不触发外部搜索。"""
    return _ask_internal(group_id, req)


@router.get("/conversations", response_model=list[AskConversationBrief])
def list_conversations(group_id: int):
    with get_session() as s:
        if not GroupRepo(s).get(group_id):
            raise HTTPException(404, "group not found")
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
def create_conversation(group_id: int, req: GroupAskReq):
    question = _question_text(req)
    _ensure_group_exists(group_id)
    answer = _ask_internal(group_id, req)
    title = question[:80]
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
        messages = s.exec(
            select(AskMessage)
            .where(AskMessage.conversation_id == conv.id)
            .order_by(AskMessage.created_at)
        ).all()
        return _conversation_detail(conv, messages)


@router.get("/conversations/{conversation_id}", response_model=AskConversationDetail)
def get_conversation(group_id: int, conversation_id: int):
    with get_session() as s:
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
def continue_conversation(group_id: int, conversation_id: int, req: GroupAskReq):
    question = _question_text(req)
    _ensure_conversation_in_group(group_id, conversation_id)
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
        messages = s.exec(
            select(AskMessage)
            .where(AskMessage.conversation_id == conversation_id)
            .order_by(AskMessage.created_at)
        ).all()
        return _conversation_detail(conv, messages)
