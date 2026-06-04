"""POC: 真实调用 TikHub 验证搜索和评论端点可用

运行：python -m scripts.poc_tikhub
"""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.platforms import get_adapter


def main():
    adapter = get_adapter("douyin")
    print(f"platform: {adapter.platform}")
    print(f"capabilities: {[c.value for c in adapter.capabilities()]}")
    print()

    # 1. 搜索
    print("=" * 60)
    print("[1/3] 搜索 '微信小店'")
    try:
        results = adapter.search("微信小店", limit=5, days=7)
        print(f"  ✓ 搜索返回 {len(results)} 条")
        for r in results[:3]:
            print(f"    · [{r.create_time[:10]}] {r.author_name}: {r.title[:50]}")
            print(f"      id={r.content_id} stats={r.statistics}")
    except Exception as e:
        print(f"  ✗ 搜索失败: {e}")

    # 2. 获取评论（用第一条结果的 id）
    print()
    print("=" * 60)
    if results:
        aweme_id = results[0].content_id
        print(f"[2/3] 抓评论 aweme_id={aweme_id}")
        try:
            comments = adapter.fetch_comments(aweme_id, top_n=5, fetch_replies=True)
            print(f"  ✓ 抓到 {len(comments)} 条一级评论")
            for c in comments[:3]:
                print(f"    · 👍{c.likes} @{c.author}: {c.text[:50]}")
                for r in c.replies[:2]:
                    print(f"        └ 👍{r.likes} @{r.author}: {r.text[:40]}")
        except Exception as e:
            print(f"  ✗ 抓评论失败: {e}")
    else:
        print("[2/3] skip（没有搜索结果）")

    # 3. 博主作品（已验证过的能力，再跑一次确保没回归）
    print()
    print("=" * 60)
    print("[3/3] 博主作品（回归测试：狼教授）")
    try:
        contents = adapter.fetch_creator_content(
            "MS4wLjABAAAAhbui6XQ7bfISEWzd9G3MS4KjPGB14KazIPzF-5R_qgQ",
            limit=3,
        )
        print(f"  ✓ 拿到 {len(contents)} 条")
        for c in contents[:3]:
            print(f"    · [{c.create_time[:10]}] {c.title[:50]}")
    except Exception as e:
        print(f"  ✗ 失败: {e}")


if __name__ == "__main__":
    main()
