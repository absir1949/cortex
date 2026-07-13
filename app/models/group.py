"""知识组 / 订阅源 / 任务 / 报告 — 共享枚举定义

实际持久化模型在 app/db/schema.py（SQLModel table=True）。
这里只定义跨层共享的枚举，避免循环依赖。
"""
from enum import Enum


class SourceType(str, Enum):
    CREATOR = "creator"
    KEYWORD = "keyword"


class TaskKind(str, Enum):
    INGEST = "ingest"                        # 定时订阅采集
    INGEST_TARGET = "ingest_target"          # 共享采集目标级刷新
    RESEARCH = "research"                    # 问听风外部搜索
    TRANSCRIBE_BACKFILL = "transcribe_backfill"
    ANALYZE = "analyze"                      # 仅生成报告（基于已采集的信号，不重新采集）


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELED = "canceled"


class ReportKind(str, Enum):
    SCHEDULED = "scheduled"                  # 定时订阅产出
    RESEARCH = "research"                    # 已停用：旧外部搜索报告
