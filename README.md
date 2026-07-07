# 听风 (cortex) - 你的行业听风者

自动监控一批内容创作者，下载视频、语音转文字、用 AI 提炼观点。带记忆：能判断博主这次讲的是**新观点**还是**老调重弹**，让你只看真正变化。

## 特性

- 🧠 **观点记忆** - 每个博主维护一份持续更新的观点档案，自动过滤重复内容
- 🆕 **新信号识别** - 新视频进来先比对档案，是"新的"才进日报重点
- 🎥 **自动采集** - 多平台（抖音已支持，更多开发中），基于视频 ID 去重
- 🎤 **语音转文字** - 阿里云百炼 ASR
- 🔍 **按需研究** - 临时提问，系统自动搜内容、转录、用证据回答
- ⏰ **定时调度** - APScheduler 按知识组触发，组内多源并行
- 🌐 **Web 界面** - FastAPI + React SPA，浏览器里完成一切

## 架构

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

## 安装

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

## 配置

复制 `.env.example` 为 `.env`：

```bash
cp .env.example .env
```

需要的环境变量：

| 配置项 | 说明 |
|--------|------|
| `TIKHUB_API_KEY` | 抖音 API（https://api.tikhub.io） |
| `BAILIAN_API_KEY` | 阿里云百炼（语音识别） |
| `ALIYUN_ACCESS_KEY_ID` / `ALIYUN_ACCESS_KEY_SECRET` | 阿里云 AK/SK |
| `ALIYUN_STS_ROLE_ARN` / `OSS_BUCKET` / `OSS_REGION` | OSS 转录用 |
| `LLM_API_KEY` / `LLM_BASE_URL` / `LLM_MODEL` | LLM（默认 DeepSeek，可在 Web 设置页改） |

> `DEEPSEEK_API_KEY` / `DEEPSEEK_API_URL` 老字段仍兼容（`LLM_*` 没配时回退）。

LLM、采集参数、prompt 模板都可在 **Web 设置页**热改，不用重启。

## 运行

### 开发模式（前后端分离）

```bash
# 后端（终端 1）
uvicorn app.main:app --reload --port 8080

# 前端（终端 2，自动代理 /api 到 8080）
cd frontend && npm run dev
# 打开 http://localhost:5173
```

### 生产模式（前端构建后由 FastAPI 托管）

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

## 核心概念

- **知识组（Group）** - 一个关注主题，如"微信小店"。有自己的采集节奏和配置
- **订阅源（Source）** - 组下的创作者或关键词。`creator` 类型拉博主作品，`keyword` 类型按词搜索
- **任务（Task）** - 异步执行单元（采集/研究/转录补全），有进度日志、可取消
- **报告（Report）** - 产出的 markdown 简报（定时日报 / 按需研究）
- **信号（Signal）** - 每条内容贡献的观点判定：新观点还是老调重弹
- **观点档案（Profile）** - 每个博主持续更新的观点沉淀（文件系统，group 级）

## 使用流程

1. 打开 Web 界面 → 「订阅新专题」创建知识组
2. 进专题页 → 添加抖音博主（sec_user_id）或关键词
3. 系统按节奏自动采集 → 转录 → 抓评论 → 观点判定 → 生成日报
4. 首页「今日简报」读结论，「本期新信号」看博主讲了什么新的
5. 临时有问题 → 首页追问栏直接提问，系统搜内容、用证据回答

## CLI（调试用）

```bash
python -m app.cli serve --reload          # 启动服务
python -m app.cli groups                  # 列知识组
python -m app.cli sources <slug>          # 列组下源
python -m app.cli run <slug>              # 手动跑一次采集+分析
python -m app.cli search douyin "关键词"   # 直接搜抖音（调试）
python -m app.cli research "问题"         # 按需研究（阻塞，调试）
python -m app.cli migrate                 # 数据迁移
```

## 添加新平台

在 `app/platforms/` 下新建文件，继承 `PlatformAdapter`，声明 `capabilities()` 并实现对应方法：

```python
from app.platforms.base import PlatformAdapter, Capability

class XiaohongshuAdapter(PlatformAdapter):
    platform = "xiaohongshu"

    def capabilities(self) -> set[Capability]:
        return {Capability.SEARCH, Capability.FETCH_COMMENTS}

    def search(self, query, limit=20, days=7):
        ...
```

在 `app/platforms/__init__.py` 的 `_adapters` 注册即可。

## 开发

```bash
# 跑测试
pytest

# API 文档
# 启动后访问 http://localhost:8080/docs
```

## License

MIT
