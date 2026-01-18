# Cortex - 内容智能采集系统

自动监控内容创作者，下载视频、语音转文字、AI 知识提取。

## 特性

- 🎥 **自动下载** - 支持多平台（抖音、更多开发中...）
- 🎤 **语音转文字** - 阿里云百炼 ASR，准确率高
- 📅 **智能命名** - `{日期}_{视频ID}` 格式，按时间排序
- 🔄 **自动去重** - 基于视频 ID，不重复下载
- ⏰ **定时监控** - APScheduler 定时调度
- 🧠 **知识提取** - AI 分析所有内容生成知识报告
- 📦 **轻量级** - 独立系统，无需复杂依赖

## 安装

```bash
# 1. 进入项目目录
cd ~/code/mcp/cortex

# 2. 创建虚拟环境
python -m venv .venv
source .venv/bin/activate

# 3. 安装依赖（注意版本）
pip install -r requirements.txt
```

**重要依赖版本**（已测试）：
```
alibabacloud-oss-v2==1.2.1
alibabacloud-sts20150401==1.1.6
dashscope==1.25.1
```

## 配置

### 1. 环境变量

复制 `.env.example` 为 `.env`：

```bash
cp .env.example .env
```

需要配置的密钥：

| 配置项 | 说明 | 获取方式 |
|--------|------|----------|
| `TIKHUB_API_KEY` | 抖音 API | https://api.tikhub.io |
| `BAILIAN_API_KEY` | 阿里云百炼 | 阿里云控制台 |
| `ALIYUN_ACCESS_KEY_ID` | 阿里云 AK | 阿里云控制台 |
| `ALIYUN_ACCESS_KEY_SECRET` | 阿里云 SK | 阿里云控制台 |
| `ALIYUN_STS_ROLE_ARN` | STS 角色 | 阿里云控制台 |
| `OSS_BUCKET` | OSS Bucket | 阿里云控制台 |
| `OSS_REGION` | OSS 区域 | 如 `oss-cn-beijing` |
| `DEEPSEEK_API_KEY` | AI 总结 | DeepSeek 开放平台 |

### 2. 创作者配置

使用命令添加：

```bash
python cli.py add <昵称> <平台> <ID> [间隔小时数]

# 示例：添加抖音创作者，每48小时检查一次
python cli.py add 九栢米电商 douyin MS4wLjABAAAA... 48
```

或直接编辑 `creators.json`：

```json
{
  "creators": [
    {
      "name": "九栢米电商",
      "platform": "douyin",
      "id": "MS4wLjABAAAAi2lM8Jn9_RdVZ2dDZPIBDQEXRTth11EVqpdPCerS3dc",
      "interval_hours": 48,
      "enabled": true,
      "directory": "MS4wLjAB_九栢米电商"
    }
  ]
}
```

**支持平台**：
- `douyin` - 抖音

## 使用

### 命令列表

```bash
# 添加创作者
python cli.py add <昵称> <平台> <ID> [间隔]

# 列出所有创作者
python cli.py list

# 删除创作者
python cli.py remove <昵称>

# 运行一次（下载新视频 + 转录）
python cli.py run

# 给已下载视频补充转录
python cli.py transcribe

# 启动定时监控
python cli.py start

# 停止监控
python cli.py stop

# 查看状态
python cli.py status

# 查看已处理视频
python cli.py videos                    # 所有创作者
python cli.py videos "九栢米电商"      # 特定创作者

# 生成知识报告
python cli.py knowledge
```

### 使用流程

#### 1. 初次使用

```bash
# 添加创作者
python cli.py add 九栢米电商 douyin MS4wLjABAAAA...

# 运行一次，下载历史视频
python cli.py run
```

#### 2. 补充转录

如果之前跳过了转录，可以补充：

```bash
python cli.py transcribe
```

#### 3. 定时监控

```bash
# 启动定时任务（按配置的间隔自动检查）
python cli.py start
```

按 `Ctrl+C` 停止。

#### 4. 查看结果

```bash
# 查看已处理的视频
python cli.py videos

# 查看转录内容
cat data/MS4wLjAB_九栢米电商/2025-12-22_7586614939215367461.txt
```

## 文件结构

```
cortex/
├── cli.py              # 命令行入口
├── config.py           # 配置管理
├── scheduler.py        # 核心处理逻辑
├── storage.py          # 文件存储管理
├── transcriber.py      # 语音转文字（阿里云百炼）
├── knowledge.py        # AI 知识提取
├── platforms/          # 平台适配器
│   ├── __init__.py
│   ├── base.py         # PlatformAdapter 基类
│   └── douyin.py       # 抖音实现
├── data/               # 数据目录
│   └── {ID前8位}_昵称/  # 创作者目录
│       ├── 2025-12-22_{视频ID}.mp4    # 视频
│       ├── 2025-12-22_{视频ID}.txt    # 转录文本
│       └── 2025-12-22_{视频ID}.json   # 元数据
├── knowledge/          # 知识报告目录
├── creators.json       # 创作者配置
├── .env                # 环境变量
└── requirements.txt    # 依赖列表
```

## 数据命名规范

### 目录名：`{ID前8位}_{昵称}`
- 示例：`MS4wLjAB_九栢米电商`
- 优点：唯一标识 + 可读性

### 文件名：`{日期}_{视频ID}.{扩展名}`
- 示例：`2025-12-22_7586614939215367461.mp4`
- 优点：
  - ✅ 按时间自动排序
  - ✅ 唯一标识（基于视频 ID）
  - ✅ 不依赖创作者昵称

## 开发

### 添加新平台

1. 在 `platforms/` 下创建新文件（如 `xiaohongshu.py`）
2. 继承 `PlatformAdapter` 基类
3. 实现以下方法：

```python
from platforms.base import PlatformAdapter

class XiaohongshuAdapter(PlatformAdapter):
    def fetch_videos(self, creator_id: str, count: int = 20) -> List[Video]:
        # 获取视频列表
        pass

    def download_video(self, video: Video, output_path: str) -> bool:
        # 下载视频
        pass
```

4. 在 `platforms/__init__.py` 中注册

## 常见问题

### Q: 转录失败，提示 CRC 错误？

**A**: 网络问题导致 OSS 上传失败。重试即可：

```bash
python cli.py transcribe
```

已成功的会自动跳过。

### Q: 如何批量添加创作者？

**A**: 直接编辑 `creators.json` 文件：

```json
{
  "creators": [
    {"name": "创作者1", "platform": "douyin", "id": "...", "interval_hours": 48, "enabled": true},
    {"name": "创作者2", "platform": "douyin", "id": "...", "interval_hours": 48, "enabled": true}
  ]
}
```

### Q: 视频下载失败？

**A**: 可能原因：
1. TikHub API 密钥无效
2. 视频已被创作者删除
3. 网络问题

### Q: 如何只下载不转录？

**A**: 暂时没有命令行参数，可以直接修改 `scheduler.py` 中的 `skip_transcribe` 参数。

### Q: 转录速度慢？

**A**: 每个视频需要：
1. 提取音频（几秒）
2. 上传到 OSS（取决于网速）
3. 阿里云百炼处理（通常 30-60 秒）

## License

MIT
