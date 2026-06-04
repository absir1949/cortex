"""AI 知识提炼 - 视频原话 vs 观众评论分开喂给 LLM"""
from __future__ import annotations
import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from app.db.engine import get_session
from app.db.repos import GroupRepo, SourceRepo, AnalyzedRepo, ReportRepo
from app.db.schema import Report
from app.llm import OpenAICompatClient, LLMMessage
from app.models.group import ReportKind
from app.services import config_service
from app.storage import paths
from app.storage.fs import StorageManager


# 单次喂给 LLM 的文本上限
MAX_TRANSCRIPT_CHARS = 12000
MAX_COMMENT_CHARS = 3000


class KnowledgeService:
    """按组做增量分析：每源挑未分析过的 content，构造 prompt 喂给 LLM"""

    def __init__(self):
        self.llm = OpenAICompatClient()

    # ============ 公开 API ============

    def analyze_group(self, group_id: int) -> Optional[dict]:
        """对一个组做一次增量分析，返回结构：
        {
          "creators": [{"name", "analysis", "new_count"}],
          "report_id": int,
          "report_path": str
        }
        """
        with get_session() as s:
            group = GroupRepo(s).get(group_id)
            sources = SourceRepo(s).list_by_group(group_id, enabled_only=True)
        if not group:
            return None

        analyzed_results: list[dict] = []
        total_new = 0

        for source in sources:
            new_items = self._collect_new_items(source)
            if not new_items:
                continue
            analysis = self._analyze_source(source, new_items)
            if not analysis:
                continue
            analyzed_results.append({
                "name": source.display_name,
                "analysis": analysis,
                "new_count": len(new_items),
                "source_id": source.id,
            })
            # 标记已分析（只有 analysis 成功才标记）
            with get_session() as s:
                AnalyzedRepo(s).mark_many(
                    source.id,
                    [it["content_id"] for it in new_items],
                )
            total_new += len(new_items)

        if not analyzed_results:
            return {"creators": [], "report_id": None, "report_path": None}

        # 落地报告
        report_md, report_json_path = self._write_report(group.slug, analyzed_results)
        with get_session() as s:
            report = ReportRepo(s).create(Report(
                group_id=group_id,
                kind=ReportKind.SCHEDULED.value,
                title=f"{group.name} 知识整理 {datetime.now().strftime('%Y-%m-%d %H:%M')}",
                summary=self._make_summary(analyzed_results),
                content_md_path=str(report_md),
                content_json_path=str(report_json_path),
                sources_used=[{"source_id": r["source_id"], "new_count": r["new_count"]} for r in analyzed_results],
            ))

        return {
            "creators": analyzed_results,
            "report_id": report.id,
            "report_path": str(report_md),
        }

    def answer_question(
        self,
        question: str,
        evidence: list[dict],
    ) -> str:
        """按需研究用的 LLM 调用
        evidence = [{content_id, url, author, title, transcript?, comments: [{author, text, likes}]}]
        """
        llm_config = config_service.get_llm_config()
        template = config_service.prompt("research_prompt_template")
        evidence_block = self._build_evidence_block(evidence)
        prompt = template.format(question=question, evidence_block=evidence_block)

        return self.llm.chat(
            [
                LLMMessage(role="system", content="你是电商行业分析师，基于证据回答问题，严谨并标注来源。"),
                LLMMessage(role="user", content=prompt),
            ],
            config=llm_config,
        )

    # ============ 内部 ============

    def _collect_new_items(self, source) -> list[dict]:
        """从该源目录读已转录的 content，过滤掉已分析的"""
        with get_session() as s:
            analyzed = AnalyzedRepo(s).get_analyzed_ids(source.id)
        storage = StorageManager(source.directory)
        new_items: list[dict] = []
        for md in storage.list_metadata():
            cid = md.get("content_id") or md.get("video_id")
            if not cid or cid in analyzed:
                continue
            transcript = storage.get_transcript(cid)
            if not transcript:
                continue
            new_items.append({
                "content_id": cid,
                "title": md.get("title", ""),
                "transcript": transcript,
                "comments": storage.get_comments(cid) or [],
                "create_time": md.get("create_time", ""),
            })
        return new_items

    def _analyze_source(self, source, items: list[dict]) -> Optional[str]:
        """构造 prompt 喂 LLM"""
        transcripts_block = self._build_transcripts_block(items)
        comments_block = self._build_comments_block(items)

        template = config_service.prompt("analysis_prompt_template")
        prompt = template.format(
            creator_name=source.display_name,
            content_count=len(items),
            transcripts_block=transcripts_block,
            comments_block=comments_block or "（无评论）",
        )

        try:
            return self.llm.chat(
                [
                    LLMMessage(role="system", content="你是电商行业的知识整理专家，保留细节、不要空洞概括。"),
                    LLMMessage(role="user", content=prompt),
                ],
                config=config_service.get_llm_config(),
            )
        except Exception as e:
            return None

    @staticmethod
    def _build_transcripts_block(items: list[dict]) -> str:
        parts: list[str] = []
        for i, it in enumerate(items, 1):
            title = (it.get("title") or "").strip()
            text = (it.get("transcript") or "").strip()
            header = f"【作品 {i}】{title}" if title else f"【作品 {i}】"
            parts.append(f"{header}\n{text}")
        full = "\n\n---\n\n".join(parts)
        if len(full) > MAX_TRANSCRIPT_CHARS:
            full = full[:MAX_TRANSCRIPT_CHARS] + "\n\n...（原话过长已截断）"
        return full

    @staticmethod
    def _build_comments_block(items: list[dict]) -> str:
        parts: list[str] = []
        for i, it in enumerate(items, 1):
            comments = it.get("comments") or []
            if not comments:
                continue
            sub = [f"【作品 {i} 评论】"]
            for c in comments[:10]:
                author = c.get("author", "")
                text = c.get("text", "")
                likes = c.get("likes", 0)
                sub.append(f"  - 👍{likes} @{author}: {text}")
                for r in (c.get("replies") or [])[:3]:
                    sub.append(f"    └ @{r.get('author', '')}: {r.get('text', '')}")
            parts.append("\n".join(sub))
        full = "\n\n".join(parts)
        if len(full) > MAX_COMMENT_CHARS:
            full = full[:MAX_COMMENT_CHARS] + "\n...（评论过长已截断）"
        return full

    @staticmethod
    def _build_evidence_block(evidence: list[dict]) -> str:
        parts: list[str] = []
        for i, ev in enumerate(evidence, 1):
            header = f"【证据 {i}】{ev.get('author', '')} · {ev.get('title', '')[:50]}\n来源：{ev.get('url', '')}"
            body: list[str] = []
            if ev.get("transcript"):
                t = ev["transcript"]
                body.append(f"[博主原话]\n{t[:2000]}" + ("..." if len(t) > 2000 else ""))
            if ev.get("comments"):
                body.append("[观众评论]")
                for c in ev["comments"][:8]:
                    body.append(f"  - 👍{c.get('likes', 0)} @{c.get('author', '')}: {c.get('text', '')}")
            parts.append(header + "\n" + "\n".join(body))
        return "\n\n---\n\n".join(parts)

    def _write_report(self, group_slug: str, results: list[dict]) -> tuple[Path, Path]:
        dir_ = paths.knowledge_dir_for_group(group_slug)
        dir_.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        md_path = dir_ / f"knowledge_{ts}.md"
        json_path = dir_ / f"knowledge_{ts}.json"

        lines = [
            "# Cortex 知识报告",
            f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "",
        ]
        for r in results:
            lines.append(f"## {r['name']}（本次新增 {r['new_count']} 条）")
            lines.append("")
            lines.append(r["analysis"])
            lines.append("")
            lines.append("---")
            lines.append("")
        lines.append("*由 Cortex 自动生成*")

        md_path.write_text("\n".join(lines), encoding="utf-8")
        json_path.write_text(
            json.dumps({"creators": results}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return md_path, json_path

    @staticmethod
    def _make_summary(results: list[dict]) -> str:
        names = "、".join(r["name"] for r in results[:5])
        total = sum(r["new_count"] for r in results)
        return f"本期分析了 {len(results)} 个源（{names}），共 {total} 条新内容"
