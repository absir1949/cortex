"""LLM token 计量与分摊。

设计原则：
- LLMUsageEvent 记录真实 provider 调用成本，只算一次。
- LLMUsageAllocation 记录受益专题/用户的分摊份额，用于后台看用户、博主维度。
- provider 未返回 usage 时只记 missing + 估算值，不混入真实 token 总量。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from sqlalchemy import func
from sqlmodel import Session, select

from app.db.engine import get_session
from app.db.schema import (
    AskConversation,
    Creator,
    GlobalContent,
    GroupContent,
    IngestTarget,
    KnowledgeGroup,
    LLMUsageAllocation,
    LLMUsageEvent,
    Source,
    SourceContent,
    Task,
    User,
)
from app.llm.base import LLMConfig, LLMMessage, LLMTokenUsage, LLMUsageContext
from app.runtime_context import current_task_id


@dataclass
class _EventContext:
    task_id: Optional[str] = None
    user_id: Optional[int] = None
    group_id: Optional[int] = None
    source_id: Optional[int] = None
    creator_id: Optional[int] = None
    global_content_id: Optional[int] = None
    ingest_target_id: Optional[int] = None
    conversation_id: Optional[int] = None


@dataclass(frozen=True)
class _AllocationTarget:
    user_id: Optional[int]
    group_id: Optional[int]
    source_id: Optional[int]
    creator_id: Optional[int]
    global_content_id: Optional[int]
    ingest_target_id: Optional[int]


def record_llm_usage(
    *,
    config: LLMConfig,
    messages: list[LLMMessage],
    response_text: str = "",
    usage_context: Optional[LLMUsageContext] = None,
    token_usage: Optional[LLMTokenUsage] = None,
    provider: str = "openai_compat",
    error: Optional[BaseException | str] = None,
) -> Optional[int]:
    """记录一次 LLM 调用并生成分摊行。

    该函数不能影响主业务：计量本身失败时吞掉异常，返回 None。
    """
    try:
        with get_session() as session:
            ctx = _normalize_context(session, usage_context)
            request_chars = sum(len(m.content or "") for m in messages)
            response_chars = len(response_text or "")
            prompt_tokens = _token_value(token_usage.prompt_tokens if token_usage else None)
            completion_tokens = _token_value(token_usage.completion_tokens if token_usage else None)
            total_tokens = _token_value(token_usage.total_tokens if token_usage else None)
            if not total_tokens and (prompt_tokens or completion_tokens):
                total_tokens = prompt_tokens + completion_tokens
            cached_tokens = _token_value(token_usage.cached_tokens if token_usage else None)
            reasoning_tokens = _token_value(token_usage.reasoning_tokens if token_usage else None)
            has_real_usage = bool(token_usage and any(
                value is not None
                for value in (token_usage.prompt_tokens, token_usage.completion_tokens, token_usage.total_tokens)
            ))
            status = "failed" if error else ("ok" if has_real_usage else "missing")

            event = LLMUsageEvent(
                provider=provider,
                base_url=_safe_base_url(config.base_url),
                model=config.model or "",
                operation=(usage_context.operation if usage_context else "unknown") or "unknown",
                metering_status=status,
                task_id=ctx.task_id,
                user_id=ctx.user_id,
                group_id=ctx.group_id,
                source_id=ctx.source_id,
                creator_id=ctx.creator_id,
                global_content_id=ctx.global_content_id,
                ingest_target_id=ctx.ingest_target_id,
                conversation_id=ctx.conversation_id,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                cached_tokens=cached_tokens,
                reasoning_tokens=reasoning_tokens,
                estimated_total_tokens=_estimate_tokens(request_chars + response_chars),
                request_chars=request_chars,
                response_chars=response_chars,
                error=_error_text(error),
            )
            session.add(event)
            session.commit()
            session.refresh(event)
            if event.id is None:
                return None

            targets = _allocation_targets(session, ctx)
            _insert_allocations(session, event, targets)
            return int(event.id)
    except Exception:
        return None


def _normalize_context(session: Session, usage_context: Optional[LLMUsageContext]) -> _EventContext:
    ctx = _EventContext()
    if usage_context:
        ctx.task_id = usage_context.task_id
        ctx.user_id = _existing_id(session, User, usage_context.user_id)
        ctx.group_id = _existing_id(session, KnowledgeGroup, usage_context.group_id)
        ctx.source_id = _existing_id(session, Source, usage_context.source_id)
        ctx.creator_id = _existing_id(session, Creator, usage_context.creator_id)
        ctx.global_content_id = _existing_id(session, GlobalContent, usage_context.global_content_id)
        ctx.ingest_target_id = _existing_id(session, IngestTarget, usage_context.ingest_target_id)
        ctx.conversation_id = _existing_id(session, AskConversation, usage_context.conversation_id)

    task_id = ctx.task_id or current_task_id()
    if task_id and session.get(Task, task_id):
        ctx.task_id = task_id
    else:
        ctx.task_id = None

    if ctx.source_id:
        source = session.get(Source, ctx.source_id)
        if source:
            ctx.group_id = ctx.group_id or source.group_id
            ctx.creator_id = ctx.creator_id or source.creator_id
    if ctx.global_content_id:
        global_item = session.get(GlobalContent, ctx.global_content_id)
        if global_item:
            ctx.creator_id = ctx.creator_id or global_item.creator_id
    if ctx.conversation_id:
        conv = session.get(AskConversation, ctx.conversation_id)
        if conv:
            ctx.group_id = ctx.group_id or conv.group_id
    if ctx.group_id:
        group = session.get(KnowledgeGroup, ctx.group_id)
        if group:
            ctx.user_id = ctx.user_id or group.owner_id
    return ctx


def _allocation_targets(session: Session, ctx: _EventContext) -> list[_AllocationTarget]:
    if ctx.global_content_id:
        targets = _targets_for_global_content(session, ctx)
        if targets:
            return targets
    if ctx.ingest_target_id:
        targets = _targets_for_ingest_target(session, ctx)
        if targets:
            return targets
    if ctx.source_id:
        target = _target_for_source(session, ctx.source_id, ctx)
        if target:
            return [target]
    if ctx.group_id:
        target = _target_for_group(session, ctx.group_id, ctx)
        if target:
            return [target]
    if ctx.user_id:
        return [_AllocationTarget(
            user_id=ctx.user_id,
            group_id=None,
            source_id=None,
            creator_id=ctx.creator_id,
            global_content_id=ctx.global_content_id,
            ingest_target_id=ctx.ingest_target_id,
        )]
    return []


def _targets_for_global_content(session: Session, ctx: _EventContext) -> list[_AllocationTarget]:
    rows = session.exec(
        select(GroupContent, KnowledgeGroup)
        .join(KnowledgeGroup, KnowledgeGroup.id == GroupContent.group_id)
        .where(GroupContent.global_content_id == ctx.global_content_id)
        .order_by(GroupContent.group_id)
    ).all()
    targets: list[_AllocationTarget] = []
    seen_groups: set[int] = set()
    for group_content, group in rows:
        if group.id is None or group.id in seen_groups:
            continue
        seen_groups.add(int(group.id))
        targets.append(_AllocationTarget(
            user_id=group.owner_id,
            group_id=group_content.group_id,
            source_id=_source_id_for_group_content(session, group_content.group_id, ctx.global_content_id),
            creator_id=ctx.creator_id,
            global_content_id=ctx.global_content_id,
            ingest_target_id=ctx.ingest_target_id,
        ))
    return targets


def _targets_for_ingest_target(session: Session, ctx: _EventContext) -> list[_AllocationTarget]:
    target = session.get(IngestTarget, ctx.ingest_target_id)
    if not target:
        return []
    rows = session.exec(
        select(Source, KnowledgeGroup)
        .join(KnowledgeGroup, KnowledgeGroup.id == Source.group_id)
        .where(Source.platform == target.platform)
        .where(Source.type == target.kind)
        .where(func.trim(Source.identifier) == target.target_key)
        .where(Source.enabled == True)  # noqa: E712
        .order_by(Source.group_id, Source.id)
    ).all()
    out: list[_AllocationTarget] = []
    seen_groups: set[int] = set()
    for source, group in rows:
        if group.id is None or group.id in seen_groups:
            continue
        seen_groups.add(int(group.id))
        out.append(_AllocationTarget(
            user_id=group.owner_id,
            group_id=source.group_id,
            source_id=source.id,
            creator_id=source.creator_id or ctx.creator_id,
            global_content_id=ctx.global_content_id,
            ingest_target_id=ctx.ingest_target_id,
        ))
    return out


def _target_for_source(session: Session, source_id: int, ctx: _EventContext) -> Optional[_AllocationTarget]:
    source = session.get(Source, source_id)
    if not source:
        return None
    group = session.get(KnowledgeGroup, source.group_id)
    return _AllocationTarget(
        user_id=group.owner_id if group else ctx.user_id,
        group_id=source.group_id,
        source_id=source.id,
        creator_id=source.creator_id or ctx.creator_id,
        global_content_id=ctx.global_content_id,
        ingest_target_id=ctx.ingest_target_id,
    )


def _target_for_group(session: Session, group_id: int, ctx: _EventContext) -> Optional[_AllocationTarget]:
    group = session.get(KnowledgeGroup, group_id)
    if not group:
        return None
    return _AllocationTarget(
        user_id=group.owner_id or ctx.user_id,
        group_id=group.id,
        source_id=ctx.source_id,
        creator_id=ctx.creator_id,
        global_content_id=ctx.global_content_id,
        ingest_target_id=ctx.ingest_target_id,
    )


def _source_id_for_group_content(session: Session, group_id: int, global_content_id: Optional[int]) -> Optional[int]:
    if not global_content_id:
        return None
    source_id = session.exec(
        select(Source.id)
        .join(SourceContent, SourceContent.source_id == Source.id)
        .where(Source.group_id == group_id)
        .where(SourceContent.global_content_id == global_content_id)
        .order_by(Source.id)
        .limit(1)
    ).first()
    return int(source_id) if source_id is not None else None


def _insert_allocations(session: Session, event: LLMUsageEvent, targets: list[_AllocationTarget]) -> None:
    if not targets or event.id is None:
        return
    total = len(targets)
    kind = "shared" if total > 1 else "direct"
    for idx, target in enumerate(targets):
        session.add(LLMUsageAllocation(
            usage_event_id=int(event.id),
            allocation_kind=kind,
            allocation_ratio=1 / total,
            user_id=target.user_id,
            group_id=target.group_id,
            source_id=target.source_id,
            creator_id=target.creator_id,
            global_content_id=target.global_content_id,
            ingest_target_id=target.ingest_target_id,
            allocated_prompt_tokens=_split_tokens(event.prompt_tokens, total, idx),
            allocated_completion_tokens=_split_tokens(event.completion_tokens, total, idx),
            allocated_total_tokens=_split_tokens(event.total_tokens, total, idx),
            allocated_cached_tokens=_split_tokens(event.cached_tokens, total, idx),
            allocated_reasoning_tokens=_split_tokens(event.reasoning_tokens, total, idx),
            allocated_estimated_total_tokens=_split_tokens(event.estimated_total_tokens, total, idx),
        ))
    session.commit()


def _existing_id(session: Session, model, value: Optional[int]) -> Optional[int]:
    if value is None:
        return None
    try:
        int_value = int(value)
    except (TypeError, ValueError):
        return None
    return int_value if session.get(model, int_value) else None


def _token_value(value: Optional[int]) -> int:
    if value is None:
        return 0
    try:
        return max(int(value), 0)
    except (TypeError, ValueError):
        return 0


def _split_tokens(value: int, total: int, idx: int) -> int:
    if total <= 0:
        return 0
    base = int(value or 0) // total
    remainder = int(value or 0) % total
    return base + (1 if idx < remainder else 0)


def _estimate_tokens(char_count: int) -> int:
    if char_count <= 0:
        return 0
    return max(1, (char_count + 3) // 4)


def _safe_base_url(base_url: str) -> str:
    return (base_url or "").split("?", 1)[0][:255]


def _error_text(error: Optional[BaseException | str]) -> Optional[str]:
    if not error:
        return None
    return str(error)[:1000]
