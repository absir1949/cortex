"""Repository 模式 - 所有 DB 操作走这里，Service 层不直接用 Session"""
from .group_repo import GroupRepo
from .source_repo import SourceRepo
from .config_repo import ConfigRepo
from .task_repo import TaskRepo
from .report_repo import ReportRepo
from .analyzed_repo import AnalyzedRepo
from .signal_repo import SignalRepo
from .creator_repo import CreatorRepo
from .content_repo import ContentRepo
from .refresh_run_repo import RefreshRunRepo
from .user_repo import UserRepo
from .shared_ingest_repo import GlobalContentRepo, GroupContentRepo, IngestTargetRepo, SourceContentRepo

__all__ = [
    "GroupRepo",
    "SourceRepo",
    "ConfigRepo",
    "TaskRepo",
    "ReportRepo",
    "AnalyzedRepo",
    "SignalRepo",
    "CreatorRepo",
    "ContentRepo",
    "RefreshRunRepo",
    "UserRepo",
    "GlobalContentRepo",
    "GroupContentRepo",
    "IngestTargetRepo",
    "SourceContentRepo",
]
