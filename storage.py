"""存储管理模块"""
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional
from config import Config, CreatorConfig


class StorageManager:
    """存储管理器 - 使用视频ID作为文件名，天然去重"""

    def __init__(self, creator_name: str):
        self.creator_name = creator_name
        # 使用 Config 获取正确的目录路径（支持 ID_昵称 格式）
        creator_config = CreatorConfig()
        self.creator_dir = creator_config.get_creator_dir(creator_name)
        self.creator_dir.mkdir(parents=True, exist_ok=True)

    def _get_filename(self, video_id: str, create_time: str = None) -> str:
        """生成文件名（带日期前缀）

        Args:
            video_id: 视频ID
            create_time: 创建时间 (ISO格式)

        Returns:
            文件名（不含扩展名）
        """
        # 提取日期部分作为前缀
        if create_time:
            try:
                # 解析 ISO 时间: 2025-12-22T17:41:07 -> 2025-12-22
                date_part = create_time.split('T')[0]
                return f"{date_part}_{video_id}"
            except:
                pass
        return video_id

    def exists(self, video_id: str) -> bool:
        """检查视频是否已处理"""
        return len(list(self.creator_dir.glob(f"*_{video_id}.*"))) > 0

    def save_video(self, video_id: str, video_path: str, create_time: str = None) -> Path:
        """保存视频文件"""
        import shutil
        filename = self._get_filename(video_id, create_time)
        dest = self.creator_dir / f"{filename}.mp4"
        shutil.copy(video_path, dest)
        return dest

    def save_transcript(self, video_id: str, transcript: str, create_time: str = None) -> Path:
        """保存转录文本"""
        filename = self._get_filename(video_id, create_time)
        dest = self.creator_dir / f"{filename}.txt"
        dest.write_text(transcript, encoding='utf-8')
        return dest

    def save_metadata(self, video_id: str, metadata: Dict[str, Any]) -> Path:
        """保存视频元数据"""
        create_time = metadata.get('create_time')
        filename = self._get_filename(video_id, create_time)
        dest = self.creator_dir / f"{filename}.json"
        dest.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding='utf-8')
        return dest

    def has_transcript(self, video_id: str) -> bool:
        """检查是否已有转录文本"""
        return len(list(self.creator_dir.glob(f"*_{video_id}.txt"))) > 0

    def get_transcript(self, video_id: str) -> Optional[str]:
        """获取转录文本"""
        for txt_file in self.creator_dir.glob(f"*_{video_id}.txt"):
            return txt_file.read_text(encoding='utf-8')
        return None

    def get_metadata(self, video_id: str) -> Optional[Dict[str, Any]]:
        """获取元数据"""
        for json_file in self.creator_dir.glob(f"*_{video_id}.json"):
            return json.loads(json_file.read_text(encoding='utf-8'))
        return None

    def list_videos(self) -> list[Dict[str, Any]]:
        """列出所有已处理的视频"""
        videos = []
        for json_file in self.creator_dir.glob("*.json"):
            try:
                metadata = json.loads(json_file.read_text(encoding='utf-8'))
                videos.append(metadata)
            except:
                continue
        # 按创建时间排序
        videos.sort(key=lambda x: x.get('create_time', ''), reverse=True)
        return videos

    def get_creator_dir(self) -> Path:
        """获取创作者目录"""
        return self.creator_dir
