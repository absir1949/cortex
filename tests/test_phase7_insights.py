"""Phase 7 测试：跨博主趋势提炼（InsightService + API + 报告含趋势段）

覆盖：
  - InsightService：信号不足返回 None、LLM 失败降级、JSON 解析、趋势阈值过滤
  - insight prompt + 配置项可读
  - insights API 端点
  - 报告 _write_report 含趋势段（mock LLM 端到端）
"""
from __future__ import annotations
import pytest
from pathlib import Path
from sqlmodel import Session

from app.db.engine import get_engine
from app.db.schema import KnowledgeGroup, Source, Signal
from app.db.repos import GroupRepo, SourceRepo, SignalRepo
from app.models.group import SourceType
from app.services.insight_service import InsightService
from app.services.knowledge_service import KnowledgeService


def _session() -> Session:
    return Session(get_engine())


@pytest.fixture(autouse=True)
def _isolated_knowledge_dir(tmp_path, monkeypatch):
    """重定向 knowledge_dir 到临时目录，避免污染"""
    from app.settings import settings
    monkeypatch.setattr(settings, "knowledge_dir", tmp_path / "knowledge")


def _make_group_with_sources(slug: str = "insight-test"):
    """造一个 group + 2 个 source，返回 (group_id, src1_id, src2_id)"""
    with _session() as s:
        group = GroupRepo(s).create(KnowledgeGroup(name="微信小店", slug=slug))
        src1 = SourceRepo(s).create(Source(
            group_id=group.id, type=SourceType.CREATOR.value, platform="douyin",
            identifier="a1", display_name="张三", directory=f"{slug}/a1",
        ))
        src2 = SourceRepo(s).create(Source(
            group_id=group.id, type=SourceType.CREATOR.value, platform="douyin",
            identifier="a2", display_name="李四", directory=f"{slug}/a2",
        ))
        return group.id, src1.id, src2.id


def _add_signal(source_id, group_id, content_id, summary, new_points, is_new=True):
    with _session() as s:
        SignalRepo(s).create(source_id, content_id, group_id=group_id,
                             is_new=is_new, summary=summary, new_points=new_points)


# ---------- 配置项 & prompt ----------

def test_insight_config_and_prompt():
    from app.services import config_service
    assert config_service.system_value("insight_lookback_days") == 14
    assert config_service.system_value("insight_min_sources") == 2
    p = config_service.prompt("insight_prompt_template")
    assert "{signals_block}" in p and "{min_sources}" in p


# ---------- InsightService 边界情况 ----------

def test_insight_returns_none_when_too_few_signals():
    """信号 <2 条直接返回 None，不调 LLM"""
    grp, s1, s2 = _make_group_with_sources()
    _add_signal(s1, grp, "c1", "单条观点", ["x"])
    svc = InsightService()
    # monkeypatch LLM 如果被调用就失败（证明没被调用）
    called = {"v": False}
    def fake_chat(msgs, *, config):
        called["v"] = True
        return '{"trends":[]}'
    svc.llm.chat = fake_chat
    result = svc.build_group_insights(grp, days=14)
    assert result is None
    assert called["v"] is False  # 没调 LLM


def test_insight_returns_none_on_llm_failure(monkeypatch):
    """LLM 失败 → 返回 None"""
    grp, s1, s2 = _make_group_with_sources()
    _add_signal(s1, grp, "c1", "观点A", ["私域转公域"])
    _add_signal(s2, grp, "c2", "观点B", ["私域转公域"])

    svc = InsightService()
    monkeypatch.setattr(svc.llm, "chat", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("挂了")))
    result = svc.build_group_insights(grp, days=14)
    assert result is None


def test_insight_finds_cross_source_trend(monkeypatch):
    """两个博主都讲同一观点 → LLM 聚类出趋势"""
    grp, s1, s2 = _make_group_with_sources()
    _add_signal(s1, grp, "c1", "张三讲私域", ["私域转公域", "选品"])
    _add_signal(s2, grp, "c2", "李四讲私域", ["私域转公域"])

    svc = InsightService()
    def fake_chat(msgs, *, config):
        return '{"trends":[{"trend":"私域转公域","source_names":["张三","李四"],"signal_count":2,"momentum":"↗ 升温","why_hot":"多人在讲"}]}'
    monkeypatch.setattr(svc.llm, "chat", fake_chat)

    result = svc.build_group_insights(grp, days=14)
    assert result is not None
    assert len(result["trends"]) == 1
    assert result["trends"][0]["trend"] == "私域转公域"
    assert set(result["trends"][0]["source_names"]) == {"张三", "李四"}


