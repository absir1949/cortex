from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import case, func
from sqlmodel import Session, select

from app.auth import get_current_user
from app.db.engine import get_session
from app.db.repos import IngestTargetRepo, UserRepo
from app.db.schema import (
    Creator,
    GlobalContent,
    GroupContent,
    IngestTarget,
    KnowledgeGroup,
    LLMUsageAllocation,
    LLMUsageEvent,
    Report,
    Signal,
    Source,
    Task,
    User,
)
from app.models.group import TaskKind
from app.tasks import get_runner


router = APIRouter(prefix="/api/admin", tags=["admin"])


class AdminStats(BaseModel):
    users: int = 0
    active_users: int = 0
    groups: int = 0
    enabled_groups: int = 0
    sources: int = 0
    active_sources: int = 0
    failed_sources: int = 0
    ingest_targets: int = 0
    active_targets: int = 0
    targets_with_error: int = 0
    global_content: int = 0
    group_content: int = 0
    recent_content_7d: int = 0
    signals: int = 0
    new_signals: int = 0
    reports: int = 0
    tasks: int = 0
    running_tasks: int = 0
    failed_tasks: int = 0
    llm_actual_tokens_30d: int = 0
    llm_allocated_tokens_30d: int = 0
    llm_missing_events_30d: int = 0


class AdminUserRow(BaseModel):
    id: int
    phone: str
    nickname: str = ""
    role: str
    plan: str
    expires_at: Optional[str] = None
    group_count: int = 0
    source_count: int = 0
    active_source_count: int = 0
    failed_source_count: int = 0
    content_count: int = 0
    signal_count: int = 0
    new_signal_count: int = 0
    report_count: int = 0
    task_count: int = 0
    last_activity_at: Optional[str] = None
    created_at: str


class AdminTargetRow(BaseModel):
    id: int
    platform: str
    kind: str
    target_key: str
    enabled: bool
    admin_paused: bool = False
    subscriber_count: int = 0
    group_count: int = 0
    interval_hours: int
    days: int
    content_limit: int
    comment_top_n: int
    last_check: Optional[str] = None
    last_error: Optional[str] = None
    running_task_id: Optional[str] = None
    locked_at: Optional[str] = None
    updated_at: Optional[str] = None


class AdminTaskRow(BaseModel):
    id: str
    kind: str
    status: str
    group_id: Optional[int] = None
    group_name: str = ""
    source_id: Optional[int] = None
    source_name: str = ""
    owner_phone: str = ""
    created_at: str
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    error: Optional[str] = None


class AdminUsageOperationRow(BaseModel):
    operation: str
    model: str = ""
    call_count: int = 0
    actual_prompt_tokens: int = 0
    actual_completion_tokens: int = 0
    actual_total_tokens: int = 0
    cached_tokens: int = 0
    reasoning_tokens: int = 0
    missing_events: int = 0
    failed_events: int = 0


class AdminUsageUserRow(BaseModel):
    user_id: Optional[int] = None
    phone: str = ""
    nickname: str = ""
    allocated_total_tokens: int = 0
    allocated_estimated_tokens: int = 0
    call_count: int = 0
    group_count: int = 0
    source_count: int = 0


class AdminUsageCreatorRow(BaseModel):
    creator_id: Optional[int] = None
    creator_name: str = ""
    actual_total_tokens: int = 0
    allocated_total_tokens: int = 0
    allocated_estimated_tokens: int = 0
    call_count: int = 0
    user_count: int = 0


class AdminUsageSummary(BaseModel):
    actual_total_tokens_7d: int = 0
    actual_total_tokens_30d: int = 0
    allocated_total_tokens_30d: int = 0
    allocated_estimated_tokens_30d: int = 0
    missing_events_30d: int = 0
    failed_events_30d: int = 0
    by_operation: list[AdminUsageOperationRow] = Field(default_factory=list)
    by_user: list[AdminUsageUserRow] = Field(default_factory=list)
    by_creator: list[AdminUsageCreatorRow] = Field(default_factory=list)


class AdminOverviewResp(BaseModel):
    generated_at: str
    stats: AdminStats
    users: list[AdminUserRow] = Field(default_factory=list)
    targets: list[AdminTargetRow] = Field(default_factory=list)
    tasks: list[AdminTaskRow] = Field(default_factory=list)
    usage: AdminUsageSummary = Field(default_factory=AdminUsageSummary)


