"""Phase 7 测试：跨博主趋势提炼（InsightService + API + 报告含趋势段）

覆盖：
  - InsightService：信号不足返回 None、LLM 失败降级、JSON 解析、趋势阈值过滤
  - insight prompt + 配置项可读
  - insights API 端点
  - 报告 _write_report 含趋势段（mock LLM 端到端）
"""
from __future__ import annotations
import json
import pytest
from pathlib import Path
from sqlmodel import Session, select

from app.db.engine import get_engine
from app.db.schema import GlobalContent, GroupContent, KnowledgeGroup, Report, Source, Signal, SourceContent
from app.db.repos import GroupRepo, SourceRepo, SignalRepo
from app.models.group import ReportKind, SourceType
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


def _add_signal(source_id, group_id, content_id, summary, new_points, is_new=True, global_content_id=None):
    with _session() as s:
        SignalRepo(s).create(
            source_id,
            content_id,
            global_content_id=global_content_id,
            group_id=group_id,
            is_new=is_new,
            summary=summary,
            new_points=new_points,
        )


def _add_group_content(group_id, source_id, content_id, *, title, create_time, is_new=None, summary="", new_points=None):
    with _session() as s:
        src = s.get(Source, source_id)
        global_item = GlobalContent(
            platform=src.platform,
            content_id=content_id,
            creator_id=src.creator_id,
            title=title,
            author_name=src.display_name,
            url=f"https://example.com/{content_id}",
            create_time=create_time,
        )
        s.add(global_item)
        s.commit()
        s.refresh(global_item)
        s.add(SourceContent(source_id=source_id, global_content_id=global_item.id))
        s.add(GroupContent(group_id=group_id, global_content_id=global_item.id))
        s.commit()
        gid = global_item.id
    if is_new is not None:
        _add_signal(
            source_id,
            group_id,
            content_id,
            summary,
            new_points or [],
            is_new=is_new,
            global_content_id=gid,
        )
    return gid


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

def test_insights_api_endpoint(tmp_path):
    from fastapi.testclient import TestClient
    from app.main import app
    from tests.auth_helpers import auth_headers
    client = TestClient(app, headers=auth_headers())

    grp, s1, s2 = _make_group_with_sources()
    json_path = tmp_path / "report.json"
    json_path.write_text(json.dumps({
        "insights": {
            "trends": [{"trend": "测试趋势", "source_names": ["张三", "李四"],
                        "signal_count": 2, "momentum": "↗ 升温", "why_hot": ""}],
            "raw_signal_count": 2,
            "days": 14,
        }
    }, ensure_ascii=False), encoding="utf-8")
    with _session() as s:
        s.add(Report(
            group_id=grp,
            kind=ReportKind.SCHEDULED.value,
            title="微信小店报告",
            summary="摘要",
            content_md_path=str(tmp_path / "report.md"),
            content_json_path=str(json_path),
        ))
        s.commit()

    r = client.get(f"/api/groups/{grp}/insights?days=14")
    assert r.status_code == 200
    data = r.json()
    assert data["trends"][0]["trend"] == "测试趋势"
    assert data["days"] == 14
    assert data["report_title"] == "微信小店报告"


def test_insights_api_group_not_found():
    from fastapi.testclient import TestClient
    from app.main import app
    from tests.auth_helpers import auth_headers
    client = TestClient(app, headers=auth_headers())
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
    from tests.auth_helpers import auth_headers
    client = TestClient(app, headers=auth_headers())
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

def test_collect_new_group_items_distinguishes_unjudged_from_repeat(monkeypatch):
    """没有 signal 记录的内容不进入报告，避免绕过观点档案状态机"""
    from app.services.knowledge_service import KnowledgeService

    grp, s1, _ = _make_group_with_sources(slug="three-state")
    _add_group_content(
        grp,
        s1,
        "c-unjudged",
        title="未判定的内容",
        create_time="2026-07-01T10:00:00",
    )
    _add_group_content(
        grp,
        s1,
        "c-repeat",
        title="老调重弹内容",
        create_time="2026-07-01T11:00:00",
        is_new=False,
        summary="重复观点",
        new_points=["x"],
    )

    with _session() as s:
        src = SourceRepo(s).get(s1)
    items = KnowledgeService()._collect_new_group_items(grp, [src])[src.id]
    item_map = {it["content_id"]: it for it in items}

    # 未判定的内容：等待刷新流水线补判定，不进入报告
    assert "c-unjudged" not in item_map
    # 真老调重弹：has_signal=True, is_new=False
    assert item_map["c-repeat"]["has_signal"] is True
    assert item_map["c-repeat"]["is_new_signal"] is False


def test_analyze_group_unjudged_does_not_go_to_deep_analysis(monkeypatch):
    """未判定内容不应被报告兜底深度分析；应等待刷新流水线补 Signal"""
    from app.services.knowledge_service import KnowledgeService

    grp, s1, _ = _make_group_with_sources(slug="undjudged-flow")
    _add_group_content(
        grp,
        s1,
        "c1",
        title="未判定",
        create_time="2026-07-01T10:00:00",
    )

    summary_called = {"v": False}

    def spy_summary(self, source, items):
        summary_called["v"] = True
        return {"analysis": "不应生成"}

    monkeypatch.setattr(KnowledgeService, "_build_creator_period_summary", spy_summary)

    result = KnowledgeService().analyze_group(grp)
    assert result["report_id"] is None
    assert summary_called["v"] is False


