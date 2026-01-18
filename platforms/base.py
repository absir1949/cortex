"""平台适配器基类"""
from abc import ABC, abstractmethod
from typing import List, Dict, Any
from dataclasses import dataclass


@dataclass
class Video:
    """视频数据类"""
    video_id: str
    title: str
    author: str
    create_time: str
    video_url: str
    share_url: str
    statistics: Dict[str, int]
    platform: str


class PlatformAdapter(ABC):
    """平台适配器基类"""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.platform_name = config.get('platform', 'unknown')

    @abstractmethod
    def fetch_videos(self, creator_id: str, count: int = 20) -> List[Video]:
        """获取创作者的视频列表

        Args:
            creator_id: 创作者ID
            count: 获取数量

        Returns:
            视频列表
        """
        pass

    @abstractmethod
    def download_video(self, video: Video, output_path: str) -> bool:
        """下载视频

        Args:
            video: 视频信息
            output_path: 输出路径

        Returns:
            是否成功
        """
        pass

    def filter_new_videos(self, videos: List[Video], days: int = 7) -> List[Video]:
        """过滤指定天数内的新视频

        Args:
            videos: 视频列表
            days: 天数

        Returns:
            过滤后的视频列表
        """
        from datetime import datetime, timedelta
        cutoff = datetime.now() - timedelta(days=days)

        filtered = []
        for video in videos:
            try:
                create_time = datetime.fromisoformat(video.create_time)
                if create_time > cutoff:
                    filtered.append(video)
            except:
                # 如果时间解析失败，保留该视频
                filtered.append(video)

        return filtered
