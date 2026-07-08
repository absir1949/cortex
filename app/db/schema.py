"""持久化表定义 - SQLModel

表：
  knowledge_groups   知识组
  creators           博主（跨平台聚合的全局身份）
  creator_aliases    博主的平台账号映射（platform+uid → creator）
  sources            订阅源（组 × 平台账号，关联到 creator）
  settings           系统级 runtime 配置（key-value JSON）
  tasks              异步任务
  reports            产出报告元数据（正文在文件系统）
  refresh_runs       一次作者/专题刷新的运行记录与阶段统计
  content_items      每条内容的处理状态（水位、失败、补跑依据）
  analyzed_content   已分析过的 content_id（增量分析，替代 .analyzed.json）
  signals            每条内容的观点判定（新观点/老调重弹）+ 提炼的新观点
  ask_conversations  问听风专题内对话
  ask_messages       问听风对话消息
  prompt_history     prompt 修改历史（保留版本）
  schema_version     迁移版本号
"""
from __future__ import annotations
from datetime import datetime
from typing import Optional
from sqlalchemy import JSON, ForeignKey, UniqueConstraint
from sqlmodel import Field, SQLModel, Column


# ---------- 知识组 ----------

class KnowledgeGroup(SQLModel, table=True):
    __tablename__ = "knowledge_groups"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    slug: str = Field(unique=True, index=True)  # 目录名用
    description: str = ""
    enabled: bool = Field(default=True)

    # JSON 配置
    defaults: dict = Field(default_factory=dict, sa_column=Column(JSON))
    prompt_overrides: dict = Field(default_factory=dict, sa_column=Column(JSON))

    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now().isoformat())


# ---------- 博主（跨平台聚合的全局身份）----------

class Creator(SQLModel, table=True):
    """博主的全局身份——一个真人跨多个平台、被多个组关注时，只有一条记录。

    Source 通过 creator_id 关联到这里；观点档案按 creator_id 存文件，
    同一博主无论被几个组关注都共用一份档案。
    """
    __tablename__ = "creators"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)             # 统一显示名
    slug: str = Field(unique=True, index=True)  # URL / 文件名用
    bio: str = ""                             # 简介（未来抓取填充）
    avatar_url: str = ""                      # 头像（未来抓取填充）
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())


