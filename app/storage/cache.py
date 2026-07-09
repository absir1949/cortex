"""跨 group / 跨 task 的 content 级缓存

命中优先级（从高到低）：
  1. data/{platform}/**/{*_}{content_id}.* 全局采集产物
  2. data/**/{*_}{content_id}.* 旧订阅采集产物（用邻近 metadata 校验 platform）
  3. research/**/transcripts/{content_id}.txt  之前研究保存的转录
  4. research/**/comments/{content_id}.json    之前研究保存的评论

新调用应传 `(platform, content_id)`，旧的一参调用仅作为 research 兼容路径。
"""
from __future__ import annotations
import json
from pathlib import Path
from typing import Optional

from app.settings import settings


class ContentCache:
    """只读 + 可选写入的内容缓存。不影响任何现有写路径。"""

    def __init__(self):
        self.data_dir = settings.data_dir
        self.research_dir = settings.research_dir

    # ---------- 查询 ----------

    def get_transcript(self, platform_or_content_id: str, content_id: Optional[str] = None) -> Optional[str]:
        """按 (platform, content_id) 找一个已有的转录文本。找不到返回 None"""
        platform, cid = self._normalize_args(platform_or_content_id, content_id)
        # 订阅产物：data/**/{date_}{content_id}.txt
        for f in self._iter_data_files(platform, f"*_{cid}.txt"):
            try:
                txt = f.read_text(encoding="utf-8").strip()
                if txt:
                    return txt
            except Exception:
                continue
        # 订阅产物（无日期前缀）
        for f in self._iter_data_files(platform, f"{cid}.txt"):
            try:
                txt = f.read_text(encoding="utf-8").strip()
                if txt:
                    return txt
            except Exception:
                continue
        # research 攒的
        for f in self.research_dir.rglob(f"transcripts/{cid}.txt"):
            try:
                txt = f.read_text(encoding="utf-8").strip()
                if txt:
                    return txt
            except Exception:
                continue
        return None

    def get_comments(self, platform_or_content_id: str, content_id: Optional[str] = None) -> Optional[list[dict]]:
        """按 (platform, content_id) 找一个已有的评论列表。找不到返回 None"""
        platform, cid = self._normalize_args(platform_or_content_id, content_id)
        # 订阅产物：data/**/{date_}{content_id}.comments.json
        for f in self._iter_data_files(platform, f"*_{cid}.comments.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    return data
            except Exception:
                continue
        # 订阅产物（无日期前缀）
        for f in self._iter_data_files(platform, f"{cid}.comments.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    return data
            except Exception:
                continue
        # research 攒的
        for f in self.research_dir.rglob(f"comments/{cid}.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    return data
            except Exception:
                continue
        return None

    def get_video_path(self, platform_or_content_id: str, content_id: Optional[str] = None) -> Optional[Path]:
        """按 (platform, content_id) 找一个已有的视频文件（用于再次研究时避免下载）"""
        platform, cid = self._normalize_args(platform_or_content_id, content_id)
        for f in self._iter_data_files(platform, f"*_{cid}.mp4"):
            if f.exists() and f.stat().st_size > 10000:
                return f
        for f in self._iter_data_files(platform, f"{cid}.mp4"):
            if f.exists() and f.stat().st_size > 10000:
                return f
        for f in self.research_dir.rglob(f"inputs/{cid}.mp4"):
            if f.exists() and f.stat().st_size > 10000:
                return f
        return None

    def get_metadata(self, platform_or_content_id: str, content_id: Optional[str] = None) -> Optional[dict]:
        """按 (platform, content_id) 找已保存的元数据（订阅才有）"""
        platform, cid = self._normalize_args(platform_or_content_id, content_id)
        for f in self._iter_data_files(platform, f"*_{cid}.json"):
            if f.name.endswith(".comments.json"):
                continue
            try:
                return json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                continue
        return None

    def _normalize_args(self, platform_or_content_id: str, content_id: Optional[str]) -> tuple[Optional[str], str]:
        if content_id is None:
            return None, platform_or_content_id
        return platform_or_content_id, content_id

    def _iter_data_files(self, platform: Optional[str], pattern: str):
        if platform:
            platform_root = self.data_dir / platform
            if platform_root.exists():
                yield from platform_root.rglob(pattern)
        for path in self.data_dir.rglob(pattern):
            if self._matches_platform(path, platform):
                yield path

    def _matches_platform(self, path: Path, platform: Optional[str]) -> bool:
        if not platform:
            return True
        metadata = self._metadata_path_for(path)
        if not metadata.exists():
            return True
        try:
            data = json.loads(metadata.read_text(encoding="utf-8"))
        except Exception:
            return False
        return data.get("platform") == platform

    def _metadata_path_for(self, path: Path) -> Path:
        name = path.name
        if name.endswith(".comments.json"):
            return path.with_name(name.removesuffix(".comments.json") + ".json")
        return path.with_suffix(".json")
