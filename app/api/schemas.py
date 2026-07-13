"""FastAPI 请求/响应 schema"""
from __future__ import annotations
from typing import Any, Optional
from pydantic import BaseModel, Field


# ---------- Groups ----------

class GroupCreateReq(BaseModel):
    name: str
    slug: Optional[str] = None
    description: str = ""
    defaults: dict = Field(default_factory=dict)
    prompt_overrides: dict = Field(default_factory=dict)


class GroupUpdateReq(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    enabled: Optional[bool] = None
    defaults: Optional[dict] = None
    prompt_overrides: Optional[dict] = None


class GroupResp(BaseModel):
    id: int
    name: str
    slug: str
    description: str = ""
    enabled: bool = True
    defaults: dict = Field(default_factory=dict)
    prompt_overrides: dict = Field(default_factory=dict)
    source_count: int = 0
    created_at: str = ""
    updated_at: str = ""


class GroupSummaryResp(GroupResp):
    recent_content_count: int = 0
    recent_signal_count: int = 0
    recent_new_signal_count: int = 0
    failed_source_count: int = 0
    window_days: int = 7


class SourceBrief(BaseModel):
    id: int
    type: str
    platform: str
    identifier: str
    display_name: str
    enabled: bool
    interval_hours: Optional[int] = None
    last_check: Optional[str] = None
    last_error: Optional[str] = None
    directory: str


class SourceSummary(SourceBrief):
    recent_content_count: int = 0
    recent_signal_count: int = 0
    recent_new_signal_count: int = 0
    window_days: int = 7


class GroupDetailResp(GroupResp):
    sources: list[SourceBrief] = Field(default_factory=list)


# ---------- Sources ----------

class SourceCreateReq(BaseModel):
    type: str                             # creator / keyword
    platform: str                         # douyin / wechat_channels / ...（必填，无默认）
    identifier: str
    display_name: str = ""
    interval_hours: Optional[int] = None
    days: Optional[int] = None
    content_limit: Optional[int] = None
    comment_top_n: Optional[int] = None
    resolve_creator: bool = True


class SourceUpdateReq(BaseModel):
    display_name: Optional[str] = None
    enabled: Optional[bool] = None
    interval_hours: Optional[int] = None
    days: Optional[int] = None
    content_limit: Optional[int] = None
    comment_top_n: Optional[int] = None


# ---------- Ask Tingfeng ----------

class GroupAskReq(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    use_internal: bool = True
    use_external: bool = False
    days: int = Field(default=365, ge=1, le=365)
    limit: int = Field(default=20, ge=1, le=30)
    platforms: list[str] = Field(default_factory=list)
    external_days: int = Field(default=7, ge=1, le=365)
    external_limit: int = Field(default=10, ge=1, le=50)
    comment_top_n: int = Field(default=20, ge=0, le=100)


class GroupAskEvidence(BaseModel):
    kind: str = "content"
    task_id: Optional[str] = None
    status: str = ""
    content_id: str = ""
    global_content_id: Optional[int] = None
    platform: str = ""
    source_id: Optional[int] = None
    author: str = ""
    title: str = ""
    url: str = ""
    create_time: str = ""
    signal_summary: str = ""
    new_points: list[str] = Field(default_factory=list)
    snippet: str = ""


class GroupAskResp(BaseModel):
    answer: str
    evidence: list[GroupAskEvidence] = Field(default_factory=list)
    scope: str = "internal"
    days: int
    evidence_count: int


class AskMessageResp(BaseModel):
    id: int
    role: str
    content: str
    evidence: list[GroupAskEvidence] = Field(default_factory=list)
    created_at: str


class AskConversationBrief(BaseModel):
    id: int
    group_id: int
    title: str
    latest_answer: str = ""
    evidence_count: int = 0
    message_count: int = 0
    created_at: str
    updated_at: str


class AskConversationDetail(BaseModel):
    id: int
    group_id: int
    title: str
    messages: list[AskMessageResp] = Field(default_factory=list)
    created_at: str
    updated_at: str


class TaskResp(BaseModel):
    id: str
    kind: str
    status: str
    group_id: Optional[int] = None
    source_id: Optional[int] = None
    params: dict = Field(default_factory=dict)
    progress: dict = Field(default_factory=dict)
    logs: list[dict] = Field(default_factory=list)
    result: dict = Field(default_factory=dict)
    error: Optional[str] = None
    created_at: str
    started_at: Optional[str] = None
    finished_at: Optional[str] = None


# ---------- Reports ----------

class ReportBrief(BaseModel):
    id: int
    group_id: Optional[int] = None
    task_id: Optional[str] = None
    kind: str
    title: str
    summary: str = ""
    created_at: str


class ReportDetail(ReportBrief):
    content_md: str = ""
    content_md_path: str
    content_json_path: Optional[str] = None
    sources_used: list[dict] = Field(default_factory=list)


# ---------- Config ----------

class ConfigUpdateReq(BaseModel):
    values: dict[str, Any]


class PromptUpdateReq(BaseModel):
    content: str
