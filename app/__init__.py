"""听风 (cortex) - 独立产品化升级版

架构说明：
- app/models/ — 数据模型（Pydantic + SQLModel）
- app/db/     — 持久层（SQLite，WAL 模式）
- app/services/ — 业务层（Service 层为中心，CLI 和 REST API 都是薄壳调用 Service）
- app/platforms/ — 平台适配器（能力契约 + 具体实现）
- app/llm/    — LLM 客户端（OpenAI 兼容层，可切 DeepSeek / OpenAI / Moonshot / 千问）
- app/tasks/  — 异步任务系统（ThreadPoolExecutor + SQLite 状态表）
- app/scheduler/ — APScheduler 按组触发定时订阅
- app/api/    — FastAPI REST 端点
- app/cli/    — 命令行薄壳
"""