class CreatorAlias(SQLModel, table=True):
    """博主的平台账号映射：(platform, platform_uid) → creator_id

    创建 source 时按此表查：命中则关联已有 creator，未命中则新建 creator + alias。
    实现跨平台聚合与跨组去重。
    """
    __tablename__ = "creator_aliases"
    __table_args__ = (
        UniqueConstraint("platform", "platform_uid", name="uq_creator_alias"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    creator_id: int = Field(foreign_key="creators.id", index=True)
    platform: str = Field(index=True)         # douyin / wechat / xhs
    platform_uid: str = Field(index=True)     # 该平台唯一 ID（如抖音 sec_uid）
    display_name: str = ""                    # 该平台的昵称（可能与 creator.name 不同）
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())


# ---------- 订阅源 ----------

class Source(SQLModel, table=True):
    __tablename__ = "sources"
    __table_args__ = (UniqueConstraint("group_id", "platform", "identifier", name="uq_source_key"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    group_id: int = Field(foreign_key="knowledge_groups.id", index=True)

    # 关联到全局博主身份（NULL = 尚未关联，keyword 类型永远 NULL）
    creator_id: Optional[int] = Field(default=None, foreign_key="creators.id", index=True)

    type: str = Field(index=True)             # creator / keyword
    platform: str = Field(index=True)         # douyin / ...
    identifier: str                           # creator_id 或 keyword
    display_name: str = ""

    enabled: bool = Field(default=True)

    # 运行参数覆盖（NULL 表示继承组/系统默认）
    interval_hours: Optional[int] = None
    days: Optional[int] = None
    content_limit: Optional[int] = None
    comment_top_n: Optional[int] = None

    # 存储路径（相对 data_dir）
    directory: str

    last_check: Optional[str] = None          # ISO 8601
    last_error: Optional[str] = None
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())


# ---------- 系统配置 ----------

class SettingKV(SQLModel, table=True):
    """系统级 runtime 配置 - key/value JSON"""
    __tablename__ = "settings"

    key: str = Field(primary_key=True)
    value: dict = Field(default_factory=dict, sa_column=Column(JSON))
    updated_at: str = Field(default_factory=lambda: datetime.now().isoformat())


# ---------- 异步任务 ----------

class Task(SQLModel, table=True):
    __tablename__ = "tasks"

    id: str = Field(primary_key=True)         # UUID hex
    kind: str = Field(index=True)             # ingest / research / transcribe_backfill
    status: str = Field(index=True)           # pending / running / succeeded / failed / canceled

    group_id: Optional[int] = Field(default=None, foreign_key="knowledge_groups.id", index=True)
    source_id: Optional[int] = Field(default=None, foreign_key="sources.id", index=True)

    params: dict = Field(default_factory=dict, sa_column=Column(JSON))
    progress: dict = Field(default_factory=dict, sa_column=Column(JSON))
    logs: list = Field(default_factory=list, sa_column=Column(JSON))
    result: dict = Field(default_factory=dict, sa_column=Column(JSON))
    error: Optional[str] = None

    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    started_at: Optional[str] = None
    finished_at: Optional[str] = None


# ---------- 报告 ----------

class Report(SQLModel, table=True):
    __tablename__ = "reports"

    id: Optional[int] = Field(default=None, primary_key=True)
    group_id: Optional[int] = Field(default=None, foreign_key="knowledge_groups.id", index=True)
    task_id: Optional[str] = Field(default=None, foreign_key="tasks.id", index=True)

    kind: str = Field(index=True)             # scheduled / research
    title: str
    summary: str = ""                         # 前 200 字摘要

    content_md_path: str
    content_json_path: Optional[str] = None

    sources_used: list = Field(default_factory=list, sa_column=Column(JSON))

    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())


# ---------- 刷新运行记录 ----------

class RefreshRun(SQLModel, table=True):
    """一次刷新动作的运行水位。

    scope=source 表示单作者刷新；scope=group 表示专题刷新。
    专题刷新下会创建一个 group run，并为每个 source 创建子 run。
    """
    __tablename__ = "refresh_runs"

    id: Optional[int] = Field(default=None, primary_key=True)
    scope: str = Field(index=True)                  # group / source
    mode: str = Field(default="refresh", index=True)  # refresh / repair / rebuild_report
    status: str = Field(default="running", index=True)  # running / succeeded / partial_failed / failed / canceled

    parent_run_id: Optional[int] = Field(default=None, index=True)
    task_id: Optional[str] = Field(default=None, foreign_key="tasks.id", index=True)
    group_id: Optional[int] = Field(default=None, foreign_key="knowledge_groups.id", index=True)
    source_id: Optional[int] = Field(default=None, foreign_key="sources.id", index=True)
    lookback_days: Optional[int] = None

    counts: dict = Field(default_factory=dict, sa_column=Column(JSON))
    errors: list = Field(default_factory=list, sa_column=Column(JSON))

    started_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    finished_at: Optional[str] = None
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())


# ---------- 内容处理状态 ----------

