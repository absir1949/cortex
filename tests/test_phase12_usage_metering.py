from __future__ import annotations

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.auth import create_token
from app.db.engine import get_engine
from app.db.repos import GroupRepo
from app.db.schema import (
    Creator,
    GlobalContent,
    GroupContent,
    KnowledgeGroup,
    LLMUsageAllocation,
    LLMUsageEvent,
    Source,
    SourceContent,
    User,
)
from app.llm import LLMConfig, LLMMessage, LLMTokenUsage, LLMUsageContext
from app.main import create_app
from app.services.usage_service import record_llm_usage


def test_llm_usage_records_true_event_and_splits_shared_global_content():
    with Session(get_engine()) as s:
        u1 = User(phone="13100000001", nickname="A", plan="pro")
        u2 = User(phone="13100000002", nickname="B", plan="pro")
        creator = Creator(name="共享作者", slug="shared-author")
        s.add_all([u1, u2, creator])
        s.commit()
        s.refresh(u1)
        s.refresh(u2)
        s.refresh(creator)

        g1 = KnowledgeGroup(owner_id=u1.id, name="专题A", slug="a")
        g2 = KnowledgeGroup(owner_id=u2.id, name="专题B", slug="b")
        s.add_all([g1, g2])
        s.commit()
        s.refresh(g1)
        s.refresh(g2)

        src1 = Source(
            group_id=g1.id,
            creator_id=creator.id,
            type="creator",
            platform="douyin",
            identifier="creator-a",
            display_name="共享作者",
            directory="a/creator-a",
        )
        src2 = Source(
            group_id=g2.id,
            creator_id=creator.id,
            type="creator",
            platform="douyin",
            identifier="creator-a",
            display_name="共享作者",
            directory="b/creator-a",
        )
        content = GlobalContent(
            platform="douyin",
            content_id="shared-001",
            creator_id=creator.id,
            title="同一条内容",
        )
        s.add_all([src1, src2, content])
        s.commit()
        s.refresh(src1)
        s.refresh(src2)
        s.refresh(content)

        s.add_all([
            SourceContent(source_id=src1.id, global_content_id=content.id),
            SourceContent(source_id=src2.id, global_content_id=content.id),
            GroupContent(group_id=g1.id, global_content_id=content.id),
            GroupContent(group_id=g2.id, global_content_id=content.id),
        ])
        s.commit()

        source_id = src1.id
        creator_id = creator.id
        global_content_id = content.id
        group_id_to_delete = g1.id
        user_ids = {u1.id, u2.id}

    event_id = record_llm_usage(
        config=LLMConfig(base_url="https://llm.example/v1", api_key="sk-test", model="test-model"),
        messages=[LLMMessage(role="user", content="判断这条内容是否新观点")],
        response_text='{"is_new": true}',
        usage_context=LLMUsageContext(
            operation="signal_judge",
            source_id=source_id,
            creator_id=creator_id,
            global_content_id=global_content_id,
        ),
        token_usage=LLMTokenUsage(prompt_tokens=100, completion_tokens=50, total_tokens=150),
    )

    assert event_id is not None
    with Session(get_engine()) as s:
        event = s.get(LLMUsageEvent, event_id)
        assert event is not None
        assert event.total_tokens == 150
        assert event.global_content_id == global_content_id

        allocations = s.exec(select(LLMUsageAllocation).order_by(LLMUsageAllocation.user_id)).all()
        assert len(allocations) == 2
        assert [a.allocated_total_tokens for a in allocations] == [75, 75]
        assert {a.allocation_kind for a in allocations} == {"shared"}
        assert {a.user_id for a in allocations} == user_ids

    with Session(get_engine()) as s:
        GroupRepo(s).delete(group_id_to_delete, cascade=True)
        assert s.get(LLMUsageEvent, event_id) is not None


def test_admin_overview_exposes_usage_summary():
    with Session(get_engine()) as s:
        admin = User(phone="13000000000", nickname="admin", role="admin", plan="pro")
        user = User(phone="13100000003", nickname="客户", role="user", plan="pro", expires_at="2099-01-01T00:00:00")
        creator = Creator(name="九柚米电商", slug="jiuyoumi")
        s.add_all([admin, user, creator])
        s.commit()
        s.refresh(admin)
        s.refresh(user)
        s.refresh(creator)

        group = KnowledgeGroup(owner_id=user.id, name="微信小店", slug="wechat-shop")
        s.add(group)
        s.commit()
        s.refresh(group)
        source = Source(
            group_id=group.id,
            creator_id=creator.id,
            type="creator",
            platform="douyin",
            identifier="creator-a",
            display_name="九柚米电商",
            directory="wechat-shop/creator-a",
        )
        s.add(source)
        s.commit()
        s.refresh(source)

        admin_user = {"id": admin.id, "phone": admin.phone, "role": admin.role}
        source_id = source.id
        group_id = group.id
        creator_id = creator.id

    record_llm_usage(
        config=LLMConfig(base_url="https://llm.example/v1", api_key="sk-test", model="test-model"),
        messages=[LLMMessage(role="user", content="生成报告")],
        response_text="报告正文",
        usage_context=LLMUsageContext(
            operation="report_source_batch",
            group_id=group_id,
            source_id=source_id,
            creator_id=creator_id,
        ),
        token_usage=LLMTokenUsage(prompt_tokens=20, completion_tokens=10, total_tokens=30),
    )

    with TestClient(create_app()) as client:
        resp = client.get(
            "/api/admin/overview",
            headers={"Authorization": f"Bearer {create_token(admin_user['id'], admin_user['phone'], admin_user['role'])}"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["stats"]["llm_actual_tokens_30d"] == 30
    assert data["stats"]["llm_allocated_tokens_30d"] == 30
    assert data["usage"]["actual_total_tokens_30d"] == 30
    assert data["usage"]["by_operation"][0]["operation"] == "report_source_batch"
    assert data["usage"]["by_user"][0]["phone"] == "13100000003"
    assert data["usage"]["by_user"][0]["allocated_total_tokens"] == 30
    assert data["usage"]["by_creator"][0]["creator_name"] == "九柚米电商"
