"""APScheduler 按共享采集目标触发定时订阅

逻辑：
- 注册一个固定扫描 job
- 扫描 due 的 IngestTarget，向 TaskRunner 提交 ingest_target 任务
- 采集目标内部会把新内容分发给所有订阅它的专题
"""
from __future__ import annotations
from typing import Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.db.engine import get_session
from app.db.repos import IngestTargetRepo
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

        self.scheduler.add_job(
            _scan_ingest_targets_entry,
            trigger=IntervalTrigger(minutes=15),
            id="target_scan",
            name="共享采集目标扫描 (15m)",
            replace_existing=True,
        )

    def list_jobs(self) -> list[dict]:
        out = []
        for job in self.scheduler.get_jobs():
            next_run = job.next_run_time.strftime("%Y-%m-%d %H:%M:%S") if job.next_run_time else None
            out.append({"id": job.id, "name": job.name, "next_run": next_run})
        return out


def _scan_ingest_targets_entry() -> None:
    """APScheduler 触发时，扫描 due 的 IngestTarget 并提交任务。"""
    from app.tasks.runner import get_runner
    with get_session() as s:
        targets = IngestTargetRepo(s).due_targets(limit=20)
    runner = get_runner()
    for target in targets:
        runner.enqueue(
            TaskKind.INGEST_TARGET,
            params={"target_id": target.id, "force": False},
        )


_scheduler: Optional[CortexScheduler] = None


def get_scheduler() -> CortexScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = CortexScheduler()
    return _scheduler