class AdminUserUpdateReq(BaseModel):
    nickname: Optional[str] = None
    role: Optional[str] = None
    plan: Optional[str] = None
    expires_at: Optional[str] = None


class AdminTargetUpdateReq(BaseModel):
    enabled: bool


class AdminActionResp(BaseModel):
    ok: bool = True
    task_id: Optional[str] = None


def _count(session, stmt) -> int:
    value = session.exec(stmt).one()
    return int(value or 0)


def _grouped_counts(session, stmt) -> dict[int, int]:
    out: dict[int, int] = {}
    for key, value in session.exec(stmt).all():
        if key is not None:
            out[int(key)] = int(value or 0)
    return out


def _max_times(session, stmt) -> dict[int, str]:
    out: dict[int, str] = {}
    for key, value in session.exec(stmt).all():
        if key is not None and value:
            out[int(key)] = str(value)
    return out


def _scalar_int(session: Session, stmt) -> int:
    value = session.exec(stmt).one()
    return int(value or 0)


def _sum_int(value) -> int:
    return int(value or 0)


def _latest(*values: Optional[str]) -> Optional[str]:
    existing = [v for v in values if v]
    return max(existing) if existing else None


def _is_active_user(user: User, now_iso: str) -> bool:
    if user.role == "admin":
        return True
    return user.plan == "pro" and bool(user.expires_at and user.expires_at > now_iso)


def _source_matches_target(source: Source, target: IngestTarget) -> bool:
    return (
        source.platform == target.platform
        and source.type == target.kind
        and source.identifier.strip() == target.target_key
    )


@dataclass
class UserAggregates:
    group_count: dict[int, int]
    source_count: dict[int, int]
    active_source_count: dict[int, int]
    failed_source_count: dict[int, int]
    content_count: dict[int, int]
    signal_count: dict[int, int]
    legacy_signal_count: dict[int, int]
    new_signal_count: dict[int, int]
    legacy_new_signal_count: dict[int, int]
    report_count: dict[int, int]
    task_count: dict[int, int]
    group_updated_at: dict[int, str]
    source_checked_at: dict[int, str]
    task_created_at: dict[int, str]
    report_created_at: dict[int, str]


