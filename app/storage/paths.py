"""路径规范集中定义

目录布局：
  data/{group_slug}/{source_slug}/YYYY-MM-DD_{content_id}.{mp4|txt|json}
  knowledge/{group_slug}/knowledge_YYYYMMDD_HHMMSS.{md|json}
  knowledge/{group_slug}/profiles/{source_id}.md   ← 观点档案（持续更新）
  research/{task_id}/{inputs/, comments/, report.md}
"""
from __future__ import annotations
import re
from pathlib import Path
from typing import Optional

from app.settings import settings


def slugify(text: str, max_len: int = 40) -> str:
    """把中文/特殊字符转成安全的 slug。保留中文可读（只剔掉文件系统非法字符）"""
    # 去除文件系统不允许的字符
    s = re.sub(r"[\\/:*?\"<>|\s]+", "-", text.strip())
    s = s.strip("-")
    return s[:max_len] or "unnamed"


def data_file(source_directory: str, filename: str) -> Path:
    """data/{source_directory}/{filename}"""
    return settings.data_dir / source_directory / filename


def source_dir(source_directory: str) -> Path:
    return settings.data_dir / source_directory


def knowledge_dir_for_group(group_slug: str) -> Path:
    return settings.knowledge_dir / group_slug


def research_dir_for_task(task_id: str) -> Path:
    return settings.research_dir / task_id


def profiles_dir() -> Path:
    """knowledge/profiles/ - 全局观点档案目录（按 creator_id，跨组共用）"""
    return settings.knowledge_dir / "profiles"


def profile_path(creator_id: int) -> Path:
    """knowledge/profiles/{creator_id}.md - 某博主的观点档案（全局唯一）"""
    return profiles_dir() / f"{creator_id}.md"


def profiles_dir_for_group(group_slug: str) -> Path:
    """[已废弃] 旧路径 knowledge/{group_slug}/profiles/，仅为迁移兼容保留"""
    return settings.knowledge_dir / group_slug / "profiles"


def content_filename(content_id: str, create_time: Optional[str], ext: str) -> str:
    """YYYY-MM-DD_{content_id}.{ext}"""
    if create_time:
        date_part = create_time.split("T")[0]
        return f"{date_part}_{content_id}.{ext}"
    return f"{content_id}.{ext}"
