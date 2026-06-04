"""AI 知识提炼模块"""
import json
import requests
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Set
from rich.console import Console

from config import Config

console = Console()

ANALYZED_FILE = ".analyzed.json"


def extract_knowledge() -> Dict[str, Any]:
    """增量分析：每个创作者只分析未分析过的新转录

    Returns:
        {"creators": [{"name": ..., "analysis": ..., "new_count": N}, ...]}
    """
    console.print("\n[bold cyan]🧠 AI 知识提炼（增量）[/bold cyan]")

    data_dir = Config.DATA_DIR
    results = []
    total_new = 0

    for creator_dir in data_dir.iterdir():
        if not creator_dir.is_dir():
            continue

        analyzed = _load_analyzed(creator_dir)
        new_transcripts = _collect_new_transcripts(creator_dir, analyzed)

        if not new_transcripts:
            console.print(f"  [dim]{creator_dir.name}: 无新内容，跳过[/dim]")
            continue

        console.print(f"  [yellow]{creator_dir.name}: 发现 {len(new_transcripts)} 条新转录[/yellow]")

        analysis = _analyze_creator(creator_dir.name, new_transcripts)
        if analysis:
            results.append({
                "name": creator_dir.name,
                "analysis": analysis,
                "new_count": len(new_transcripts),
            })
            # 标记为已分析
            new_ids = {t['video_id'] for t in new_transcripts}
            _save_analyzed(creator_dir, analyzed | new_ids)
            total_new += len(new_transcripts)

    knowledge = {"creators": results}

    if not results:
        console.print("[dim]本次没有新内容需要分析[/dim]")
        return knowledge

    # 保存报告
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    report_json = Config.KNOWLEDGE_DIR / f"knowledge_{timestamp}.json"
    report_json.write_text(json.dumps(knowledge, ensure_ascii=False, indent=2), encoding='utf-8')

    report_md = Config.KNOWLEDGE_DIR / f"knowledge_{timestamp}.md"
    report_md.write_text(_to_markdown(knowledge), encoding='utf-8')

    console.print(f"[green]✓ 分析了 {len(results)} 个创作者，共 {total_new} 条新转录[/green]")
    console.print(f"[green]✓ 知识报告已保存: {report_json}[/green]")

    return knowledge


def _load_analyzed(creator_dir: Path) -> Set[str]:
    """读取该创作者已分析过的 video_id 集合"""
    state_file = creator_dir / ANALYZED_FILE
    if not state_file.exists():
        return set()
    try:
        data = json.loads(state_file.read_text(encoding='utf-8'))
        return set(data.get('video_ids', []))
    except Exception:
        return set()


def _save_analyzed(creator_dir: Path, video_ids: Set[str]):
    """保存已分析的 video_id 集合"""
    state_file = creator_dir / ANALYZED_FILE
    state_file.write_text(json.dumps({
        'video_ids': sorted(video_ids),
        'updated_at': datetime.now().isoformat(),
    }, ensure_ascii=False, indent=2), encoding='utf-8')


def _collect_new_transcripts(creator_dir: Path, analyzed: Set[str]) -> List[Dict]:
    """收集该创作者目录下未分析过的转录，按时间倒序"""
    new_items = []
    for txt_file in sorted(creator_dir.glob("*.txt"), reverse=True):
        try:
            # 通过同名 json 元数据获取 video_id
            meta_file = txt_file.with_suffix('.json')
            if not meta_file.exists():
                continue
            meta = json.loads(meta_file.read_text(encoding='utf-8'))
            video_id = meta.get('video_id')
            if not video_id or video_id in analyzed:
                continue

            transcript = txt_file.read_text(encoding='utf-8').strip()
            if not transcript:
                continue

            new_items.append({
                'video_id': video_id,
                'title': meta.get('title', ''),
                'content': transcript,
            })
        except Exception:
            continue
    return new_items


def _analyze_creator(creator_name: str, transcripts: List[Dict]) -> str:
    """分析单个创作者的新转录内容，返回自然语言分析文本"""
    content_parts = []
    for t in transcripts:
        title_line = f"【{t['title']}】" if t['title'] else ""
        content_parts.append(f"{title_line}\n{t['content']}")

    all_content = "\n\n---\n\n".join(content_parts)

    if len(all_content) > 15000:
        all_content = all_content[:15000] + "\n\n...（内容过长已截断）"

    prompt = f"""以下是电商创作者「{creator_name}」最近发布的 {len(transcripts)} 条短视频转录内容。

请你仔细阅读全部内容，输出一份详细的知识整理。要求：

1. **不要过度概括**，保留具体的数字、方法、操作步骤等细节
2. 按话题分段整理，每个话题下列出该创作者提到的具体做法和观点
3. 特别注意那些不容易被注意到的隐性经验（比如踩坑经历、反常识的做法、具体的参数设置等）
4. 如果创作者提到了具体的工具、软件、平台规则变化，要原样记录
5. 用中文输出，不要输出 JSON，直接输出可读的文本

转录内容：

{all_content}"""

    try:
        response = requests.post(
            f"{Config.DEEPSEEK_API_URL}/chat/completions",
            headers={
                "Authorization": f"Bearer {Config.DEEPSEEK_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": "deepseek-chat",
                "messages": [
                    {
                        "role": "system",
                        "content": "你是电商行业的知识整理专家。你的任务是从创作者的口语化视频内容中，提炼出有实操价值的知识，保留关键细节，不要空洞概括。"
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ]
            },
            timeout=180
        )
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"]
    except Exception as e:
        console.print(f"    [red]✗ 分析失败: {e}[/red]")
        return None


def _to_markdown(knowledge: Dict[str, Any]) -> str:
    """将知识报告转为 markdown"""
    lines = [
        f"# Cortex 知识报告",
        f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        ""
    ]

    for creator in knowledge.get("creators", []):
        count = creator.get('new_count', 0)
        lines.append(f"## {creator['name']}（本次新增 {count} 条）")
        lines.append("")
        lines.append(creator.get('analysis', '（无分析结果）'))
        lines.append("")
        lines.append("---")
        lines.append("")

    lines.append("*由 Cortex 自动生成*")
    return "\n".join(lines)
