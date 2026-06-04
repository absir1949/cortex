"""阿里云转录 - 从旧 transcriber.py 迁入，改用 settings 配置"""
from __future__ import annotations
import subprocess
import tempfile
import uuid
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

try:
    import alibabacloud_oss_v2 as oss
    from alibabacloud_sts20150401.client import Client as StsClient
    from alibabacloud_sts20150401.models import AssumeRoleRequest
    from alibabacloud_tea_openapi.models import Config as OpenApiConfig
    from dashscope.audio.asr import Transcription
    import dashscope
except ImportError as e:
    raise ImportError(f"缺少阿里云转录依赖: {e}")

from app.settings import settings


def transcribe_video(video_path: str) -> str:
    """同步转录流程：提取音频 → OSS 上传 → 百炼识别 → 清理"""
    audio_file = _extract_audio(Path(video_path))
    try:
        oss_url = _upload_to_oss(audio_file)
        try:
            return _transcribe_audio(oss_url)
        finally:
            try:
                _delete_oss_file(oss_url)
            except Exception:
                pass
    finally:
        if audio_file.exists():
            audio_file.unlink()


def _extract_audio(video_path: Path) -> Path:
    tmp = Path(tempfile.gettempdir())
    audio = tmp / f"{video_path.stem}_{datetime.now().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:6]}.wav"
    cmd = [
        "ffmpeg", "-i", str(video_path),
        "-vn", "-acodec", "pcm_s16le",
        "-ar", "16000", "-ac", "1",
        "-y", str(audio),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"ffmpeg 音频提取失败: {res.stderr[:200]}")
    return audio


def _get_sts_token() -> dict:
    cfg = OpenApiConfig(
        access_key_id=settings.aliyun_access_key_id,
        access_key_secret=settings.aliyun_access_key_secret,
        endpoint="sts.cn-beijing.aliyuncs.com",
        region_id="cn-beijing",
    )
    client = StsClient(cfg)
    req = AssumeRoleRequest(
        role_arn=settings.aliyun_sts_role_arn,
        role_session_name="cortex-transcription-session",
        duration_seconds=3600,
    )
    resp = client.assume_role(req)
    c = resp.body.credentials
    return {
        "access_key_id": c.access_key_id,
        "access_key_secret": c.access_key_secret,
        "security_token": c.security_token,
    }


def _upload_to_oss(audio_file: Path) -> str:
    sts = _get_sts_token()
    region = settings.oss_region[4:] if settings.oss_region.startswith("oss-") else settings.oss_region
    provider = oss.credentials.StaticCredentialsProvider(
        sts["access_key_id"], sts["access_key_secret"], sts["security_token"]
    )
    cfg = oss.config.load_default()
    cfg.credentials_provider = provider
    cfg.region = region
    if settings.oss_endpoint:
        cfg.endpoint = settings.oss_endpoint
    client = oss.Client(cfg)

    key = f"cortex-transcription/{datetime.now().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8]}.wav"
    res = client.put_object_from_file(
        oss.PutObjectRequest(bucket=settings.oss_bucket, key=key, acl="public-read"),
        str(audio_file),
    )
    if res.status_code != 200:
        raise RuntimeError(f"OSS 上传失败: {res.status_code}")
    return f"https://{settings.oss_bucket}.{settings.oss_region}.aliyuncs.com/{key}"


def _transcribe_audio(oss_url: str) -> str:
    dashscope.api_key = settings.bailian_api_key
    task = Transcription.async_call(model="paraformer-v2", file_urls=[oss_url])
    if task.status_code != 200:
        raise RuntimeError(f"识别任务提交失败: {task.message}")
    result = Transcription.wait(task=task.output.task_id)
    if result.status_code != 200:
        raise RuntimeError(f"识别失败: {result.message}")
    results = result.output.results or []
    if not results:
        raise RuntimeError("转写结果为空")
    first = results[0]
    text = (
        first.get("transcription")
        or first.get("transcript")
        or first.get("text")
        or ""
    )
    if not text and first.get("transcription_url"):
        import requests
        data = requests.get(first["transcription_url"]).json()
        text = (
            (data.get("transcripts") or [{}])[0].get("text") if data.get("transcripts") else None
        ) or data.get("text") or data.get("transcription") or ""
        if not text:
            parts = []
            for t in data.get("transcripts") or []:
                for s in t.get("sentences") or []:
                    parts.append(s.get("text", ""))
            text = " ".join(parts)
    if not text:
        raise RuntimeError("转写文本为空")
    return text


def _delete_oss_file(oss_url: str) -> None:
    key = urlparse(oss_url).path.lstrip("/")
    sts = _get_sts_token()
    region = settings.oss_region[4:] if settings.oss_region.startswith("oss-") else settings.oss_region
    provider = oss.credentials.StaticCredentialsProvider(
        sts["access_key_id"], sts["access_key_secret"], sts["security_token"]
    )
    cfg = oss.config.load_default()
    cfg.credentials_provider = provider
    cfg.region = region
    if settings.oss_endpoint:
        cfg.endpoint = settings.oss_endpoint
    client = oss.Client(cfg)
    client.delete_object(oss.DeleteObjectRequest(bucket=settings.oss_bucket, key=key))
