"""Phase 2 冒烟测试：PlatformAdapter 契约 + 抖音适配器数据转换（不打真实 API）"""
from __future__ import annotations
from unittest.mock import patch, MagicMock

from app.platforms import get_adapter, list_platforms, Capability
from app.platforms.douyin import DouyinAdapter
from app.models.content import ContentType


def test_registry_has_douyin():
    assert "douyin" in list_platforms()
    a = get_adapter("douyin")
    assert isinstance(a, DouyinAdapter)
    assert a.platform == "douyin"


def test_douyin_capabilities_complete():
    a = DouyinAdapter()
    caps = a.capabilities()
    for cap in (
        Capability.FETCH_CREATOR,
        Capability.SEARCH,
        Capability.FETCH_COMMENTS,
        Capability.DOWNLOAD_MEDIA,
    ):
        assert a.has(cap), f"missing {cap}"


def _mock_response(code=200, payload=None):
    r = MagicMock()
    r.status_code = 200
    r.json.return_value = {"code": code, "data": payload or {}}
    return r


def test_fetch_creator_content_parsing():
    a = DouyinAdapter()
    fake_api_response = {
        "aweme_list": [
            {
                "aweme_id": "7111111111",
                "desc": "测试视频标题",
                "create_time": 1704067200,   # 2024-01-01
                "author": {"nickname": "张三", "sec_uid": "MS4wLjABxxx"},
                "statistics": {
                    "digg_count": 100, "comment_count": 20, "share_count": 5, "play_count": 5000
                },
                "video": {"play_addr": {"url_list": ["https://example.com/v1.mp4"]}},
            },
        ]
    }
    with patch("app.platforms.douyin.requests.get", return_value=_mock_response(payload=fake_api_response)):
        contents = a.fetch_creator_content("MS4wLjABxxx", limit=20)

    assert len(contents) == 1
    c = contents[0]
    assert c.content_id == "7111111111"
    assert c.content_type == ContentType.VIDEO
    assert c.title == "测试视频标题"
    assert c.author_name == "张三"
    assert c.media_urls == ["https://example.com/v1.mp4"]
    assert c.statistics["digg_count"] == 100
    assert c.url == "https://www.douyin.com/video/7111111111"
    assert c.should_transcribe() is True


def test_search_parsing_general_result_shape():
    """新端点：POST /api/v1/douyin/search/fetch_general_search_v1
    响应：{"data": {"data": [{"type":1, "aweme_info": {...}}, {"type":6,...}], "has_more":0, ...}}
    """
    import time
    a = DouyinAdapter()
    recent_ts = int(time.time()) - 86400
    fake = {
        "data": [
            {
                "type": 1,
                "aweme_info": {
                    "aweme_id": "SEARCH1",
                    "desc": "保证金要交多少",
                    "create_time": recent_ts,
                    "author": {"nickname": "A", "sec_uid": "secA"},
                    "statistics": {"digg_count": 1, "comment_count": 2, "share_count": 3, "play_count": 4},
                    "video": {"play_addr": {"url_list": []}},
                },
            },
            {"type": 6, "user_info": {}},   # 混入的非视频结果应被过滤
        ],
        "has_more": 0,
        "cursor": 20,
        "search_id": "x",
        "backtrace": "y",
    }
    with patch("app.platforms.douyin.requests.post", return_value=_mock_response(payload=fake)):
        results = a.search("抖店保证金", limit=10, days=30)

    assert len(results) == 1
    assert results[0].content_id == "SEARCH1"
    assert results[0].title == "保证金要交多少"


def test_fetch_comments_with_replies():
    a = DouyinAdapter()
    # 第一次调用 → 一级评论；第二次 → 二级回复
    l1 = {"comments": [{
        "cid": "c1",
        "text": "评论1",
        "digg_count": 10,
        "create_time": 1704067200,
        "user": {"nickname": "u1"},
        "reply_comment_total": 2,
    }]}
    l2 = {"comments": [
        {"cid": "r1", "text": "回复1", "digg_count": 1, "create_time": 1704067201, "user": {"nickname": "u2"}},
        {"cid": "r2", "text": "回复2", "digg_count": 0, "create_time": 1704067202, "user": {"nickname": "u3"}},
    ]}

    responses = [_mock_response(payload=l1), _mock_response(payload=l2)]

    with patch("app.platforms.douyin.requests.get", side_effect=responses):
        comments = a.fetch_comments("7111111111", top_n=20, fetch_replies=True)

    assert len(comments) == 1
    c = comments[0]
    assert c.comment_id == "c1"
    assert c.text == "评论1"
    assert c.likes == 10
    assert len(c.replies) == 2
    assert c.replies[0].text == "回复1"


def test_http_error_raises():
    a = DouyinAdapter()
    r = MagicMock()
    r.status_code = 500
    r.text = "server error"
    with patch("app.platforms.douyin.requests.get", return_value=r):
        try:
            a.fetch_creator_content("xxx")
            assert False, "should have raised"
        except RuntimeError as e:
            assert "TikHub HTTP 500" in str(e)


def test_not_implemented_on_missing_capability():
    """Base class methods raise NotImplementedError if subclass doesn't implement"""
    from app.platforms.base import PlatformAdapter

    class Stub(PlatformAdapter):
        platform = "stub"
        def capabilities(self):
            return set()

    s = Stub()
    for method in (
        lambda: s.fetch_creator_content("x"),
        lambda: s.search("x"),
        lambda: s.fetch_comments("x"),
    ):
        try:
            method()
            assert False
        except NotImplementedError:
            pass
