"""抖音平台适配器"""
import subprocess
import requests
from typing import List
from pathlib import Path
from .base import PlatformAdapter, Video
from config import Config


class DouyinAdapter(PlatformAdapter):
    """抖音平台适配器"""

    def __init__(self, config):
        super().__init__(config)
        self.api_key = Config.TIKHUB_API_KEY
        self.api_url = Config.TIKHUB_API_URL

    def fetch_videos(self, creator_id: str, count: int = 20) -> List[Video]:
        """获取抖音博主视频列表"""
        response = requests.get(
            f"{self.api_url}/api/v1/douyin/app/v3/fetch_user_post_videos",
            params={
                "sec_user_id": creator_id,
                "max_cursor": "0",
                "count": str(count),
                "sort_type": "0"
            },
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=30
        )

        data = response.json()
        if data.get("code") != 200:
            raise Exception(f"API 错误: {data.get('message', 'Unknown error')}")

        videos = []
        for item in data.get("data", {}).get("aweme_list", []):
            author = item.get("author", {})
            statistics = item.get("statistics", {})
            video = item.get("video", {})
            play_addr = video.get("play_addr", {})
            url_list = play_addr.get("url_list", [])

            videos.append(Video(
                video_id=item.get("aweme_id", ""),
                title=item.get("desc", "无标题"),
                author=author.get("nickname", "未知作者"),
                create_time=f"{datetime.fromtimestamp(item.get('create_time', 0)).isoformat()}",
                video_url=url_list[0] if url_list else "",
                share_url=f"https://www.douyin.com/video/{item.get('aweme_id', '')}",
                statistics={
                    "digg_count": statistics.get("digg_count", 0),
                    "comment_count": statistics.get("comment_count", 0),
                    "share_count": statistics.get("share_count", 0),
                    "play_count": statistics.get("play_count", 0),
                },
                platform="douyin"
            ))

        return videos

    def download_video(self, video: Video, output_path: str) -> bool:
        """下载抖音视频"""
        script_path = Path("/Volumes/扩展/code/mcp/n8n/scripts/download-douyin-video.js")

        try:
            result = subprocess.run(
                ["node", str(script_path), video.share_url, output_path],
                capture_output=True,
                text=True,
                timeout=180,
                check=False
            )

            if result.returncode != 0:
                return False

            # 检查文件是否存在
            return Path(output_path).exists()

        except Exception:
            return False


from datetime import datetime
