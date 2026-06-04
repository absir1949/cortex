"""文件系统存储 - 按 Source.directory 定位"""
from __future__ import annotations
import json
import shutil
from pathlib import Path
from typing import Any, Optional

from . import paths


class StorageManager:
    """每个 Source 一个 StorageManager 实例"""

    def __init__(self, source_directory: str):
        self.directory = source_directory
        self.base = paths.source_dir(source_directory)
        self.base.mkdir(parents=True, exist_ok=True)

    # ------ 查询 ------

    def exists(self, content_id: str) -> bool:
        return len(list(self.base.glob(f"*_{content_id}.*"))) > 0 or (self.base / f"{content_id}.mp4").exists()

    def has_transcript(self, content_id: str) -> bool:
        return len(list(self.base.glob(f"*_{content_id}.txt"))) > 0 or (self.base / f"{content_id}.txt").exists()

    # ------ 写入 ------

    def save_video(self, content_id: str, src_path: str, create_time: Optional[str] = None) -> Path:
        name = paths.content_filename(content_id, create_time, "mp4")
        dest = self.base / name
        shutil.copy(src_path, dest)
        return dest

    def save_transcript(self, content_id: str, text: str, create_time: Optional[str] = None) -> Path:
        name = paths.content_filename(content_id, create_time, "txt")
        dest = self.base / name
        dest.write_text(text, encoding="utf-8")
        return dest

    def save_metadata(self, content_id: str, metadata: dict[str, Any]) -> Path:
        create_time = metadata.get("create_time")
        name = paths.content_filename(content_id, create_time, "json")
        dest = self.base / name
        dest.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        return dest

    def save_comments(self, content_id: str, comments: list[dict], create_time: Optional[str] = None) -> Path:
        """评论单独存 {content_id}.comments.json"""
        date_part = (create_time or "").split("T")[0]
        prefix = f"{date_part}_" if date_part else ""
        dest = self.base / f"{prefix}{content_id}.comments.json"
        dest.write_text(json.dumps(comments, ensure_ascii=False, indent=2), encoding="utf-8")
        return dest

    # ------ 读取 ------

    def get_metadata(self, content_id: str) -> Optional[dict]:
        for f in self.base.glob(f"*_{content_id}.json"):
            try:
                return json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                continue
        return None

    def get_transcript(self, content_id: str) -> Optional[str]:
        for f in self.base.glob(f"*_{content_id}.txt"):
            try:
                return f.read_text(encoding="utf-8")
            except Exception:
                continue
        return None

    def get_comments(self, content_id: str) -> Optional[list[dict]]:
        for f in self.base.glob(f"*_{content_id}.comments.json"):
            try:
                return json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                continue
        return None

    def list_metadata(self) -> list[dict]:
        out = []
        for f in self.base.glob("*.json"):
            if f.name.endswith(".comments.json"):
                continue
            try:
                out.append(json.loads(f.read_text(encoding="utf-8")))
            except Exception:
                continue
        out.sort(key=lambda x: x.get("create_time", ""), reverse=True)
        return out
