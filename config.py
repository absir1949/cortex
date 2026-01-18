"""配置管理"""
import os
import json
from pathlib import Path
from dotenv import load_dotenv
from typing import List, Dict, Any

load_dotenv()


class Config:
    """全局配置"""

    # 项目路径
    BASE_DIR = Path(__file__).parent
    DATA_DIR = BASE_DIR / "data"
    KNOWLEDGE_DIR = BASE_DIR / "knowledge"
    CREATORS_FILE = BASE_DIR / "creators.json"

    # API 配置
    TIKHUB_API_KEY = os.getenv("TIKHUB_API_KEY", "")
    TIKHUB_API_URL = os.getenv("TIKHUB_API_URL", "https://api.tikhub.io")

    DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
    DEEPSEEK_API_URL = os.getenv("DEEPSEEK_API_URL", "https://api.deepseek.com/v1")

    # 阿里云配置
    ALIYUN_ACCESS_KEY_ID = os.getenv("ALIYUN_ACCESS_KEY_ID", "")
    ALIYUN_ACCESS_KEY_SECRET = os.getenv("ALIYUN_ACCESS_KEY_SECRET", "")
    ALIYUN_STS_ROLE_ARN = os.getenv("ALIYUN_STS_ROLE_ARN", "")
    OSS_BUCKET = os.getenv("OSS_BUCKET", "")
    OSS_REGION = os.getenv("OSS_REGION", "oss-cn-beijing")
    OSS_ENDPOINT = os.getenv("OSS_ENDPOINT", "")
    BAILIAN_API_KEY = os.getenv("BAILIAN_API_KEY", "")

    @classmethod
    def ensure_dirs(cls):
        """确保目录存在"""
        cls.DATA_DIR.mkdir(parents=True, exist_ok=True)
        cls.KNOWLEDGE_DIR.mkdir(parents=True, exist_ok=True)


class CreatorConfig:
    """创作者配置管理"""

    def __init__(self):
        self.creators_file = Config.CREATORS_FILE
        self._creators: List[Dict[str, Any]] = []
        self._load()

    def _load(self):
        """加载创作者配置"""
        if self.creators_file.exists():
            with open(self.creators_file, 'r', encoding='utf-8') as f:
                self._creators = json.load(f).get('creators', [])
        else:
            self._creators = []
            self._save()

    def _save(self):
        """保存创作者配置"""
        with open(self.creators_file, 'w', encoding='utf-8') as f:
            json.dump({'creators': self._creators}, f, ensure_ascii=False, indent=2)

    def get_all(self) -> List[Dict[str, Any]]:
        """获取所有创作者"""
        return self._creators

    def get_enabled(self) -> List[Dict[str, Any]]:
        """获取启用的创作者"""
        return [c for c in self._creators if c.get('enabled', True)]

    def add(self, name: str, platform: str, creator_id: str, interval_hours: int = 48):
        """添加创作者"""
        # 生成目录名：ID前8位_昵称
        safe_name = "".join(c for c in name if c.isalnum() or c in (' ', '-', '_')).strip()
        dir_name = f"{creator_id[:8]}_{safe_name}"

        creator = {
            'name': name,
            'platform': platform,
            'id': creator_id,
            'interval_hours': interval_hours,
            'enabled': True,
            'created_at': None,
            'last_check': None,
            'directory': dir_name  # 存储实际目录名
        }
        self._creators.append(creator)
        self._save()
        return creator

    def get_creator_dir(self, name: str) -> Path:
        """获取创作者数据目录（通过名称查找）"""
        for c in self._creators:
            if c['name'] == name:
                dir_name = c['directory']
                return Config.DATA_DIR / dir_name
        raise ValueError(f"找不到名为 {name} 的创作者")

    def get_creator_by_id(self, creator_id: str):
        """通过 ID 获取创作者配置"""
        for c in self._creators:
            if c['id'] == creator_id:
                return c
        return None

    def get_creator_dir_by_id(self, creator_id: str) -> Path:
        """通过 ID 获取创作者数据目录"""
        creator = self.get_creator_by_id(creator_id)
        if not creator:
            raise ValueError(f"找不到 ID 为 {creator_id} 的创作者")
        return Config.DATA_DIR / creator['directory']

    def remove(self, name: str):
        """删除创作者（通过名称）"""
        self._creators = [c for c in self._creators if c['name'] != name]
        self._save()

    def update_last_check(self, name: str):
        """更新最后检查时间"""
        from datetime import datetime
        for c in self._creators:
            if c['name'] == name:
                c['last_check'] = datetime.now().isoformat()
                break
        self._save()
        """获取创作者数据目录（通过名称查找，兼容旧版本）"""
        for c in self._creators:
            if c['name'] == name:
                dir_name = c.get('directory', name)
                return Config.DATA_DIR / dir_name
        # 兼容旧版本：直接用名称
        safe_name = "".join(c for c in name if c.isalnum() or c in (' ', '-', '_')).strip()
        return Config.DATA_DIR / safe_name

    def get_creator_dir_by_id(self, creator_id: str) -> Path:
        """通过 ID 获取创作者数据目录"""
        for c in self._creators:
            if c['id'] == creator_id:
                dir_name = c.get('directory', c.get('name'))
                return Config.DATA_DIR / dir_name
        raise ValueError(f"找不到 ID 为 {creator_id} 的创作者")
