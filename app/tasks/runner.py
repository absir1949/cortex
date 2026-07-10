"""异步任务执行器

设计：
- ThreadPoolExecutor(max_workers=2)
- SQLite tasks 表持久化状态
- cancel_flags: dict[task_id, Event] 协作取消
- Handler 在每个长步骤前检查 ctx.cancel_flag.is_set() 抛 CancelledError
- 进程启动时把 RUNNING 状态幽灵任务重置为 FAILED（不自动重跑避免重复扣费）
"""
from __future__ import annotations
import threading
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Optional

from app.db.engine import get_session
from app.db.repos import TaskRepo
from app.db.schema import Task
from app.models.group import TaskKind, TaskStatus


class CancelledError(RuntimeError):
    pass


@dataclass
class TaskContext:
    """传递给 handler 的上下文，负责进度回调和取消检查"""
    task_id: str
    _cancel_flag: threading.Event
    _progress_cb: Callable[[dict], None]
    _log_cb: Callable[[str, str], None]  # (level, message)

    def is_cancelled(self) -> bool:
        return self._cancel_flag.is_set()

    def raise_if_cancelled(self):
        if self.is_cancelled():
            raise CancelledError("task cancelled")

    def progress(self, progress: dict) -> None:
        self._progress_cb(progress)

    def log(self, message: str, level: str = "info") -> None:
        self._log_cb(level, message)


class TaskRunner:
    def __init__(self, max_workers: int = 2):
        self.executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="cortex-task")
        self.cancel_flags: dict[str, threading.Event] = {}
        self._lock = threading.Lock()

    # ------ 生命周期 ------

    def startup(self) -> int:
        """启动时调用：清理上一次进程未完成的 RUNNING 任务"""
        with get_session() as s:
            return TaskRepo(s).reset_running_to_failed("service restart")

    def shutdown(self, wait: bool = True) -> None:
        # 先给所有还在跑的任务设置取消
        with self._lock:
            for flag in self.cancel_flags.values():
                flag.set()
        self.executor.shutdown(wait=wait)

    # ------ 提交任务 ------

    def enqueue(
        self,
        kind: TaskKind | str,
        params: Optional[dict] = None,
        *,
        group_id: Optional[int] = None,
        source_id: Optional[int] = None,
    ) -> str:
        kind_str = kind.value if isinstance(kind, TaskKind) else kind
        task_id = uuid.uuid4().hex

        with get_session() as s:
            TaskRepo(s).create(Task(
                id=task_id,
                kind=kind_str,
                status=TaskStatus.PENDING.value,
                group_id=group_id,
                source_id=source_id,
                params=params or {},
                progress={},
                logs=[],
                result={},
            ))

        with self._lock:
            self.cancel_flags[task_id] = threading.Event()

        self.executor.submit(self._run, task_id)
        return task_id

    # ------ 取消 ------

    def cancel(self, task_id: str) -> bool:
        with self._lock:
            flag = self.cancel_flags.get(task_id)
        if flag:
            flag.set()
            return True
        return False

    # ------ 内部：执行流程 ------

    def _run(self, task_id: str) -> None:
        from app.tasks.registry import get_handler

        # 读任务
        with get_session() as s:
            task = TaskRepo(s).get(task_id)
        if not task:
            return

        # 取消标志
        flag = self.cancel_flags.get(task_id) or threading.Event()

        # 进度/日志回调
        def progress_cb(progress: dict) -> None:
            with get_session() as s:
                TaskRepo(s).update_progress(task_id, progress)

        def log_cb(level: str, msg: str) -> None:
            with get_session() as s:
                TaskRepo(s).append_log(task_id, {
                    "ts": datetime.now().isoformat(),
                    "level": level,
                    "message": msg,
                })

        ctx = TaskContext(
            task_id=task_id,
            _cancel_flag=flag,
            _progress_cb=progress_cb,
            _log_cb=log_cb,
        )

        # 标记 RUNNING
        with get_session() as s:
            TaskRepo(s).set_status(task_id, TaskStatus.RUNNING)

        handler = get_handler(task.kind)
        if not handler:
            with get_session() as s:
                TaskRepo(s).set_status(
                    task_id, TaskStatus.FAILED,
                    error=f"no handler for kind={task.kind}",
                )
            return

        from app.runtime_context import reset_current_task_id, set_current_task_id
        context_token = set_current_task_id(task_id)
        try:
            result = handler(task, ctx) or {}
            with get_session() as s:
                TaskRepo(s).set_status(task_id, TaskStatus.SUCCEEDED, result=result)
        except CancelledError:
            with get_session() as s:
                TaskRepo(s).set_status(task_id, TaskStatus.CANCELED)
        except Exception as e:
            err_text = f"{e}\n{traceback.format_exc()}"
            with get_session() as s:
                TaskRepo(s).set_status(task_id, TaskStatus.FAILED, error=err_text)
        finally:
            reset_current_task_id(context_token)
            with self._lock:
                self.cancel_flags.pop(task_id, None)


# ------ 全局单例 ------

_runner: Optional[TaskRunner] = None


def get_runner() -> TaskRunner:
    global _runner
    if _runner is None:
        _runner = TaskRunner()
    return _runner


def set_runner(runner: Optional[TaskRunner]) -> None:
    global _runner
    _runner = runner