def test_insight_filters_below_min_sources(monkeypatch):
    """LLM 返回的趋势，博主数 < min_sources 的被过滤"""
    grp, s1, s2 = _make_group_with_sources()
    _add_signal(s1, grp, "c1", "A", ["观点1"])
    _add_signal(s2, grp, "c2", "B", ["观点2"])

    svc = InsightService()
    def fake_chat(msgs, *, config):
        # 一个双博主趋势 + 一个单博主趋势（应被过滤）
        return ('{"trends":['
                 '{"trend":"双博主趋势","source_names":["张三","李四"],"signal_count":2,"momentum":"→ 稳定","why_hot":""},'
                 '{"trend":"单博主","source_names":["只有张三"],"signal_count":1,"momentum":"→ 稳定","why_hot":""}'
                 ']}')
    monkeypatch.setattr(svc.llm, "chat", fake_chat)

    result = svc.build_group_insights(grp, days=14)
    assert result is not None
    assert len(result["trends"]) == 1  # 单博主那条被过滤
    assert result["trends"][0]["trend"] == "双博主趋势"


# ---------- JSON 解析（复用风格，确认 insight 的解析健壮）----------

def test_parse_json_variants():
    assert InsightService._parse_json('{"trends":[]}') == {"trends": []}
    assert InsightService._parse_json('```json\n{"trends":[]}\n```') == {"trends": []}
    assert InsightService._parse_json('结果：{"trends":[]} 完') == {"trends": []}
    assert InsightService._parse_json("无 json") is None


def test_build_signals_block_groups_by_source():
    by_source = {
        "张三": [{"new_points": ["A", "B"], "summary": "s", "created_at": "2026-07-01T10:00:00"}],
        "李四": [{"new_points": [], "summary": "兜底摘要", "created_at": "2026-07-02T10:00:00"}],
    }
    block = InsightService._build_signals_block(by_source)
    assert "张三" in block and "A" in block
    assert "李四" in block and "兜底摘要" in block  # 没 new_points 时用 summary 兜底


# ---------- insights API 端点 ----------

