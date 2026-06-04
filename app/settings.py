"""系统级环境变量与 secrets（只读，不暴露在 /api/config）"""
from pathlib import Path
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # 老字段兼容：DEEPSEEK_API_KEY / DEEPSEEK_API_URL
    deepseek_api_key: str = ""
    deepseek_api_url: str = ""

    # 基础路径
    base_dir: Path = Path(__file__).resolve().parent.parent
    data_dir: Path = Path(__file__).resolve().parent.parent / "data"
    knowledge_dir: Path = Path(__file__).resolve().parent.parent / "knowledge"
    research_dir: Path = Path(__file__).resolve().parent.parent / "research"
    backup_dir: Path = Path(__file__).resolve().parent.parent / "backup"
    db_dir: Path = Path(__file__).resolve().parent.parent / "state"
    db_path: Path = Path(__file__).resolve().parent.parent / "state" / "cortex.db"

    # HTTP
    http_host: str = "0.0.0.0"
    http_port: int = 8080

    # 平台 API
    tikhub_api_key: str = ""
    tikhub_api_url: str = "https://api.tikhub.io"

    # 阿里云（转录）
    aliyun_access_key_id: str = ""
    aliyun_access_key_secret: str = ""
    aliyun_sts_role_arn: str = ""
    oss_bucket: str = ""
    oss_region: str = "oss-cn-beijing"
    oss_endpoint: str = ""
    bailian_api_key: str = ""

    # 飞书 Bee（可选，P0 保留但不是核心）
    bee_url: str = ""
    bee_notify_group: str = ""

    # LLM secrets（runtime 参数走 DB）
    # 若 DB 里没配置，回退到这里的环境变量
    llm_api_key: str = ""
    llm_base_url: str = "https://api.deepseek.com/v1"
    llm_model: str = "deepseek-chat"

    def ensure_dirs(self) -> None:
        """确保关键目录存在"""
        for d in (self.data_dir, self.knowledge_dir, self.research_dir, self.backup_dir, self.db_dir):
            d.mkdir(parents=True, exist_ok=True)

    @model_validator(mode="after")
    def _fallback_llm_from_deepseek(self) -> "Settings":
        """老部署兼容：LLM_API_KEY 没配时退到 DEEPSEEK_API_KEY / DEEPSEEK_API_URL"""
        if not self.llm_api_key and self.deepseek_api_key:
            self.llm_api_key = self.deepseek_api_key
        if self.llm_base_url == "https://api.deepseek.com/v1" and self.deepseek_api_url:
            self.llm_base_url = self.deepseek_api_url.rstrip("/")
        return self


settings = Settings()
