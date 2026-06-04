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


class GroupDetailResp(GroupResp):
    sources: list[SourceBrief] = Field(default_factory=list)


# ---------- Sources ----------

class SourceCreateReq(BaseModel):
    type: str                             # creator / keyword
    platform: str = "douyin"
    identifier: str
    display_name: str = ""
    interval_hours: Optional[int] = None
    days: Optional[int] = None
    content_limit: Optional[int] = None
    comment_top_n: Optional[int] = None
    resolve_creator: bool = True


# ---------- Research ----------

class ResearchReq(BaseModel):
    question: str
    platforms: Optional[list[str]] = None
    days: int = 7
    search_limit: Optional[int] = None
    comment_top_n: Optional[int] = None


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