def _load_user_aggregates(session: Session) -> UserAggregates:
    return UserAggregates(
        group_count=_grouped_counts(
            session,
            select(KnowledgeGroup.owner_id, func.count(KnowledgeGroup.id)).group_by(KnowledgeGroup.owner_id),
        ),
        source_count=_grouped_counts(
            session,
            select(KnowledgeGroup.owner_id, func.count(Source.id))
            .join(Source, Source.group_id == KnowledgeGroup.id)
            .group_by(KnowledgeGroup.owner_id),
        ),
        active_source_count=_grouped_counts(
            session,
            select(KnowledgeGroup.owner_id, func.count(Source.id))
            .join(Source, Source.group_id == KnowledgeGroup.id)
            .where(Source.enabled == True)  # noqa: E712
            .group_by(KnowledgeGroup.owner_id),
        ),
        failed_source_count=_grouped_counts(
            session,
            select(KnowledgeGroup.owner_id, func.count(Source.id))
            .join(Source, Source.group_id == KnowledgeGroup.id)
            .where(Source.last_error.is_not(None))
            .where(Source.last_error != "")
            .group_by(KnowledgeGroup.owner_id),
        ),
        content_count=_grouped_counts(
            session,
            select(KnowledgeGroup.owner_id, func.count(GroupContent.id))
            .join(GroupContent, GroupContent.group_id == KnowledgeGroup.id)
            .group_by(KnowledgeGroup.owner_id),
        ),
        signal_count=_grouped_counts(
            session,
            select(KnowledgeGroup.owner_id, func.count(func.distinct(Signal.id)))
            .join(GroupContent, GroupContent.group_id == KnowledgeGroup.id)
            .join(Signal, Signal.global_content_id == GroupContent.global_content_id)
            .group_by(KnowledgeGroup.owner_id),
        ),
        legacy_signal_count=_grouped_counts(
            session,
            select(KnowledgeGroup.owner_id, func.count(Signal.id))
            .join(Signal, Signal.group_id == KnowledgeGroup.id)
            .where(Signal.global_content_id.is_(None))
            .group_by(KnowledgeGroup.owner_id),
        ),
        new_signal_count=_grouped_counts(
            session,
            select(KnowledgeGroup.owner_id, func.count(func.distinct(Signal.id)))
            .join(GroupContent, GroupContent.group_id == KnowledgeGroup.id)
            .join(Signal, Signal.global_content_id == GroupContent.global_content_id)
            .where(Signal.is_new == True)  # noqa: E712
            .group_by(KnowledgeGroup.owner_id),
        ),
        legacy_new_signal_count=_grouped_counts(
            session,
            select(KnowledgeGroup.owner_id, func.count(Signal.id))
            .join(Signal, Signal.group_id == KnowledgeGroup.id)
            .where(Signal.global_content_id.is_(None))
            .where(Signal.is_new == True)  # noqa: E712
            .group_by(KnowledgeGroup.owner_id),
        ),
        report_count=_grouped_counts(
            session,
            select(KnowledgeGroup.owner_id, func.count(Report.id))
            .join(Report, Report.group_id == KnowledgeGroup.id)
            .group_by(KnowledgeGroup.owner_id),
        ),
        task_count=_grouped_counts(
            session,
            select(KnowledgeGroup.owner_id, func.count(Task.id))
            .join(Task, Task.group_id == KnowledgeGroup.id)
            .group_by(KnowledgeGroup.owner_id),
        ),
        group_updated_at=_max_times(
            session,
            select(KnowledgeGroup.owner_id, func.max(KnowledgeGroup.updated_at)).group_by(KnowledgeGroup.owner_id),
        ),
        source_checked_at=_max_times(
            session,
            select(KnowledgeGroup.owner_id, func.max(Source.last_check))
            .join(Source, Source.group_id == KnowledgeGroup.id)
            .group_by(KnowledgeGroup.owner_id),
        ),
        task_created_at=_max_times(
            session,
            select(KnowledgeGroup.owner_id, func.max(Task.created_at))
            .join(Task, Task.group_id == KnowledgeGroup.id)
            .group_by(KnowledgeGroup.owner_id),
        ),
        report_created_at=_max_times(
            session,
            select(KnowledgeGroup.owner_id, func.max(Report.created_at))
            .join(Report, Report.group_id == KnowledgeGroup.id)
            .group_by(KnowledgeGroup.owner_id),
        ),
    )


def _build_user_row(user: User, aggregates: UserAggregates) -> AdminUserRow:
    user_id = int(user.id)
    return AdminUserRow(
        id=user_id,
        phone=user.phone,
        nickname=user.nickname,
        role=user.role,
        plan=user.plan,
        expires_at=user.expires_at,
        group_count=aggregates.group_count.get(user_id, 0),
        source_count=aggregates.source_count.get(user_id, 0),
        active_source_count=aggregates.active_source_count.get(user_id, 0),
        failed_source_count=aggregates.failed_source_count.get(user_id, 0),
        content_count=aggregates.content_count.get(user_id, 0),
        signal_count=aggregates.signal_count.get(user_id, 0) + aggregates.legacy_signal_count.get(user_id, 0),
        new_signal_count=aggregates.new_signal_count.get(user_id, 0) + aggregates.legacy_new_signal_count.get(user_id, 0),
        report_count=aggregates.report_count.get(user_id, 0),
        task_count=aggregates.task_count.get(user_id, 0),
        last_activity_at=_latest(
            aggregates.group_updated_at.get(user_id),
            aggregates.source_checked_at.get(user_id),
            aggregates.task_created_at.get(user_id),
            aggregates.report_created_at.get(user_id),
        ),
        created_at=user.created_at,
    )