def test_insights_api_endpoint(monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app
    client = TestClient(app)

    grp, s1, s2 = _make_group_with_sources()
    _add_signal(s1, grp, "c1", "观点A", ["私域"])
    _add_signal(s2, grp, "c2", "观点B", ["私域"])

    # mock InsightService 返回趋势
    from app.services import insight_service
    orig = insight_service.InsightService

    class FakeInsight(orig):
        def build_group_insights(self, group_id, *, days=14):
            return {"trends": [{"trend": "测试趋势", "source_names": ["张三", "李四"],
                                "signal_count": 2, "momentum": "↗ 升温", "why_hot": ""}],
                    "raw_signal_count": 2, "days": days}
    monkeypatch.setattr(insight_service, "InsightService", FakeInsight)

    r = client.get(f"/api/groups/{grp}/insights?days=14")
    assert r.status_code == 200
    data = r.json()
    assert data["trends"][0]["trend"] == "测试趋势"
    assert data["days"] == 14


def test_insights_api_group_not_found():
    from fastapi.testclient import TestClient
    from app.main import app
    client = TestClient(app)
    r = client.get("/api/groups/99999/insights")
    assert r.status_code == 404


# ---------- 报告含趋势段（端到端：_format_insights）----------

def test_format_insights_with_trends():
    insights = {
        "trends": [{"trend": "私域转公域", "source_names": ["张三", "李四", "王五"],
                    "signal_count": 3, "momentum": "↗ 升温", "why_hot": "业务关键"}],
        "raw_signal_count": 5, "days": 14,
    }
    lines = KnowledgeService._format_insights(insights)
    text = "\n".join(lines)
    assert "🌐 本期行业信号" in text
    assert "私域转公域" in text
    assert "🔥" in text  # signal_count>=3 是热门
    assert "张三、李四、王五" in text


def test_format_insights_no_trends_but_enough_signals():
    """有信号但无趋势 → 显示分散说明"""
    insights = {"trends": [], "raw_signal_count": 3, "days": 14}
    lines = KnowledgeService._format_insights(insights)
    assert len(lines) > 0
    assert "分散" in "\n".join(lines) or "未形成" in "\n".join(lines)


def test_format_insights_none():
    """insights=None → 空列表（不显示趋势段）"""
    assert KnowledgeService._format_insights(None) == []


# ---------- config API 含 insight 相关项 ----------

def test_config_api_has_insight_items():
    from fastapi.testclient import TestClient
    from app.main import app
    client = TestClient(app)
    r = client.get("/api/config")
    sch = r.json()["schema"]
    assert "insight_lookback_days" in sch
    assert "insight_min_sources" in sch

    r = client.get("/api/config/prompts")
    assert "insight_prompt_template" in r.json()


# ---------- 修复点验证：system_int 防御非法配置 ----------

def test_system_int_handles_invalid_config():
    """system_int 对非法配置值安全降级，不抛异常"""
    from app.services import config_service
    # 正常值
    assert config_service.system_int("signal_min_new_points", 1) == 1
    assert config_service.system_int("insight_lookback_days", 14) == 14
    # 配成字符串数字
    config_service.set_system_value("signal_min_new_points", "3")
    assert config_service.system_int("signal_min_new_points", 1) == 3
    # 配成非法值 → 回退默认
    config_service.set_system_value("signal_min_new_points", "abc")
    assert config_service.system_int("signal_min_new_points", 1) == 1
    config_service.set_system_value("signal_min_new_points", None)
    assert config_service.system_int("signal_min_new_points", 1) == 1
    config_service.invalidate_cache()


# ---------- 修复点验证：报告只消费已完成 Signal ----------

def test_collect_new_items_distinguishes_unjudged_from_repeat(monkeypatch):
    """没有 signal 记录的内容不进入报告，避免绕过观点档案状态机"""
    from app.services.knowledge_service import KnowledgeService
    from app.storage.fs import StorageManager

    grp, s1, _ = _make_group_with_sources(slug="three-state")
    # 造一条已转录的内容（但 DB 里没有对应的 Signal 记录 = 判定失败）
    storage = StorageManager(f"three-state/a1")
    storage.save_transcript("c-unjudged", "这是一段转录", create_time="2026-07-01T10:00:00")
    storage.save_metadata("c-unjudged", {
        "content_id": "c-unjudged", "title": "未判定的内容",
        "create_time": "2026-07-01T10:00:00",
    })
    # 造一条有 signal 且 is_new=False 的内容（真正的老调重弹）
    storage.save_transcript("c-repeat", "另一段转录", create_time="2026-07-01T11:00:00")
    storage.save_metadata("c-repeat", {
        "content_id": "c-repeat", "title": "老调重弹内容",
        "create_time": "2026-07-01T11:00:00",
    })
    _add_signal(s1, grp, "c-repeat", "重复观点", ["x"], is_new=False)

    with _session() as s:
        src = SourceRepo(s).get(s1)
    items = KnowledgeService()._collect_new_items(src)
    item_map = {it["content_id"]: it for it in items}

    # 未判定的内容：等待刷新流水线补判定，不进入报告
    assert "c-unjudged" not in item_map
    # 真老调重弹：has_signal=True, is_new=False
    assert item_map["c-repeat"]["has_signal"] is True
    assert item_map["c-repeat"]["is_new_signal"] is False


def test_analyze_group_unjudged_does_not_go_to_deep_analysis(monkeypatch):
    """未判定内容不应被报告兜底深度分析；应等待刷新流水线补 Signal"""
    from app.services.knowledge_service import KnowledgeService
    from app.storage.fs import StorageManager

    grp, s1, _ = _make_group_with_sources(slug="undjudged-flow")
    # 只造一条未判定内容（无 signal 记录）
    storage = StorageManager(f"undjudged-flow/a1")
    storage.save_transcript("c1", "转录内容", create_time="2026-07-01T10:00:00")
    storage.save_metadata("c1", {
        "content_id": "c1", "title": "未判定", "create_time": "2026-07-01T10:00:00",
    })

    # mock _analyze_source / _summarize_repeats 都不应被调用
    analyze_called = {"v": False}
    summarize_called = {"v": False}
    orig_analyze = KnowledgeService._analyze_source
    orig_summarize = KnowledgeService._summarize_repeats

    def spy_analyze(self, source, items):
        analyze_called["v"] = True
        # 确认传进来的是未判定内容
        assert all(not it.get("is_new_signal") for it in items)
        return "深度分析结果"

    def spy_summarize(source, items):
        summarize_called["v"] = True
        return "汇总"

    monkeypatch.setattr(KnowledgeService, "_analyze_source", spy_analyze)
    monkeypatch.setattr(KnowledgeService, "_summarize_repeats", spy_summarize)
    # 跳过跨源提炼和报告写盘
    monkeypatch.setattr(KnowledgeService, "_write_report", lambda self, *a, **k: (Path("/tmp/x.md"), Path("/tmp/x.json")))

    from app.db.schema import Report
    monkeypatch.setattr("app.db.repos.ReportRepo.create", lambda self, r: type("R", (), {"id": 1})())

    result = KnowledgeService().analyze_group(grp)
    assert result["report_id"] is None
    assert analyze_called["v"] is False
    assert summarize_called["v"] is False


# ---------- 修复点验证：insights 端点读配置默认 days ----------

def test_insights_api_uses_config_default_days(monkeypatch):
    """insights 端点不传 days 时，用 insight_lookback_days 配置"""
    from app.services import config_service
    from fastapi.testclient import TestClient
    from app.main import app
    client = TestClient(app)

    grp, s1, s2 = _make_group_with_sources(slug="insight-config")
    _add_signal(s1, grp, "c1", "A", ["x"])
    _add_signal(s2, grp, "c2", "B", ["x"])

    config_service.set_system_value("insight_lookback_days", 30)

    captured = {"days": None}
    from app.services import insight_service
    orig = insight_service.InsightService.build_group_insights
    def spy(self, group_id, *, days=14):
        captured["days"] = days
        return None
    monkeypatch.setattr(insight_service.InsightService, "build_group_insights", spy)

    client.get(f"/api/groups/{grp}/insights")  # 不传 days
    assert captured["days"] == 30  # 用了配置值，不是写死的 14

    client.get(f"/api/groups/{grp}/insights?days=7")  # 显式传
    assert captured["days"] == 7
    config_service.invalidate_cache()
