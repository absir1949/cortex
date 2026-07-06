"""版本号驱动的数据库迁移

每个迁移是一个函数，版本号从 1 开始连续。
幂等：已应用的版本会被 SchemaVersion 表记录，不重复执行。
"""
from __future__ import annotations
from datetime import datetime
from typing import Callable
from sqlmodel import Session, select, SQLModel

from app.db.engine import get_engine
from app.db import schema as _schema  # noqa: F401 注册模型


# (版本号, 描述, 执行函数)
_migrations: list[tuple[int, str, Callable[[Session], None]]] = []


def register(version: int, note: str):
    def decorator(fn):
        _migrations.append((version, note, fn))
        return fn
    return decorator


# ============ Migration 001: 初始化全部表 ============

@register(1, "001_init: 创建全部基础表")
def _mig_001_init(session: Session) -> None:
    SQLModel.metadata.create_all(get_engine())


# ============ Migration 003: 新增 signals 表 ============
# （version 2 被根目录 migrations/002_*.py 一次性数据迁移占用，这里从 3 起）
# create_all 幂等：已存在的表跳过，只建新增的 signals 表

@register(3, "003_signals: 新增观点信号表（观点去重判定结果）")
def _mig_003_signals(session: Session) -> None:
    SQLModel.metadata.create_all(get_engine())


# ============ 通用运行器 ============

def current_version(session: Session) -> int:
    rows = session.exec(select(_schema.SchemaVersion).order_by(_schema.SchemaVersion.version.desc())).all()
    return rows[0].version if rows else 0


def run_migrations(verbose: bool = True) -> list[int]:
    """按版本号顺序执行未应用的 migration，返回本次应用的版本列表"""
    from app.db.engine import get_engine
    # 第一次运行时 schema_version 表还不存在，先 create_all 一次
    SQLModel.metadata.create_all(get_engine())

    applied: list[int] = []
    with Session(get_engine()) as session:
        cur = current_version(session)
        for version, note, fn in sorted(_migrations, key=lambda x: x[0]):
            if version <= cur:
                continue
            if verbose:
                print(f"[migrate] applying v{version}: {note}")
            fn(session)
            session.add(_schema.SchemaVersion(
                version=version,
                applied_at=datetime.now().isoformat(),
                note=note,
            ))
            session.commit()
            applied.append(version)
    return applied


if __name__ == "__main__":
    applied = run_migrations()
    if applied:
        print(f"[migrate] applied: {applied}")
    else:
        print("[migrate] already up to date")