def _build_target_row(session: Session, repo: IngestTargetRepo, target: IngestTarget) -> AdminTargetRow:
    target_id = int(target.id)
    matched_sources = repo.sources_for_target(target_id, enabled_only=False)
    matched_groups: list[KnowledgeGroup] = []
    seen_group_ids: set[int] = set()
    for source in matched_sources:
        group = session.get(KnowledgeGroup, source.group_id)
        if group and group.id is not None and group.id not in seen_group_ids:
            matched_groups.append(group)
            seen_group_ids.add(group.id)
    return AdminTargetRow(
        id=target_id,
        platform=target.platform,
        kind=target.kind,
        target_key=target.target_key,
        enabled=target.enabled,
        admin_paused=bool(target.admin_paused),
        subscriber_count=len(matched_sources),
        group_count=len(matched_groups),
        interval_hours=target.interval_hours,
        days=target.days,
        content_limit=target.content_limit,
        comment_top_n=target.comment_top_n,
        last_check=target.last_check,
        last_error=target.last_error,
        running_task_id=target.running_task_id,
        locked_at=target.locked_at,
        updated_at=target.updated_at,
    )


def _is_target_locked(target: IngestTarget, *, stale_after_minutes: int = 120) -> bool:
    if not target.running_task_id or not target.locked_at:
        return False
    stale_before = (datetime.now() - timedelta(minutes=stale_after_minutes)).isoformat()
    return target.locked_at > stale_before


def _assert_role_change_allowed(session: Session, user: User, new_role: str, current_user_id: int) -> None:
    if new_role == user.role:
        return
    if int(user.id) == current_user_id:
        raise HTTPException(400, "cannot change your own role")
    if user.role == "admin" and new_role != "admin":
        admin_count = int(session.exec(select(func.count(User.id)).where(User.role == "admin")).one() or 0)
        if admin_count <= 1:
            raise HTTPException(400, "cannot remove the last admin")


def _has_source_error(source: Source) -> bool:
    return bool(source.last_error and source.last_error.strip())


