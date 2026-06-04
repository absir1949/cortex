from __future__ import annotations
from fastapi import APIRouter, HTTPException

from app.api.schemas import ConfigUpdateReq, PromptUpdateReq
from app.services import config_service


router = APIRouter(prefix="/api/config", tags=["config"])


# 字段 schema（前端渲染表单用）
CONFIG_SCHEMA = {
    "content_limit": {"type": "int", "label": "单次采集数", "min": 1, "max": 200},
    "days": {"type": "int", "label": "采集时间范围（天）", "min": 1, "max": 365},
    "interval_hours": {"type": "int", "label": "定时间隔（小时）", "min": 1, "max": 720},
    "comment_top_n": {"type": "int", "label": "评论抓取数（每条）", "min": 0, "max": 100},
    "transcribe_enabled": {"type": "bool", "label": "启用转录"},
    "llm_base_url": {"type": "string", "label": "LLM Base URL",
                     "presets": {
                         "DeepSeek": "https://api.deepseek.com/v1",
                         "OpenAI": "https://api.openai.com/v1",
                         "Moonshot": "https://api.moonshot.cn/v1",
                         "Qwen": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                         "智谱(Coding)": "https://open.bigmodel.cn/api/coding/paas/v4",
                         "智谱(通用)": "https://open.bigmodel.cn/api/paas/v4",
                     }},
    "llm_api_key": {"type": "secret", "label": "LLM API Key"},
    "llm_model": {"type": "string", "label": "LLM Model"},
    "llm_temperature": {"type": "float", "label": "Temperature", "min": 0.0, "max": 2.0},
    "llm_max_tokens": {"type": "int", "label": "Max Tokens", "min": 256, "max": 32768},
    "research_timeout_sec": {"type": "int", "label": "研究超时（秒）", "min": 60, "max": 7200},
    "research_search_limit": {"type": "int", "label": "研究搜索数", "min": 1, "max": 50},
}


@router.get("")
def get_config():
    return {
        "values": config_service.all_system_values(redact_secrets=True),
        "schema": CONFIG_SCHEMA,
    }


@router.patch("")
def update_config(req: ConfigUpdateReq):
    # 过滤：只能改 schema 里有的字段 + prompt 模板
    allowed = set(CONFIG_SCHEMA.keys()) | {"analysis_prompt_template", "research_prompt_template"}
    filtered = {k: v for k, v in req.values.items() if k in allowed}
    # secret 脱敏 **** 表示未改，跳过
    for k, v in list(filtered.items()):
        if CONFIG_SCHEMA.get(k, {}).get("type") == "secret":
            if isinstance(v, str) and "****" in v:
                filtered.pop(k)
                continue
            # secret 必须是单行 ASCII，防止粘贴错误（比如粘贴了 traceback）
            if isinstance(v, str):
                v = v.strip()
                if not v.isascii():
                    raise HTTPException(400, f"{k} 必须是 ASCII（不能有中文/emoji）")
                if len(v) > 256:
                    raise HTTPException(400, f"{k} 长度异常（{len(v)} 字符，上限 256）")
                if any(c in v for c in "\n\r\t "):
                    raise HTTPException(400, f"{k} 不能包含空格/换行/制表符")
                filtered[k] = v
    config_service.set_system_values(filtered)
    return {
        "values": config_service.all_system_values(redact_secrets=True),
        "schema": CONFIG_SCHEMA,
    }


@router.get("/prompts")
def list_prompts():
    return {
        "analysis_prompt_template": config_service.prompt("analysis_prompt_template"),
        "research_prompt_template": config_service.prompt("research_prompt_template"),
    }


@router.patch("/prompts/{name}")
def update_prompt(name: str, req: PromptUpdateReq):
    if name not in ("analysis_prompt_template", "research_prompt_template"):
        raise HTTPException(400, "unknown prompt name")
    config_service.set_prompt(name, req.content)
    return {"ok": True, "content": req.content}
