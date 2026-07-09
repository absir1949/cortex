"""Authorization helpers.

HTTP handlers should prove ownership from the resource id they receive instead
of trusting caller-provided group ids. Admins bypass owner checks for operations
that are safe to expose to maintainers.
"""
from __future__ import annotations

from fastapi import HTTPException
from sqlmodel import Session, select

from app.db.schema import ContentItem, KnowledgeGroup, Report, Signal, Source, Task


def is_admin(current_user: dict) -> bool:
    return current_user.get("role") == "admin"


def current_user_id(current_user: dict) -> int:
    return int(current_user["user_id"])


def assert_group_owner(session: Session, group_id: int, current_user: dict) -> KnowledgeGroup:
    group = session.get(KnowledgeGroup, group_id)
    if not group:
        raise HTTPException(404, "group not found")
    if is_admin(current_user) or group.owner_id == current_user_id(current_user):
        return group
    raise HTTPException(403, "forbidden")


def assert_source_owner(session: Session, group_id: int, source_id: int, current_user: dict) -> Source:
    assert_group_owner(session, group_id, current_user)
    source = session.get(Source, source_id)
    if not source or source.group_id != group_id:
        raise HTTPException(404, "source not found")
    return source


def assert_report_owner(session: Session, report_id: int, current_user: dict) -> Report:
    report = session.get(Report, report_id)
    if not report:
        raise HTTPException(404, "report not found")
    if is_admin(current_user):
        return report
    if report.group_id is None:
        raise HTTPException(404, "report not found")
    assert_group_owner(session, report.group_id, current_user)
    return report


def assert_task_owner(session: Session, task_id: str, current_user: dict) -> Task:
    task = session.get(Task, task_id)
    if not task:
        raise HTTPException(404, "task not found")
    if is_admin(current_user):
        return task
    if task.group_id is None:
        raise HTTPException(404, "task not found")
    assert_group_owner(session, task.group_id, current_user)
    return task


def assert_content_owner(
    session: Session,
    *,
    platform: str,
    content_id: str,
    current_user: dict,
) -> ContentItem:
    stmt = select(ContentItem).where(
        ContentItem.platform == platform,
        ContentItem.content_id == content_id,
    )
    items = session.exec(stmt).all()
    if is_admin(current_user) and items:
        return items[0]
    for item in items:
        if item.group_id is not None:
            group = session.get(KnowledgeGroup, item.group_id)
            if group and group.owner_id == current_user_id(current_user):
                return item
    raise HTTPException(404, "transcript not found")


def owned_group_ids(session: Session, current_user: dict) -> list[int]:
    if is_admin(current_user):
        rows = session.exec(select(KnowledgeGroup.id).order_by(KnowledgeGroup.id)).all()
    else:
        rows = session.exec(
            select(KnowledgeGroup.id)
            .where(KnowledgeGroup.owner_id == current_user_id(current_user))
            .order_by(KnowledgeGroup.id)
        ).all()
    return [int(group_id) for group_id in rows if group_id is not None]


def assert_signal_owner(session: Session, signal_id: int, current_user: dict) -> Signal:
    signal = session.get(Signal, signal_id)
    if not signal:
        raise HTTPException(404, "signal not found")
    if is_admin(current_user):
        return signal
    if signal.group_id is None:
        raise HTTPException(404, "signal not found")
    assert_group_owner(session, signal.group_id, current_user)
    return signal
