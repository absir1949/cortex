"""三层配置合并：source 覆盖 group 覆盖系统默认

配置项分类：
  - 系统级 secrets（API key 等）：从 settings（env）读取，不可 UI 修改
  - 系统级 runtime（LLM model / temperature / prompt / 采集默认）：DB settings 表
  - 知识组级：group.defaults + group.prompt_overrides
  - 源级：source 字段（interval_hours / days / content_limit / comment_top_n）

所有 Service 调用 effective_for_source(source_id) 或 effective_for_group(group_id)
拿到最终可用配置字典，不用关心层级。
"""
from __future__ import annotations
from typing import Any, Optional

from app.db.engine import get_session
from app.db.repos import ConfigRepo, GroupRepo, SourceRepo
from app.settings import settings
from app.llm.base import LLMConfig


# ============ 系统级默认值（DB 没配时回退到这里） ============

SYSTEM_DEFAULTS: dict[str, Any] = {
    # 采集
    "content_limit": 50,
    "days": 7,
    "interval_hours": 48,
    "comment_top_n": 20,
    # 转录
    "transcribe_enabled": True,
    "transcribe_model": "paraformer-v2",
    # LLM（敏感的 api_key 默认从 env 读）
    "llm_base_url": "https://api.deepseek.com/v1",
    "llm_model": "deepseek-chat",
    "llm_temperature": 0.3,
    "llm_max_tokens": 4096,
    # 研究
    "research_timeout_sec": 900,
    "research_search_limit": 10,
    # prompt
    "analysis_prompt_template": (
        "以下是电商创作者「{creator_name}」最近发布的 {content_count} 条短视频内容。\n\n"
        "请仔细阅读，输出一份详细的知识整理。要求：\n"
        "1. 不要过度概括，保留具体数字、方法、操作步骤\n"
        "2. 按话题分段整理，每个话题下列出具体做法和观点\n"
        "3. 特别注意踩坑经历、反常识做法、具体参数\n"
        "4. 如果提到具体工具、软件、平台规则变化，原样记录\n"
        "5. 用中文输出，不要输出 JSON\n\n"
        "[博主原话]\n{transcripts_block}\n\n"
        "[观众评论]\n{comments_block}"
    ),
    "research_prompt_template": (
        "用户问题：{question}\n\n"
        "下面是从抖音采集到的相关视频转录和评论。请基于这些证据回答问题，"
        "要求：\n"
        "1. 只基于提供的证据作答，不虚构\n"
        "2. 标注信息来源（哪个视频 URL / 哪条评论）\n"
        "3. 如有不同观点或矛盾，分别呈现\n"
        "4. 如证据不足以回答，直接说明\n\n"
        "{evidence_block}"
    ),
}


# ============ 内存缓存 ============

_cache: dict[str, Any] = {}
_cache_loaded = False


def invalidate_cache() -> None:
    global _cache, _cache_loaded
    _cache = {}
    _cache_loaded = False


def _load_cache() -> dict[str, Any]:
    global _cache, _cache_loaded
    if _cache_loaded:
        return _cache
    with get_session() as s:
        repo = ConfigRepo(s)
        items = repo.get_all()
    # 从 env 填充敏感字段（只有 DB 里没显式配置才用）
    if "llm_api_key" not in items and settings.llm_api_key:
        items["llm_api_key"] = settings.llm_api_key
    _cache = items
    _cache_loaded = True
    return _cache


# ============ 核心 API ============

def system_value(key: str, default: Any = None) -> Any:
    """查询系统级配置：DB → env fallback → SYSTEM_DEFAULTS → caller default"""
    cache = _load_cache()
    if key in cache:
        return cache[key]
    if key in SYSTEM_DEFAULTS:
        return SYSTEM_DEFAULTS[key]
    return default


def set_system_value(key: str, value: Any) -> None:
    with get_session() as s:
        ConfigRepo(s).set(key, value)
    invalidate_cache()


def set_system_values(items: dict[str, Any]) -> None:
    with get_session() as s:
        ConfigRepo(s).set_many(items)
    invalidate_cache()


def all_system_values(*, redact_secrets: bool = True) -> dict[str, Any]:
    """返回合并后的系统级配置（SYSTEM_DEFAULTS 被 DB 覆盖）"""
    merged = {**SYSTEM_DEFAULTS}
    merged.update(_load_cache())
    if redact_secrets:
        for k in ("llm_api_key",):
            if merged.get(k):
                v = str(merged[k])
                merged[k] = v[:4] + "****" + v[-4:] if len(v) > 10 else "****"
    return merged


def effective_for_group(group_id: int) -> dict[str, Any]:
    """系统级 + 组级覆盖"""
    with get_session() as s:
        group = GroupRepo(s).get(group_id)
    merged: dict[str, Any] = {**SYSTEM_DEFAULTS}
    merged.update(_load_cache())
    if group:
        merged.update(group.defaults or {})
        prompt_over = group.prompt_overrides or {}
        for k, v in prompt_over.items():
            merged[k] = v
    return merged


def effective_for_source(source_id: int) -> dict[str, Any]:
    """系统级 + 组级 + 源级覆盖"""
    with get_session() as s:
        src = SourceRepo(s).get(source_id)
    if not src:
        return {**SYSTEM_DEFAULTS, **_load_cache()}
    merged = effective_for_group(src.group_id)
    for field in ("interval_hours", "days", "content_limit", "comment_top_n"):
        val = getattr(src, field, None)
        if val is not None:
            merged[field] = val
    return merged


def get_llm_config() -> LLMConfig:
    """构造当前 LLM 配置"""
    cfg = all_system_values(redact_secrets=False)
    return LLMConfig(
        base_url=cfg.get("llm_base_url") or settings.llm_base_url,
        api_key=cfg.get("llm_api_key") or settings.llm_api_key,
        model=cfg.get("llm_model") or settings.llm_model,
        temperature=float(cfg.get("llm_temperature", 0.3)),
        max_tokens=int(cfg.get("llm_max_tokens", 4096)),
    )


def prompt(name: str) -> str:
    """拿 prompt 模板"""
    cfg = all_system_values(redact_secrets=False)
    return cfg.get(name) or SYSTEM_DEFAULTS.get(name, "")


def set_prompt(name: str, content: str) -> None:
    """改 prompt 模板（会保留历史）"""
    from app.db.schema import PromptHistory
    old = prompt(name)
    with get_session() as s:
        if old and old != content:
            s.add(PromptHistory(name=name, content=old))
            s.commit()
    set_system_value(name, content)
