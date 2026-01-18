"""转录模块 - 阿里云百炼（独立版本）"""
import subprocess
import tempfile
import os
from pathlib import Path
from datetime import datetime
from urllib.parse import urlparse

# 导入阿里云 SDK
try:
    import alibabacloud_oss_v2 as oss
    from alibabacloud_sts20150401.client import Client as StsClient
    from alibabacloud_sts20150401.models import AssumeRoleRequest
    from alibabacloud_tea_openapi.models import Config as OpenApiConfig
    from dashscope.audio.asr import Transcription
    import dashscope
except ImportError:
    raise ImportError("缺少依赖库，请运行: pip install alibabacloud-oss-v2 alibabacloud_sts20150401 alibabacloud_tea_openapi dashscope")

from config import Config


def transcribe_video(video_path: str) -> str:
    """转录视频为文本

    Args:
        video_path: 视频文件路径

    Returns:
        转录文本
    """
    # 1. 提取音频
    audio_file = extract_audio(Path(video_path))

    # 2. 上传到 OSS
    oss_url = upload_to_oss(audio_file)

    # 3. 调用识别
    transcription = transcribe_audio(oss_url)

    # 4. 删除 OSS 临时文件
    try:
        delete_oss_file(oss_url)
    except:
        pass

    # 5. 清理本地音频文件
    if audio_file.exists():
        audio_file.unlink()

    return transcription


