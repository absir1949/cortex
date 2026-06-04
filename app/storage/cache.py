"""跨 group / 跨 task 的 content 级缓存

命中优先级（从高到低）：
  1. data/**/{*_}{content_id}.* 订阅采集的产物（最完整，有元数据）
  2. research/**/transcripts/{content_id}.txt  之前研究保存的转录
  3. research/**/comments/{content_id}.json    之前研究保存的评论

搜索基于 content_id 的 glob，platform 目前不参与去重（抖音 aweme_id 唯一）。
之后多平台时按需加 platform/{content_id} 前缀。
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

    def get_transcript(self, content_id: str) -> Optional[str]:
        """按 content_id 找一个已有的转录文本。找不到返回 None"""
        # 订阅产物：data/**/{date_}{content_id}.txt
        for f in self.data_dir.rglob(f"*_{content_id}.txt"):
            try:
                txt = f.read_text(encoding="utf-8").strip()
                if txt:
                    return txt
            except Exception:
                continue
        # 订阅产物（无日期前缀）
        for f in self.data_dir.rglob(f"{content_id}.txt"):
            try:
                txt = f.read_text(encoding="utf-8").strip()
                if txt:
                    return txt
            except Exception:
                continue
        # research 攒的
        for f in self.research_dir.rglob(f"transcripts/{content_id}.txt"):
            try:
                txt = f.read_text(encoding="utf-8").strip()
                if txt:
                    return txt
            except Exception:
                continue
        return None

    def get_comments(self, content_id: str) -> Optional[list[dict]]:
        """按 content_id 找一个已有的评论列表。找不到返回 None"""
        # 订阅产物：data/**/{date_}{content_id}.comments.json
        for f in self.data_dir.rglob(f"*_{content_id}.comments.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    return data
            except Exception:
                continue
        # 订阅产物（无日期前缀）
        for f in self.data_dir.rglob(f"{content_id}.comments.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    return data
            except Exception:
                continue
        # research 攒的
        for f in self.research_dir.rglob(f"comments/{content_id}.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    return data
            except Exception:
                continue
        return None

    def get_video_path(self, content_id: str) -> Optional[Path]:
        """按 content_id 找一个已有的视频文件（用于再次研究时避免下载）"""
        for f in self.data_dir.rglob(f"*_{content_id}.mp4"):
            if f.exists() and f.stat().st_size > 10000:
                return f
        for f in self.data_dir.rglob(f"{content_id}.mp4"):
            if f.exists() and f.stat().st_size > 10000:
                return f
        for f in self.research_dir.rglob(f"inputs/{content_id}.mp4"):
            if f.exists() and f.stat().st_size > 10000:
                return f
        return None

    def get_metadata(self, content_id: str) -> Optional[dict]:
        """按 content_id 找已保存的元数据（订阅才有）"""
        for f in self.data_dir.rglob(f"*_{content_id}.json"):
            if f.name.endswith(".comments.json"):
                continue
            try:
                return json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                continue
        return None