class ContentItem(SQLModel, table=True):
    """订阅源下某条内容的处理状态。

    文件是否存在只是证据之一；真正的刷新逻辑以这些阶段状态为准。
    """
    __tablename__ = "content_items"
    __table_args__ = (UniqueConstraint("source_id", "content_id", name="uq_content_item"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    group_id: Optional[int] = Field(default=None, foreign_key="knowledge_groups.id", index=True)
    source_id: int = Field(foreign_key="sources.id", index=True)
    creator_id: Optional[int] = Field(default=None, foreign_key="creators.id", index=True)

    platform: str = Field(index=True)
    content_id: str = Field(index=True)
    content_type: str = ""
    title: str = ""
    author_id: str = ""
    author_name: str = ""
    url: str = ""
    create_time: str = Field(default="", index=True)

    first_seen_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    last_seen_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now().isoformat())

    media_status: str = Field(default="pending", index=True)
    transcript_status: str = Field(default="pending", index=True)
    comments_status: str = Field(default="pending", index=True)
    signal_status: str = Field(default="pending", index=True)
    profile_status: str = Field(default="pending", index=True)

    media_error: Optional[str] = None
    transcript_error: Optional[str] = None
    comments_error: Optional[str] = None
    signal_error: Optional[str] = None
    profile_error: Optional[str] = None

    file_size: int = 0
    statistics: dict = Field(default_factory=dict, sa_column=Column(JSON))


# ---------- 增量分析追踪 ----------

class AnalyzedContent(SQLModel, table=True):
    """替代 .analyzed.json - 追踪每个源已分析过的 content_id"""
    __tablename__ = "analyzed_content"
    __table_args__ = (UniqueConstraint("source_id", "content_id", name="uq_analyzed"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    source_id: int = Field(foreign_key="sources.id", index=True)
    content_id: str = Field(index=True)
    analyzed_at: str = Field(default_factory=lambda: datetime.now().isoformat())


# ---------- 观点信号（去重判定结果）----------

class Signal(SQLModel, table=True):
    """每条内容贡献的观点判定结果

    采集时逐条由 SignalService 产出：
      is_new=True  → 这条内容带来了新观点，进日报重点
      is_new=False → 老调重弹，不进日报重点
    new_points / matched_points 是 LLM 给出的结构化判定依据。
    """
    __tablename__ = "signals"
    __table_args__ = (UniqueConstraint("source_id", "content_id", name="uq_signal_content"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    group_id: Optional[int] = Field(default=None, foreign_key="knowledge_groups.id", index=True)
    source_id: int = Field(foreign_key="sources.id", index=True)
    content_id: str = Field(index=True)

    is_new: bool = Field(default=False, index=True)
    summary: str = ""                            # 这条内容的观点一句话摘要
    matched_points: list = Field(default_factory=list, sa_column=Column(JSON))  # 命中的已有观点（去重证据）
    new_points: list = Field(default_factory=list, sa_column=Column(JSON))      # 本次贡献的新观点

    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())


# ---------- 问听风对话 ----------

class AskConversation(SQLModel, table=True):
    __tablename__ = "ask_conversations"

    id: Optional[int] = Field(default=None, primary_key=True)
    group_id: int = Field(
        sa_column=Column(ForeignKey("knowledge_groups.id", ondelete="CASCADE"), index=True, nullable=False),
    )
    title: str = ""
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now().isoformat())


class AskMessage(SQLModel, table=True):
    __tablename__ = "ask_messages"

    id: Optional[int] = Field(default=None, primary_key=True)
    conversation_id: int = Field(
        sa_column=Column(ForeignKey("ask_conversations.id", ondelete="CASCADE"), index=True, nullable=False),
    )
    role: str = Field(index=True)  # user / assistant
    content: str = ""
    evidence: list = Field(default_factory=list, sa_column=Column(JSON))
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())


# ---------- Prompt 历史 ----------

class PromptHistory(SQLModel, table=True):
    __tablename__ = "prompt_history"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)             # analysis_prompt_template / research_prompt_template
    content: str
    saved_at: str = Field(default_factory=lambda: datetime.now().isoformat())


# ---------- Schema 版本号 ----------

class SchemaVersion(SQLModel, table=True):
    __tablename__ = "schema_version"

    version: int = Field(primary_key=True)
    applied_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    note: str = ""
