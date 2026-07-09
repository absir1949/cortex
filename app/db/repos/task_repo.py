from __future__ import annotations
from datetime import datetime
from typing import Any, Optional
from sqlmodel import Session, select

from app.db.schema import Task
from app.models.group import TaskStatus


class TaskRepo:
    def __init__(self, session: Session):
        self.session = session

    def create(self, task: Task) -> Task:
        self.session.add(task)
        self.session.commit()
        self.session.refresh(task)
        return task

    def get(self, task_id: str) -> Optional[Task]:
        return self.session.get(Task, task_id)

    def list(
        self,
        kind: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50,
    ) -> list[Task]:
        stmt = select(Task)
        if kind:
            stmt = stmt.where(Task.kind == kind)
        if status:
            stmt = stmt.where(Task.status == status)
        stmt = stmt.order_by(Task.created_at.desc()).limit(limit)
        return list(self.session.exec(stmt).all())

    def list_by_group_ids(
        self,
        group_ids: list[int],
        *,
        kind: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50,
    ) -> list[Task]:
        if not group_ids:
            return []
        stmt = select(Task).where(Task.group_id.in_(group_ids))
        if kind:
            stmt = stmt.where(Task.kind == kind)
        if status:
            stmt = stmt.where(Task.status == status)
        stmt = stmt.order_by(Task.created_at.desc()).limit(limit)
        return list(self.session.exec(stmt).all())

    def set_status(
        self,
        task_id: str,
        status: TaskStatus | str,
        *,
        error: Optional[str] = None,
        result: Optional[dict] = None,
    ) -> None:
        task = self.session.get(Task, task_id)
        if not task:
            return
        task.status = status.value if isinstance(status, TaskStatus) else status
        if status in (TaskStatus.RUNNING, "running") and not task.started_at:
            task.started_at = datetime.now().isoformat()
        if status in (TaskStatus.SUCCEEDED, TaskStatus.FAILED, TaskStatus.CANCELED,
                      "succeeded", "failed", "canceled"):
            task.finished_at = datetime.now().isoformat()
        if error is not None:
            task.error = error
        if result is not None:
            task.result = result
        self.session.add(task)
        self.session.commit()

    def update_progress(self, task_id: str, progress: dict[str, Any]) -> None:
        task = self.session.get(Task, task_id)
        if not task:
            return
        task.progress = progress
        self.session.add(task)
        self.session.commit()

    def append_log(self, task_id: str, log: dict[str, Any], max_kept: int = 200) -> None:
        task = self.session.get(Task, task_id)
        if not task:
            return
        logs = list(task.logs or [])
        logs.append(log)
        if len(logs) > max_kept:
            logs = logs[-max_kept:]
        task.logs = logs
        self.session.add(task)
        self.session.commit()

    def reset_running_to_failed(self, note: str = "service restart") -> int:
        """进程启动时把 RUNNING 状态的幽灵任务标为 FAILED"""
        rows = self.session.exec(select(Task).where(Task.status == TaskStatus.RUNNING.value)).all()
        for t in rows:
            t.status = TaskStatus.FAILED.value
            t.error = f"interrupted: {note}"
            t.finished_at = datetime.now().isoformat()
            self.session.add(t)
        if rows:
            self.session.commit()
        return len(rows)
