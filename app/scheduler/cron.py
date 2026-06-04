"""APScheduler 按组触发定时订阅

逻辑：
- 为每个启用的知识组注册一个 interval job，间隔 = group.defaults.interval_hours 或系统默认
- 触发时向 TaskRunner 提交 ingest 任务（异步执行）
- 启动时自动 schedule 所有启用的组
"""
from __future__ import annotations
from typing import Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.db.engine import get_session
from app.db.repos import GroupRepo
from app.services import config_service
from app.models.group import TaskKind


class CortexScheduler:
    def __init__(self):
        self.scheduler = BackgroundScheduler(timezone="Asia/Shanghai")
        self._started = False

    def start(self) -> None:
        if self._started:
            return
        self.scheduler.start()
        self._started = True
        self.reload()

    def shutdown(self, wait: bool = True) -> None:
        if self._started:
            self.scheduler.shutdown(wait=wait)
            self._started = False

    def reload(self) -> None:
        """根据当前 DB 状态重建所有 job"""
        # 清掉旧 job
        for job in self.scheduler.get_jobs():
            job.remove()

        with get_session() as s:
            groups = GroupRepo(s).list_all()

        for g in groups:
            if not g.enabled:
                continue
            cfg = config_service.effective_for_group(g.id)
            hours = int(cfg.get("interval_hours", 48))
            self.scheduler.add_job(
                _ingest_group_entry,
                trigger=IntervalTrigger(hours=hours),
                id=f"group_{g.id}",
                name=f"{g.name} ({hours}h)",
                args=[g.id],
                replace_existing=True,
            )

    def list_jobs(self) -> list[dict]:
        out = []
        for job in self.scheduler.get_jobs():
            next_run = job.next_run_time.strftime("%Y-%m-%d %H:%M:%S") if job.next_run_time else None
            out.append({"id": job.id, "name": job.name, "next_run": next_run})
        return out


def _ingest_group_entry(group_id: int) -> None:
    """APScheduler 触发时，向 TaskRunner 提交 ingest 任务"""
    from app.tasks.runner import get_runner
    get_runner().enqueue(
        TaskKind.INGEST,
        params={"group_id": group_id, "force": False, "analyze": True},
        group_id=group_id,
    )


_scheduler: Optional[CortexScheduler] = None


def get_scheduler() -> CortexScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = CortexScheduler()
    return _scheduler
