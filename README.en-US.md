

# TingFeng (cortex) - Your Industry Trend Listener

Automatically monitors a batch of content creators, downloads videos, converts speech to text, and uses AI to extract insights. Features memory: it can determine whether a creator is presenting a new idea or rehashing old ones, so you only see what's truly new.

## Features

- 🧠 **Insight Memory** - Maintains a continuously updated insight profile for each creator, automatically filtering duplicate content
- 🆕 **New Signal Detection** - New videos are compared against the profile first; only "new" insights make it into the daily report highlights
- 🎥 **Automated Collection** - Multi-platform support (Douyin currently supported, more in development), with video ID-based deduplication
- 🎤 **Speech-to-Text** - Alibaba Cloud Bailian ASR
- 🔍 **On-Demand Research** - Ask ad-hoc questions, and the system automatically searches content, transcribes, and answers with evidence
- ⏰ **Scheduled Execution** - APScheduler triggers per knowledge group, running multi-source tasks in parallel within each group
- 🌐 **Web Interface** - FastAPI + React SPA, do everything right in your browser

## Architecture

```
cortex/
├── app/                    # 主应用（FastAPI）
│   ├── main.py             # 入口：lifespan + 路由 + 静态托管
│   ├── settings.py         # 环境变量/secrets
│   ├── api/                # REST 端点：groups/sources/research/tasks/reports/config/signals
│   ├── services/           # 业务层：ingest/research/knowledge/signal/profile/...
│   ├── tasks/              # 异步任务执行器（ThreadPool）+ handler 注册表
│   ├── platforms/          # 平台适配器（base + douyin）
│   ├── storage/            # 文件系统 + 缓存 + 路径
│   ├── llm/                # OpenAI 兼容客户端（DeepSeek/OpenAI/千问/智谱...）
│   ├── scheduler/          # APScheduler 定时触发
│   ├── transcribe/         # 阿里云百炼 ASR
│   ├── db/                 # SQLModel 表 + Repo + 迁移
│   ├── models/             # 跨层共享枚举
│   ├── notify/             # 飞书 Bee 通知（可选）
│   ├── cli/                # 薄 CLI（调试用）：python -m app.cli
│   └── web/static/         # 前端构建产物（gitignore，构建生成）
├── frontend/               # React SPA（Vite + TanStack Query + Tailwind）
│   └── src/pages/          # Dashboard/GroupDetail/ResearchForm/ReportView/Settings/...
├── data/                   # 采集产物（每条内容三件套：mp4/txt/json）
├── knowledge/              # 知识报告 + 观点档案
├── research/               # 按需研究产出
├── state/cortex.db         # SQLite（groups/sources/tasks/reports/signals/...）
├── migrations/             # 一次性历史数据迁移脚本（已跑过）
├── tests/                  # pytest（phase1-6）
├── requirements.txt
├── Dockerfile / docker-compose.yml
└── .env
```

## Installation

```bash
# 1. 进入项目
cd ~/code/mcp/cortex

# 2. 虚拟环境
python -m venv .venv
source .venv/bin/activate

# 3. Python 依赖
pip install -r requirements.txt

# 4. 前端依赖（如需改前端）
cd frontend && npm install && cd ..
```

## Configuration

Copy `.env.example` to `.env`:

```bash
cp .env.example .env
```

Required environment variables:

| Configuration | Description |
|--------|------|
| `TIKHUB_API_KEY` | Douyin API (https://api.tikhub.io) |
| `BAILIAN_API_KEY` | Alibaba Cloud Bailian (Speech Recognition) |
| `ALIYUN_ACCESS_KEY_ID` / `ALIYUN_ACCESS_KEY_SECRET` | Alibaba Cloud AK/SK |
| `ALIYUN_STS_ROLE_ARN` / `OSS_BUCKET` / `OSS_REGION` | For OSS Transcription |
| `LLM_API_KEY` / `LLM_BASE_URL` / `LLM_MODEL` | LLM (Default: DeepSeek, configurable in Web Settings) |

> Legacy fields `DEEPSEEK_API_KEY` / `DEEPSEEK_API_URL` remain supported (falls back if `LLM_*` is not configured).

LLM settings, collection parameters, and prompt templates can all be hot-reloaded via the **Web Settings page** without restarting.

## Running

### Development Mode (Frontend/Backend Separated)

```bash
# 后端（终端 1）
uvicorn app.main:app --reload --port 8080

# 前端（终端 2，自动代理 /api 到 8080）
cd frontend && npm run dev
# 打开 http://localhost:5173
```

### Production Mode (Frontend Built & Served by FastAPI)

```bash
# 构建前端
cd frontend && npm run build

# 拷贝产物到后端静态目录
cp -r dist/* ../app/web/static/

# 启动
cd ..
uvicorn app.main:app --port 8080
# 打开 http://localhost:8080
```

### Docker

```bash
docker compose up -d
# 打开 http://localhost:8080
```

## Core Concepts

- **Group** - A tracked topic, e.g., "WeChat Store". Has its own collection schedule and configuration.
- **Source** - Creators or keywords under a group. `creator` type fetches the creator's works; `keyword` type searches by keyword.
- **Task** - Asynchronous execution unit (collection/research/transcription completion), with progress logs and cancel support.
- **Report** - Output markdown briefing (scheduled daily / on-demand research).
- **Signal** - Insight judgment contributed by each piece of content: new idea or repetition.
- **Profile** - Continuously updated insight archive for each creator (filesystem-based, group-level).

## Usage Workflow

1. Open the Web UI → "Subscribe to New Topic" to create a group
2. Enter the topic page → Add Douyin creators (`sec_user_id`) or keywords
3. The system automatically collects → transcribes → fetches comments → evaluates insights → generates daily reports according to the schedule
4. Read conclusions in "Today's Briefing" and see what's new from creators in "New Signals This Issue" on the homepage
5. Have ad-hoc questions → Ask directly in the homepage follow-up bar; the system searches content and answers with evidence

## CLI (For Debugging)

```bash
python -m app.cli serve --reload          # 启动服务
python -m app.cli groups                  # 列知识组
python -m app.cli sources <slug>          # 列组下源
python -m app.cli run <slug>              # 手动跑一次采集+分析
python -m app.cli search douyin "关键词"   # 直接搜抖音（调试）
python -m app.cli research "问题"         # 按需研究（阻塞，调试）
python -m app.cli migrate                 # 数据迁移
```

## Adding New Platforms

Create a new file under `app/platforms/`, inherit from `PlatformAdapter`, declare `capabilities()`, and implement the corresponding methods:

```python
from app.platforms.base import PlatformAdapter, Capability

class XiaohongshuAdapter(PlatformAdapter):
    platform = "xiaohongshu"

    def capabilities(self) -> set[Capability]:
        return {Capability.SEARCH, Capability.FETCH_COMMENTS}

    def search(self, query, limit=20, days=7):
        ...
```

Register it in the `_adapters` list in `app/platforms/__init__.py`.

## Development

```bash
# 跑测试
pytest

# API 文档
# 启动后访问 http://localhost:8080/docs
```

## License

MIT