def extract_audio(video_path: Path) -> Path:
    """从视频中提取音频"""
    temp_dir = Path(tempfile.gettempdir())
    audio_path = temp_dir / f"{video_path.stem}_{datetime.now().strftime('%Y%m%d%H%M%S')}.wav"

    cmd = [
        'ffmpeg',
        '-i', str(video_path),
        '-vn',  # 不处理视频
        '-acodec', 'pcm_s16le',  # 音频编码
        '-ar', '16000',  # 采样率
        '-ac', '1',  # 单声道
        '-y',
        str(audio_path)
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        raise Exception(f"音频提取失败: {result.stderr[:100]}")

    return audio_path


def get_sts_token():
    """调用 STS AssumeRole 获取临时凭证"""
    access_key_id = Config.ALIYUN_ACCESS_KEY_ID
    access_key_secret = Config.ALIYUN_ACCESS_KEY_SECRET
    role_arn = Config.ALIYUN_STS_ROLE_ARN

    # 创建 STS client
    sts_config = OpenApiConfig(
        access_key_id=access_key_id,
        access_key_secret=access_key_secret,
        endpoint='sts.cn-beijing.aliyuncs.com',
        region_id='cn-beijing'
    )
    sts_client = StsClient(sts_config)

    # 调用 AssumeRole
    request = AssumeRoleRequest(
        role_arn=role_arn,
        role_session_name='cortex-transcription-session',
        duration_seconds=3600
    )

    response = sts_client.assume_role(request)
    credentials = response.body.credentials

    return {
        'access_key_id': credentials.access_key_id,
        'access_key_secret': credentials.access_key_secret,
        'security_token': credentials.security_token
    }


def upload_to_oss(audio_file: Path) -> str:
    """上传文件到OSS并返回公网URL"""
    # 获取 STS 临时凭证
    sts_token = get_sts_token()

    # 处理 region 格式：oss-cn-beijing -> cn-beijing
    oss_region = Config.OSS_REGION
    if oss_region.startswith('oss-'):
        region = oss_region[4:]
    else:
        region = oss_region

    # 使用临时凭证创建 OSS client
    credentials_provider = oss.credentials.StaticCredentialsProvider(
        sts_token['access_key_id'],
        sts_token['access_key_secret'],
        sts_token['security_token']
    )

    cfg = oss.config.load_default()
    cfg.credentials_provider = credentials_provider
    cfg.region = region

    if Config.OSS_ENDPOINT:
        cfg.endpoint = Config.OSS_ENDPOINT

    client = oss.Client(cfg)

    # 生成对象名称（使用时间戳+随机字符串，避免中文和特殊字符导致URL编码问题）
    import uuid
    timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
    random_id = str(uuid.uuid4())[:8]
    key = f"cortex-transcription/{timestamp}_{random_id}.wav"

    # 上传（设置为 public-read 以便百炼 API 访问）
    result = client.put_object_from_file(
        oss.PutObjectRequest(
            bucket=Config.OSS_BUCKET,
            key=key,
            acl='public-read'  # 设置文件为公开可读
        ),
        str(audio_file)
    )

    if result.status_code != 200:
        raise Exception(f"OSS上传失败: {result.status_code}")

    # 生成公网URL
    oss_url = f"https://{Config.OSS_BUCKET}.{Config.OSS_REGION}.aliyuncs.com/{key}"

    return oss_url


def transcribe_audio(oss_url: str) -> str:
    """调用阿里云百炼进行语音识别"""
    # 设置API Key
    dashscope.api_key = Config.BAILIAN_API_KEY

    # 异步提交任务
    task_response = Transcription.async_call(
        model='paraformer-v2',
        file_urls=[oss_url]
    )

    if task_response.status_code != 200:
        raise Exception(f"识别任务提交失败: {task_response.message}")

    task_id = task_response.output.task_id

    # 等待识别完成
    result = Transcription.wait(task=task_id)

    if result.status_code != 200:
        raise Exception(f"识别失败: {result.message}")

    # 获取识别结果
    results = result.output.results
    if not results or len(results) == 0:
        raise Exception("转写结果为空")

    transcription_result = results[0]

    # 尝试不同的字段名
    transcription_text = (
        transcription_result.get('transcription') or
        transcription_result.get('transcript') or
        transcription_result.get('text') or
        ''
    )

    # 如果没有直接的文本，从 transcription_url 下载
    if not transcription_text and transcription_result.get('transcription_url'):
        import requests
        response = requests.get(transcription_result['transcription_url'])
        response.raise_for_status()

        download_data = response.json()

        # 尝试多种可能的字段
        transcription_text = (
            (download_data.get('transcripts', [{}])[0].get('text') if download_data.get('transcripts') else None) or
            download_data.get('text') or
            download_data.get('transcription') or
            ''
        )

        # 如果还是没有，尝试 sentences 结构
        if not transcription_text:
            text_parts = []
            for transcript in download_data.get('transcripts', []):
                for sentence in transcript.get('sentences', []):
                    text_parts.append(sentence.get('text', ''))
            transcription_text = ' '.join(text_parts)

    if not transcription_text:
        raise Exception("转写文本为空")

    return transcription_text


def delete_oss_file(oss_url: str):
    """删除 OSS 临时文件"""
    # 从 URL 提取 key
    # URL 格式: https://bucket.region.aliyuncs.com/key
    parsed = urlparse(oss_url)
    key = parsed.path.lstrip('/')

    # 获取 STS 临时凭证
    sts_token = get_sts_token()

    # 处理 region 格式
    oss_region = Config.OSS_REGION
    if oss_region.startswith('oss-'):
        region = oss_region[4:]
    else:
        region = oss_region

    # 使用临时凭证创建 OSS client
    credentials_provider = oss.credentials.StaticCredentialsProvider(
        sts_token['access_key_id'],
        sts_token['access_key_secret'],
        sts_token['security_token']
    )

    cfg = oss.config.load_default()
    cfg.credentials_provider = credentials_provider
    cfg.region = region

    if Config.OSS_ENDPOINT:
        cfg.endpoint = Config.OSS_ENDPOINT

    client = oss.Client(cfg)

    # 删除文件
    result = client.delete_object(
        oss.DeleteObjectRequest(
            bucket=Config.OSS_BUCKET,
            key=key
        )
    )

    if result.status_code not in [200, 204]:
        raise Exception(f"OSS删除失败: {result.status_code}")
