"""Phase 3 冒烟测试：service 层 CRUD + config 三层合并"""
from __future__ import annotations
import pytest

from app.services.group_service import GroupService
from app.services.source_service import SourceService
from app.services import config_service
from app.models.group import SourceType


def test_group_service_crud():
    svc = GroupService()
    g = svc.create("微信小店", slug="wechat-shop", defaults={"interval_hours": 24})
    assert g.id is not None
    assert g.slug == "wechat-shop"
    assert g.defaults["interval_hours"] == 24

    got = svc.get_by_slug("wechat-shop")
    assert got.name == "微信小店"

    updated = svc.update(g.id, description="test")
    assert updated.description == "test"

    # 重复 slug 报错
    with pytest.raises(ValueError):
        svc.create("微信小店2", slug="wechat-shop")


def test_source_service_crud_and_directory_auto():
    g_svc = GroupService()
    s_svc = SourceService()
    g = g_svc.create("组1", slug="g1")

    src = s_svc.create(
        g.id,
        type=SourceType.CREATOR,
        platform="douyin",
        identifier="MS4w_xxx",
        display_name="狼教授",
    )
    assert src.directory.startswith("g1/creator-")
    assert src.group_id == g.id

    # 重复识别符报错
    with pytest.raises(ValueError):
        s_svc.create(g.id, type="creator", platform="douyin", identifier="MS4w_xxx", display_name="dup")

    # 关键词源
    kw = s_svc.create(
        g.id,
        type=SourceType.KEYWORD,
        platform="douyin",
        identifier="微信小店",
        display_name="微信小店",
    )
    assert kw.type == SourceType.KEYWORD.value
    assert kw.directory.startswith("g1/keyword-")

    all_sources = s_svc.list_by_group(g.id)
    assert len(all_sources) == 2


def test_config_three_layer_merge():
    """source 级 > group 级 > system 级"""
    config_service.invalidate_cache()

    g_svc = GroupService()
    s_svc = SourceService()

    g = g_svc.create(
        "组",
        slug="g-cfg",
        defaults={"interval_hours": 24, "comment_top_n": 50},
    )
    src_inherit = s_svc.create(
        g.id, type="creator", platform="douyin", identifier="inherit", display_name="A"
    )
    src_override = s_svc.create(
        g.id, type="creator", platform="douyin", identifier="override", display_name="B",
        comment_top_n=5,
    )

    # 系统默认
    assert config_service.SYSTEM_DEFAULTS["interval_hours"] == 48
    assert config_service.SYSTEM_DEFAULTS["comment_top_n"] == 20

    # 组覆盖
    g_cfg = config_service.effective_for_group(g.id)
    assert g_cfg["interval_hours"] == 24
    assert g_cfg["comment_top_n"] == 50

    # 源继承组
    a_cfg = config_service.effective_for_source(src_inherit.id)
    assert a_cfg["comment_top_n"] == 50
    assert a_cfg["interval_hours"] == 24

    # 源覆盖
    b_cfg = config_service.effective_for_source(src_override.id)
    assert b_cfg["comment_top_n"] == 5  # 源覆盖组
    assert b_cfg["interval_hours"] == 24  # 没覆盖，走组


def test_set_system_value_and_cache_invalidation():
    config_service.invalidate_cache()
    # 读默认
    assert config_service.system_value("llm_model") == "deepseek-chat"
    # 改
    config_service.set_system_value("llm_model", "gpt-4o-mini")
    assert config_service.system_value("llm_model") == "gpt-4o-mini"


def test_set_prompt_saves_history():
    from app.db.engine import get_session
    from sqlmodel import select
    from app.db.schema import PromptHistory

    config_service.invalidate_cache()
    original = config_service.prompt("analysis_prompt_template")
    assert "{creator_name}" in original

    config_service.set_prompt("analysis_prompt_template", "NEW {creator_name}")
    assert config_service.prompt("analysis_prompt_template") == "NEW {creator_name}"

    # 历史应有一条
    with get_session() as s:
        history = s.exec(select(PromptHistory).where(PromptHistory.name == "analysis_prompt_template")).all()
    assert len(history) >= 1
    assert "{creator_name}" in history[0].content


def test_llm_config_from_settings():
    config_service.invalidate_cache()
    config_service.set_system_values({
        "llm_base_url": "https://api.example.com/v1",
        "llm_model": "custom-model",
        "llm_temperature": 0.9,
    })
    cfg = config_service.get_llm_config()
    assert cfg.base_url == "https://api.example.com/v1"
    assert cfg.model == "custom-model"
    assert cfg.temperature == 0.9


def test_all_system_values_redacts_secrets():
    config_service.invalidate_cache()
    config_service.set_system_value("llm_api_key", "sk-abcdefghij1234567890")
    view = config_service.all_system_values(redact_secrets=True)
    assert view["llm_api_key"] != "sk-abcdefghij1234567890"
    assert "****" in view["llm_api_key"]

    raw = config_service.all_system_values(redact_secrets=False)
    assert raw["llm_api_key"] == "sk-abcdefghij1234567890"
