"""pytest 配置 - 每个测试用独立临时 DB"""
from __future__ import annotations
import tempfile
from pathlib import Path
import pytest

from app.db.engine import reset_engine_for_tests, get_engine
from sqlmodel import SQLModel


@pytest.fixture(autouse=True)
def fresh_db(tmp_path: Path):
    db_file = tmp_path / "test.db"
    reset_engine_for_tests(db_file)
    from app.db import schema  # noqa: F401 注册模型
    SQLModel.metadata.create_all(get_engine())
    yield
