"""SQLite 引擎 - WAL 模式 + busy_timeout，解决并发写"""
from __future__ import annotations
from pathlib import Path
from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlmodel import SQLModel, Session, create_engine

from app.settings import settings


_engine: Engine | None = None


def get_engine() -> Engine:
    """惰性创建引擎（允许测试时覆盖 settings.db_path）"""
    global _engine
    if _engine is None:
        settings.db_path.parent.mkdir(parents=True, exist_ok=True)
        url = f"sqlite:///{settings.db_path}"
        _engine = create_engine(
            url,
            connect_args={"check_same_thread": False, "timeout": 30.0},
            echo=False,
        )

        @event.listens_for(_engine, "connect")
        def _set_sqlite_pragma(dbapi_connection, _):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.close()

    return _engine


def reset_engine_for_tests(db_path: Path) -> None:
    """测试专用：切换到临时 DB 路径"""
    global _engine
    _engine = None
    settings.db_path = db_path


def get_session() -> Session:
    return Session(get_engine())


def create_all() -> None:
    """根据 SQLModel 创建全部表（开发和测试用；生产走 migrations）"""
    from app.db import schema  # noqa: F401 触发模型注册
    SQLModel.metadata.create_all(get_engine())
