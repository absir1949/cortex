"""消息推送模块"""
import requests
from typing import Dict, Any
from rich.console import Console

from config import Config

console = Console()


def push_knowledge(knowledge: Dict[str, Any]):
    """按创作者分条推送知识报告到 Bee"""
    creators = knowledge.get("creators", [])
    if not creators:
        console.print("[yellow]没有分析结果可推送[/yellow]")
        return

    for creator in creators:
        name = creator.get("name", "未知")
        analysis = creator.get("analysis", "")
        if not analysis:
            continue

        header = f"📌 {name} · 知识整理"
        _send_long(header, analysis)


def push_message(content: str, group: str = None):
    """推送自定义消息"""
    _send(content, group)


def _send_long(header: str, text: str, group: str = None, max_len: int = 2500):
    """长文本按段落拆分成多条发送，不截断"""
    if len(text) <= max_len:
        _send(f"{header}\n\n{text}", group)
        return

    # 按段落拆分（两个换行 或 ### 标题）
    paragraphs = text.split("\n\n")
    chunks = []
    current = ""

    for p in paragraphs:
        if len(current) + len(p) + 2 > max_len and current:
            chunks.append(current)
            current = p
        else:
            current = f"{current}\n\n{p}" if current else p

    if current:
        chunks.append(current)

    for i, chunk in enumerate(chunks):
        if len(chunks) == 1:
            title = header
        else:
            title = f"{header}（{i+1}/{len(chunks)}）"
        _send(f"{title}\n\n{chunk}", group)


def _send(content: str, group: str = None):
    """发送到 Bee"""
    group = group or Config.BEE_NOTIFY_GROUP
    if not Config.BEE_URL or not group:
        console.print("[yellow]未配置 BEE_URL 或 BEE_NOTIFY_GROUP[/yellow]")
        return

    try:
        resp = requests.post(
            f"{Config.BEE_URL}/notify",
            json={"group": group, "content": content},
            timeout=10,
        )
        if resp.ok:
            console.print(f"[green]✓ 已推送到 {group}[/green]")
        else:
            console.print(f"[yellow]⚠ 推送失败: {resp.text}[/yellow]")
    except Exception as e:
        console.print(f"[yellow]⚠ 推送失败: {e}[/yellow]")