def _load_usage_summary(session: Session, *, cutoff_7d_iso: str, cutoff_30d_iso: str) -> AdminUsageSummary:
    actual_7d = _scalar_int(
        session,
        select(func.coalesce(func.sum(LLMUsageEvent.total_tokens), 0))
        .where(LLMUsageEvent.created_at >= cutoff_7d_iso),
    )
    actual_30d = _scalar_int(
        session,
        select(func.coalesce(func.sum(LLMUsageEvent.total_tokens), 0))
        .where(LLMUsageEvent.created_at >= cutoff_30d_iso),
    )
    allocated_30d = _scalar_int(
        session,
        select(func.coalesce(func.sum(LLMUsageAllocation.allocated_total_tokens), 0))
        .where(LLMUsageAllocation.created_at >= cutoff_30d_iso),
    )
    allocated_estimated_30d = _scalar_int(
        session,
        select(func.coalesce(func.sum(LLMUsageAllocation.allocated_estimated_total_tokens), 0))
        .where(LLMUsageAllocation.created_at >= cutoff_30d_iso),
    )
    missing_30d = _count(
        session,
        select(func.count(LLMUsageEvent.id))
        .where(LLMUsageEvent.created_at >= cutoff_30d_iso)
        .where(LLMUsageEvent.metering_status == "missing"),
    )
    failed_30d = _count(
        session,
        select(func.count(LLMUsageEvent.id))
        .where(LLMUsageEvent.created_at >= cutoff_30d_iso)
        .where(LLMUsageEvent.metering_status == "failed"),
    )

    operation_rows: list[AdminUsageOperationRow] = []
    op_total = func.coalesce(func.sum(LLMUsageEvent.total_tokens), 0)
    for row in session.exec(
        select(
            LLMUsageEvent.operation,
            LLMUsageEvent.model,
            func.count(LLMUsageEvent.id),
            func.coalesce(func.sum(LLMUsageEvent.prompt_tokens), 0),
            func.coalesce(func.sum(LLMUsageEvent.completion_tokens), 0),
            op_total,
            func.coalesce(func.sum(LLMUsageEvent.cached_tokens), 0),
            func.coalesce(func.sum(LLMUsageEvent.reasoning_tokens), 0),
            func.coalesce(func.sum(case((LLMUsageEvent.metering_status == "missing", 1), else_=0)), 0),
            func.coalesce(func.sum(case((LLMUsageEvent.metering_status == "failed", 1), else_=0)), 0),
        )
        .where(LLMUsageEvent.created_at >= cutoff_30d_iso)
        .group_by(LLMUsageEvent.operation, LLMUsageEvent.model)
        .order_by(op_total.desc())
        .limit(20)
    ).all():
        operation, model, calls, prompt, completion, total, cached, reasoning, missing, failed = row
        operation_rows.append(AdminUsageOperationRow(
            operation=operation or "unknown",
            model=model or "",
            call_count=_sum_int(calls),
            actual_prompt_tokens=_sum_int(prompt),
            actual_completion_tokens=_sum_int(completion),
            actual_total_tokens=_sum_int(total),
            cached_tokens=_sum_int(cached),
            reasoning_tokens=_sum_int(reasoning),
            missing_events=_sum_int(missing),
            failed_events=_sum_int(failed),
        ))

    user_rows: list[AdminUsageUserRow] = []
    user_total = func.coalesce(func.sum(LLMUsageAllocation.allocated_total_tokens), 0)
    for row in session.exec(
        select(
            LLMUsageAllocation.user_id,
            User.phone,
            User.nickname,
            user_total,
            func.coalesce(func.sum(LLMUsageAllocation.allocated_estimated_total_tokens), 0),
            func.count(func.distinct(LLMUsageAllocation.usage_event_id)),
            func.count(func.distinct(LLMUsageAllocation.group_id)),
            func.count(func.distinct(LLMUsageAllocation.source_id)),
        )
        .join(User, User.id == LLMUsageAllocation.user_id, isouter=True)
        .where(LLMUsageAllocation.created_at >= cutoff_30d_iso)
        .group_by(LLMUsageAllocation.user_id, User.phone, User.nickname)
        .order_by(user_total.desc())
        .limit(30)
    ).all():
        user_id, phone, nickname, total, estimated, calls, groups, sources = row
        user_rows.append(AdminUsageUserRow(
            user_id=user_id,
            phone=phone or "",
            nickname=nickname or "",
            allocated_total_tokens=_sum_int(total),
            allocated_estimated_tokens=_sum_int(estimated),
            call_count=_sum_int(calls),
            group_count=_sum_int(groups),
            source_count=_sum_int(sources),
        ))

    actual_by_creator: dict[int, int] = {}
    for creator_id, total in session.exec(
        select(
            LLMUsageEvent.creator_id,
            func.coalesce(func.sum(LLMUsageEvent.total_tokens), 0),
        )
        .where(LLMUsageEvent.created_at >= cutoff_30d_iso)
        .where(LLMUsageEvent.creator_id.is_not(None))
        .group_by(LLMUsageEvent.creator_id)
    ).all():
        if creator_id is not None:
            actual_by_creator[int(creator_id)] = _sum_int(total)

    creator_rows: list[AdminUsageCreatorRow] = []
    creator_total = func.coalesce(func.sum(LLMUsageAllocation.allocated_total_tokens), 0)
    for row in session.exec(
        select(
            LLMUsageAllocation.creator_id,
            Creator.name,
            creator_total,
            func.coalesce(func.sum(LLMUsageAllocation.allocated_estimated_total_tokens), 0),
            func.count(func.distinct(LLMUsageAllocation.usage_event_id)),
            func.count(func.distinct(LLMUsageAllocation.user_id)),
        )
        .join(Creator, Creator.id == LLMUsageAllocation.creator_id, isouter=True)
        .where(LLMUsageAllocation.created_at >= cutoff_30d_iso)
        .where(LLMUsageAllocation.creator_id.is_not(None))
        .group_by(LLMUsageAllocation.creator_id, Creator.name)
        .order_by(creator_total.desc())
        .limit(30)
    ).all():
        creator_id, name, total, estimated, calls, users = row
        cid = int(creator_id) if creator_id is not None else None
        creator_rows.append(AdminUsageCreatorRow(
            creator_id=cid,
            creator_name=name or (f"creator#{cid}" if cid else ""),
            actual_total_tokens=actual_by_creator.get(cid or -1, 0),
            allocated_total_tokens=_sum_int(total),
            allocated_estimated_tokens=_sum_int(estimated),
            call_count=_sum_int(calls),
            user_count=_sum_int(users),
        ))

    return AdminUsageSummary(
        actual_total_tokens_7d=actual_7d,
        actual_total_tokens_30d=actual_30d,
        allocated_total_tokens_30d=allocated_30d,
        allocated_estimated_tokens_30d=allocated_estimated_30d,
        missing_events_30d=missing_30d,
        failed_events_30d=failed_30d,
        by_operation=operation_rows,
        by_user=user_rows,
        by_creator=creator_rows,
    )