def test_report_uses_signal_cards_not_raw_transcript(monkeypatch):
    """整理报告应消费 Signal 卡片和观点档案，不重新把原始转录送给 LLM。"""
    from app.services.knowledge_service import KnowledgeService
    from app.storage.fs import GlobalStorage

    grp, s1, _ = _make_group_with_sources(slug="signal-card-report")
    gid = _add_group_content(
        grp,
        s1,
        "c-new",
        title="信号卡片内容",
        create_time="2026-07-01T10:00:00",
        is_new=True,
        summary="这条内容贡献了信号卡片摘要",
        new_points=["新增观点A"],
    )
    with _session() as s:
        global_item = s.get(GlobalContent, gid)
    storage = GlobalStorage(global_item.platform, global_item.creator_id)
    storage.save_transcript(
        "c-new",
        "RAW_TRANSCRIPT_SHOULD_NOT_APPEAR 这里是很长的原始转录",
        create_time="2026-07-01T10:00:00",
    )

    captured: list[str] = []
    svc = KnowledgeService()

    def fake_chat(messages, *, config):
        captured.extend(m.content for m in messages)
        return "### 本期变化\n基于信号卡片整理。"

    monkeypatch.setattr(svc.llm, "chat", fake_chat)
    result = svc.analyze_group(grp)

    assert result["report_id"] is not None
    prompt = "\n".join(captured)
    assert "新增观点A" in prompt
    assert "信号卡片内容" in prompt
    assert "RAW_TRANSCRIPT_SHOULD_NOT_APPEAR" not in prompt


def test_report_creator_period_failure_does_not_mark_analyzed(monkeypatch):
    """作者阶段摘要失败就让报告失败，不生成假摘要、不消费水位。"""
    from app.services.knowledge_service import KnowledgeService

    grp, s1, _ = _make_group_with_sources(slug="creator-period-fail")
    gid = _add_group_content(
        grp,
        s1,
        "c-new",
        title="失败内容",
        create_time="2026-07-01T10:00:00",
        is_new=True,
        summary="有新观点",
        new_points=["新增观点A"],
    )

    svc = KnowledgeService()
    monkeypatch.setattr(svc.llm, "chat", lambda messages, *, config: (_ for _ in ()).throw(RuntimeError("llm down")))

    with pytest.raises(RuntimeError, match="llm down"):
        svc.analyze_group(grp)

    with _session() as s:
        row = s.exec(
            select(GroupContent).where(
                GroupContent.group_id == grp,
                GroupContent.global_content_id == gid,
            )
        ).one()
    assert row.analyzed_at is None


def test_report_group_synthesis_invalid_json_fails_without_marking(monkeypatch):
    """专题综合不是 JSON 时不回退成假洞察，整份报告失败且水位不动。"""
    from app.services.knowledge_service import KnowledgeService

    grp, s1, s2 = _make_group_with_sources(slug="group-synthesis-fail")
    gid1 = _add_group_content(
        grp,
        s1,
        "c-a",
        title="作者A",
        create_time="2026-07-01T10:00:00",
        is_new=True,
        summary="A 讲内容种草",
        new_points=["内容种草"],
    )
    gid2 = _add_group_content(
        grp,
        s2,
        "c-b",
        title="作者B",
        create_time="2026-07-01T11:00:00",
        is_new=True,
        summary="B 讲内容种草",
        new_points=["内容种草"],
    )

    calls = {"n": 0}
    svc = KnowledgeService()

    def fake_chat(messages, *, config):
        calls["n"] += 1
        if calls["n"] <= 2:
            return "### 本期变化\n作者阶段摘要"
        return "not json"

    monkeypatch.setattr(svc.llm, "chat", fake_chat)

    with pytest.raises(RuntimeError, match="专题综合"):
        svc.analyze_group(grp)

    with _session() as s:
        rows = s.exec(
            select(GroupContent).where(
                GroupContent.group_id == grp,
                GroupContent.global_content_id.in_([gid1, gid2]),
            )
        ).all()
    assert {row.analyzed_at for row in rows} == {None}


# ---------- 修复点验证：insights 端点读配置默认 days ----------

def test_insights_api_reads_snapshot_without_realtime_llm(monkeypatch, tmp_path):
    """insights 端点只读报告快照，不在页面访问时实时跑 InsightService。"""
    from fastapi.testclient import TestClient
    from app.main import app
    from tests.auth_helpers import auth_headers
    client = TestClient(app, headers=auth_headers())

    grp, s1, s2 = _make_group_with_sources(slug="insight-config")
    json_path = tmp_path / "snapshot.json"
    json_path.write_text(json.dumps({
        "insights": {"trends": [], "raw_signal_count": 3, "days": 30}
    }, ensure_ascii=False), encoding="utf-8")
    with _session() as s:
        s.add(Report(
            group_id=grp,
            kind=ReportKind.SCHEDULED.value,
            title="快照报告",
            summary="摘要",
            content_md_path=str(tmp_path / "snapshot.md"),
            content_json_path=str(json_path),
        ))
        s.commit()

    from app.services import insight_service
    def spy(self, group_id, *, days=14):
        raise AssertionError("should not run realtime insight")
    monkeypatch.setattr(insight_service.InsightService, "build_group_insights", spy)

    resp = client.get(f"/api/groups/{grp}/insights")
    assert resp.status_code == 200
    assert resp.json()["raw_signal_count"] == 3
