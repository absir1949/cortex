"""任务查询服务 - runner 的 CRUD 封装"""
from __future__ import annotations
from typing import Optional

from app.db.engine import get_session
from app.db.repos import TaskRepo
from app.db.schema import Task


class TaskService:

    def get(self, task_id: str) -> Optional[Task]:
        with get_session() as s:
            return TaskRepo(s).get(task_id)

    def list(
        self,
        kind: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50,
    ) -> list[Task]:
        with get_session() as s:
            return TaskRepo(s).list(kind=kind, status=status, limit=limit)

    def list_by_group_ids(
        self,
        group_ids: list[int],
        *,
        kind: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50,
    ) -> list[Task]:
        with get_session() as s:
            return TaskRepo(s).list_by_group_ids(group_ids, kind=kind, status=status, limit=limit)
