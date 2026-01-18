"""AI 知识提炼模块"""
import json
import requests
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any
from rich.console import Console

from config import Config

console = Console()


def extract_knowledge(topics: List[str] = None) -> Dict[str, Any]:
    """从所有创作者内容中提炼知识

    Args:
        topics: 指定话题列表，如 None 则自动发现

    Returns:
        知识报告
    """
    console.print("\n[bold cyan]🧠 AI 知识提炼[/bold cyan]")

    # 1. 收集所有转录文本
    all_transcripts = []
    data_dir = Config.DATA_DIR

    for creator_dir in data_dir.iterdir():
        if not creator_dir.is_dir():
            continue

        console.print(f"  扫描: {creator_dir.name}")

        for txt_file in creator_dir.glob("*.txt"):
            try:
                transcript = txt_file.read_text(encoding='utf-8')
                metadata_file = txt_file.with_suffix('.json')

                if metadata_file.exists():
                    metadata = json.loads(metadata_file.read_text(encoding='utf-8'))
                else:
                    metadata = {}

                all_transcripts.append({
                    'creator': creator_dir.name,
                    'content': transcript,
                    'metadata': metadata
                })
            except:
                continue

    console.print(f"  收集到 {len(all_transcripts)} 个转录文本")

    if not all_transcripts:
        console.print("[yellow]没有转录文本可用[/yellow]")
        return {}

    # 2. 调用 AI 提炼知识
    console.print("[yellow]AI 分析中...[/yellow]")

    prompt = f"""你是一个专业的知识分析师。请从以下内容创作者的转录文本中提炼有价值的知识。

输入内容：{len(all_transcripts)} 个创作者的转录文本。

请按以下结构输出JSON：

{{
  "topics": [
    {{
      "name": "话题名称",
      "description": "话题描述",
      "key_points": ["要点1", "要点2", "要点3"],
      "creators": ["创作者A", "创作者B"],
      "insights": ["洞察1", "洞察2"]
    }}
  ],
  "summary": "整体总结",
  "trends": ["趋势1", "趋势2"],
  "recommendations": ["建议1", "建议2"]
}}

转录文本样例（前5个）：
"""

    for i, item in enumerate(all_transcripts[:5]):
        prompt += f"\n\n--- {item['creator']} ---\n{item['content'][:500]}..."

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
                        "content": "你是一个专业的知识分析师，擅长从大量内容中提炼有价值的知识和洞察。"
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ]
            },
            timeout=120
        )

        response.raise_for_status()
        data = response.json()

        content = data["choices"][0]["message"]["content"]

        # 尝试解析 JSON
        try:
            # 提取 JSON 部分
            import re
            json_match = re.search(r'\{[\s\S]*\}', content)
            if json_match:
                knowledge = json.loads(json_match.group())
            else:
                knowledge = {"raw": content}
        except:
            knowledge = {"raw": content}

        # 保存报告
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        report_file = Config.KNOWLEDGE_DIR / f"knowledge_{timestamp}.md"

        report = f"""# Cortex 知识报告

**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
**分析内容**: {len(all_transcripts)} 个转录文本

---

## 知识内容

{content}

---

*由 Cortex 自动生成*
"""

        report_file.write_text(report, encoding='utf-8')

        console.print(f"[green]✓ 知识报告已保存: {report_file}[/green]")

        return knowledge

    except Exception as e:
        console.print(f"[red]✗ AI 分析失败: {e}[/red]")
        return {"error": str(e)}