@router.get("/overview", response_model=AdminOverviewResp)
def get_admin_overview():
    now = datetime.now()
    now_iso = now.isoformat()
    cutoff_7d = (now.replace(tzinfo=None) if now.tzinfo else now).timestamp() - 7 * 24 * 3600
    cutoff_7d_iso = datetime.fromtimestamp(cutoff_7d).isoformat()

    with get_session() as session:
        users = list(session.exec(select(User).order_by(User.id)).all())
        groups = list(session.exec(select(KnowledgeGroup).order_by(KnowledgeGroup.id)).all())
        group_by_id = {int(g.id): g for g in groups if g.id is not None}
        user_by_id = {int(u.id): u for u in users if u.id is not None}

        sources = list(session.exec(select(Source).order_by(Source.id)).all())
        source_by_id = {int(s.id): s for s in sources if s.id is not None}
        all_targets = list(session.exec(select(IngestTarget).order_by(IngestTarget.id)).all())
        target_by_id = {int(t.id): t for t in all_targets if t.id is not None}
        target_context: dict[int, tuple[list[Source], list[KnowledgeGroup], list[User]]] = {}
        for target in all_targets:
            matched_sources = [source for source in sources if _source_matches_target(source, target)]
            matched_groups: list[KnowledgeGroup] = []
            matched_users: list[User] = []
            seen_group_ids: set[int] = set()
            seen_user_ids: set[int] = set()
            for source in matched_sources:
                group = group_by_id.get(source.group_id)
                if group and group.id is not None and group.id not in seen_group_ids:
                    matched_groups.append(group)
                    seen_group_ids.add(group.id)
                if group and group.owner_id:
                    owner = user_by_id.get(group.owner_id)
                    if owner and owner.id is not None and owner.id not in seen_user_ids:
                        matched_users.append(owner)
                        seen_user_ids.add(owner.id)
            if target.id is not None:
                target_context[int(target.id)] = (matched_sources, matched_groups, matched_users)

        aggregates = _load_user_aggregates(session)

        targets = sorted(
            all_targets,
            key=lambda target: (
                target.running_task_id is None,
                target.last_error is None,
                not target.enabled,
                -(target.id or 0),
            ),
        )[:50]

        recent_tasks = list(session.exec(select(Task).order_by(Task.created_at.desc()).limit(30)).all())
        usage = _load_usage_summary(session, cutoff_7d_iso=cutoff_7d_iso, cutoff_30d_iso=(now - timedelta(days=30)).isoformat())

        stats = AdminStats(
            users=len(users),
            active_users=sum(1 for user in users if _is_active_user(user, now_iso)),
            groups=len(groups),
            enabled_groups=sum(1 for group in groups if group.enabled),
            sources=len(sources),
            active_sources=sum(1 for source in sources if source.enabled),
            failed_sources=sum(1 for source in sources if _has_source_error(source)),
            ingest_targets=len(all_targets),
            active_targets=sum(1 for target in all_targets if target.enabled),
            targets_with_error=sum(1 for target in all_targets if target.last_error),
            global_content=_count(session, select(func.count(GlobalContent.id))),
            group_content=_count(session, select(func.count(GroupContent.id))),
            recent_content_7d=_count(
                session,
                select(func.count(GlobalContent.id)).where(GlobalContent.first_seen_at >= cutoff_7d_iso),
            ),
            signals=_count(session, select(func.count(Signal.id))),
            new_signals=_count(session, select(func.count(Signal.id)).where(Signal.is_new == True)),  # noqa: E712
            reports=_count(session, select(func.count(Report.id))),
            tasks=_count(session, select(func.count(Task.id))),
            running_tasks=_count(
                session,
                select(func.count(Task.id)).where(Task.status.in_(["pending", "running"])),
            ),
            failed_tasks=_count(session, select(func.count(Task.id)).where(Task.status == "failed")),
            llm_actual_tokens_30d=usage.actual_total_tokens_30d,
            llm_allocated_tokens_30d=usage.allocated_total_tokens_30d,
            llm_missing_events_30d=usage.missing_events_30d,
        )

        user_rows = [_build_user_row(user, aggregates) for user in users]

        repo = IngestTargetRepo(session)
        target_rows = [_build_target_row(session, repo, target) for target in targets]

        task_rows = []
        for task in recent_tasks:
            group = group_by_id.get(task.group_id or -1)
            source = source_by_id.get(task.source_id or -1)
            owner = user_by_id.get(group.owner_id) if group and group.owner_id else None
            if (not group or not source or not owner) and isinstance(task.params, dict):
                try:
                    target_id = int(task.params.get("target_id") or 0)
                except (TypeError, ValueError):
                    target_id = 0
                target = target_by_id.get(target_id)
                target_sources, target_groups, target_users = target_context.get(target_id, ([], [], []))
                source = source or (target_sources[0] if target_sources else None)
                group = group or (target_groups[0] if target_groups else None)
                owner = owner or (target_users[0] if target_users else None)
                if target and not source:
                    source_name = target.target_key
                else:
                    source_name = source.display_name if source else ""
            else:
                source_name = source.display_name if source else ""
            task_rows.append(AdminTaskRow(
                id=task.id,
                kind=task.kind,
                status=task.status,
                group_id=task.group_id or (group.id if group else None),
                group_name=group.name if group else "",
                source_id=task.source_id or (source.id if source else None),
                source_name=source_name,
                owner_phone=owner.phone if owner else "",
                created_at=task.created_at,
                started_at=task.started_at,
                finished_at=task.finished_at,
                error=task.error,
            ))

    return AdminOverviewResp(
        generated_at=now_iso,
        stats=stats,
        users=user_rows,
        targets=target_rows,
        tasks=task_rows,
        usage=usage,
    )


