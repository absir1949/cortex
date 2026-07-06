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
    # 观点去重
    "signal_min_new_points": 1,   # 至少提取到几个新观点才算「新信号」
    # 跨博主洞察
    "insight_lookback_days": 14,  # 趋势回看天数
    "insight_min_sources": 2,     # 至少几个博主同时讲才算趋势
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
    # 观点判定：拿博主现有档案当上下文，判断这条内容是「新观点」还是「老调重弹」
    "signal_judge_prompt_template": (
        "你是电商行业分析师。下面是创作者「{author}」的一条新视频内容，"
        "以及该作者此前的「观点档案」（记录了他讲过的所有观点）。\n\n"
        "请判断：这条视频讲的观点，是否已经在档案里出现过？\n\n"
        "判定规则：\n"
        "- 换个说法但本质相同的观点 = 已出现（如\"选品最重要\"和\"选品决定80%成败\"是同一条）\n"
        "- 有新的数据、新的方法、新的案例、立场转变 = 新观点\n"
        "- 完全没在档案里出现过的观点 = 新观点\n\n"
        "[作者观点档案]\n{profile}\n\n"
        "[本条视频原话]\n{transcript}\n\n"
        "[观众评论摘要]\n{comments}\n\n"
        "请严格按以下 JSON 格式输出（不要输出任何其他内容，不要 markdown 代码块）：\n"
        "{{\n"
        '  "summary": "用一句话概括这条视频的核心观点",\n'
        '  "is_new": true或false,\n'
        '  "matched_points": ["命中的已有观点，每条一行。空则 []"],\n'
        '  "new_points": ["本次新贡献的观点，每条一行。空则 []"\n'
        "}}"
    ),
    # 档案更新：把新观点合并进现有档案
    "profile_update_prompt_template": (
        "你是电商行业分析师。创作者「{author}」发布了新内容，产生了若干新观点。"
        "请把这些新观点合并进他的现有观点档案。\n\n"
        "更新规则：\n"
        "1. 保留档案原有结构（核心方法论 / 反复强调 / 最近转变 / 已讲过的点）\n"
        "2. 新观点归入最合适的段落；如果有观点升级/转变，标注日期\n"
        "3. 「反复强调」段落记录观点出现次数\n"
        "4. 不要删除已有内容，只做增量合并\n"
        "5. 输出完整的更新后档案（markdown），不要输出解释\n\n"
        "[现有档案]\n{profile}\n\n"
        "[本次新观点]\n{new_points}\n\n"
        "[本次内容摘要]\n{summary}\n\n"
        "[日期]\n{date}"
    ),
    # 分批整理后的合并：把多份分批整理 reduce 成一份连贯总结
    "analysis_merge_prompt_template": (
        "下面是对创作者「{creator_name}」内容的 {batch_count} 份分批整理（因为内容多，分批处理后需要合并）。"
        "请把它们合并成一份连贯的知识整理。\n\n"
        "要求：\n"
        "1. 去重：相同观点只保留一次，保留更详细的版本\n"
        "2. 按话题重组：把分散在各批里的同一话题合并到一起\n"
        "3. 保留所有具体数字、方法、操作步骤、踩坑经历\n"
        "4. 输出一份完整的整理，不要分批痕迹、不要「第X批」字样\n"
        "5. 用中文输出\n\n"
        "[各批整理结果]\n{parts_block}"
    ),
    # 跨博主趋势提炼：把多个博主的新观点放一起，找出共同趋势
    "insight_prompt_template": (
        "你是电商行业分析师。下面是「{group_name}」这个专题下，"
        "多位创作者最近 {days} 天内的所有新观点（已按博主分组）。\n\n"
        "请找出**被多个博主同时提到的共同趋势**——这些往往是正在形成的行业信号。\n\n"
        "分析规则：\n"
        "1. 只保留被至少 {min_sources} 个博主讲到的观点（单一博主的观点不算趋势）\n"
        "2. 把本质相同的观点合并成一条趋势（如「选品重要」和「选品决定成败」是同一条）\n"
        "3. 判断每条趋势的势头：↗ 升温（最近提到变多）/ → 稳定 / ↘ 降温\n"
        "4. 简要说明为什么这条值得注意（业务含义）\n"
        "5. 如果没有共同趋势，返回空 trends 数组\n\n"
        "[各博主的新观点]\n{signals_block}\n\n"
        "请严格按以下 JSON 格式输出（不要输出任何其他内容，不要 markdown 代码块）：\n"
        "{{\n"
        '  "trends": [\n'
        "    {{\n"
        '      "trend": "趋势名称，一句话",\n'
        '      "source_names": ["讲到这个趋势的博主名"],\n'
        '      "signal_count": 讲到这个趋势的信号总数(整数),\n'
        '      "momentum": "↗ 升温 / → 稳定 / ↘ 降温",\n'
        '      "why_hot": "为什么值得关注"\n'
        "    }}\n"
        "  ]\n"
        "}}"
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


def system_int(key: str, default: int) -> int:
    """安全取整型配置：转换失败（用户配了非法值）时回退到 default，不抛异常。

    用于 signal_min_new_points / insight_lookback_days / insight_min_sources 等，
    这些值若配错会让已付费的 LLM 调用白费，必须容错。
    """
    val = system_value(key, default)
    try:
        if isinstance(val, bool):
            return int(val)
        if isinstance(val, (int, float)):
            return int(val)
        return int(str(val).strip())
    except (TypeError, ValueError):
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
