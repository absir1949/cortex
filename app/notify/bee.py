"""飞书 Bee 推送 - 保留现有能力，P0 期不是核心"""
from __future__ import annotations
from typing import Optional
import requests

from app.settings import settings


class BeeNotifier:
    """简单封装 Bee 通知网关"""

    def __init__(self, url: Optional[str] = None, group: Optional[str] = None):
        self.url = url or settings.bee_url
        self.group = group or settings.bee_notify_group

    def send(self, content: str, group: Optional[str] = None) -> bool:
        g = group or self.group
        if not self.url or not g:
            return False
        try:
            resp = requests.post(
                f"{self.url}/notify",
                json={"group": g, "content": content},
                timeout=10,
            )
            return resp.ok
        except Exception:
            return False

    def send_long(self, header: str, text: str, group: Optional[str] = None, max_len: int = 2500) -> int:
        """长文本按段落拆分多条发送，返回发送成功条数"""
        if len(text) <= max_len:
            return 1 if self.send(f"{header}\n\n{text}", group) else 0
        paragraphs = text.split("\n\n")
        chunks: list[str] = []
        current = ""
        for p in paragraphs:
            if len(current) + len(p) + 2 > max_len and current:
                chunks.append(current)
                current = p
            else:
                current = f"{current}\n\n{p}" if current else p
        if current:
            chunks.append(current)

        sent = 0
        for i, chunk in enumerate(chunks):
            title = header if len(chunks) == 1 else f"{header}（{i + 1}/{len(chunks)}）"
            if self.send(f"{title}\n\n{chunk}", group):
                sent += 1
        return sent


def push_knowledge(creators_analysis: list[dict]) -> int:
    """按创作者分条推送知识整理结果。返回成功条数"""
    notifier = BeeNotifier()
    total = 0
    for item in creators_analysis:
        name = item.get("name", "未知")
        analysis = item.get("analysis", "")
        if not analysis:
            continue
        total += notifier.send_long(f"📌 {name} · 知识整理", analysis)
    return total


def push_message(content: str, group: Optional[str] = None) -> bool:
    return BeeNotifier().send(content, group)