@router.patch("/users/{user_id}", response_model=AdminUserRow)
def update_admin_user(
    user_id: int,
    req: AdminUserUpdateReq,
    current_user: dict = Depends(get_current_user),
):
    with get_session() as session:
        user = UserRepo(session).get(user_id)
        if not user:
            raise HTTPException(404, "user not found")
        if req.nickname is not None:
            user.nickname = req.nickname.strip()
        if req.role is not None:
            if req.role not in ("user", "admin"):
                raise HTTPException(400, "invalid role")
            _assert_role_change_allowed(session, user, req.role, int(current_user["user_id"]))
            user.role = req.role
        if req.plan is not None:
            if req.plan not in ("none", "pro"):
                raise HTTPException(400, "invalid plan")
            user.plan = req.plan
        if "expires_at" in req.model_fields_set:
            user.expires_at = req.expires_at or None
        user = UserRepo(session).update(user)
        return _build_user_row(user, _load_user_aggregates(session))


@router.post("/targets/{target_id}/clear-error", response_model=AdminTargetRow)
def clear_admin_target_error(target_id: int):
    with get_session() as session:
        repo = IngestTargetRepo(session)
        target = repo.clear_lock_and_error(target_id)
        if not target:
            raise HTTPException(404, "target not found")
        return _build_target_row(session, repo, target)


@router.patch("/targets/{target_id}", response_model=AdminTargetRow)
def update_admin_target(target_id: int, req: AdminTargetUpdateReq):
    with get_session() as session:
        repo = IngestTargetRepo(session)
        target = repo.set_admin_paused(target_id, paused=not req.enabled)
        if not target:
            raise HTTPException(404, "target not found")
        return _build_target_row(session, repo, target)


@router.post("/targets/{target_id}/run", response_model=AdminActionResp)
def run_admin_target(target_id: int):
    with get_session() as session:
        target = IngestTargetRepo(session).get(target_id)
        if not target:
            raise HTTPException(404, "target not found")
        if _is_target_locked(target):
            raise HTTPException(409, "target is already running")
    task_id = get_runner().enqueue(
        TaskKind.INGEST_TARGET,
        params={"target_id": target_id, "force": True},
    )
    return AdminActionResp(task_id=task_id)


@router.post("/tasks/{task_id}/retry", response_model=AdminActionResp)
def retry_admin_task(task_id: str):
    with get_session() as session:
        task = session.get(Task, task_id)
        if not task:
            raise HTTPException(404, "task not found")
        if task.status not in ("failed", "canceled"):
            raise HTTPException(400, "only failed or canceled tasks can be retried")
    new_task_id = get_runner().enqueue(
        task.kind,
        params=dict(task.params or {}),
        group_id=task.group_id,
        source_id=task.source_id,
    )
    return AdminActionResp(task_id=new_task_id)
