"""AI 知识提炼 - 视频原话 vs 观众评论分开喂给 LLM"""
from __future__ import annotations
import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from app.db.engine import get_session
from app.db.repos import GroupRepo, SourceRepo, AnalyzedRepo, ReportRepo, SignalRepo
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

    def analyze_group(self, group_id: int, refresh_summary: Optional[dict] = None) -> Optional[dict]:
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

            # 报告只消费已完成 Signal 的内容。未判定内容留在 content_items
            # 由刷新流水线补跑，避免报告、信号列表、观点档案不一致。
            signal_items = [it for it in new_items if it.get("is_new_signal")]
            repeat_items = [it for it in new_items if not it.get("is_new_signal")]

            if signal_items:
                analysis = self._analyze_source(source, signal_items)
            elif repeat_items:
                # 没有新观点，只有老调重弹：生成一句简短说明，不喂大量原文给 LLM
                analysis = self._summarize_repeats(source, repeat_items)
            else:
                continue
            if not analysis:
                continue

            new_signal_count = sum(1 for it in signal_items if it.get("is_new_signal"))
            analyzed_results.append({
                "name": source.display_name,
                "analysis": analysis,
                "new_count": len(new_items),
                "new_signal_count": new_signal_count,
                "repeat_count": len(repeat_items),
                "source_id": source.id,
            })
            # 标记已分析（只有 analysis 成功才标记）
            with get_session() as s:
                AnalyzedRepo(s).mark_many(
                    source.id,
                    [it["content_id"] for it in new_items],
                )
            total_new += new_signal_count

        if not analyzed_results:
            return {"creators": [], "report_id": None, "report_path": None}

        # 跨博主趋势提炼（失败不阻塞报告生成）
        insights = None
        try:
            from app.services.insight_service import InsightService
            raw_days = config_service.effective_for_group(group_id).get("insight_lookback_days", 14)
            try:
                days = int(raw_days)
            except (TypeError, ValueError):
                days = 14
            insights = InsightService().build_group_insights(group_id, days=days)
        except Exception:
            insights = None

        # 落地报告
        report_md, report_json_path = self._write_report(
            group.slug,
            analyzed_results,
            insights,
            refresh_summary=refresh_summary,
        )
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
        """从该源目录读已转录且已完成 Signal 的 content，过滤掉已分析项。"""
        with get_session() as s:
            analyzed = AnalyzedRepo(s).get_analyzed_ids(source.id)
            # 查 Signal 表：哪些 content 带新观点
            sig_map = {}
            for sig in SignalRepo(s).list_by_source(source.id, limit=500):
                sig_map[sig.content_id] = sig
        storage = StorageManager(source.directory)
        new_items: list[dict] = []
        for md in storage.list_metadata():
            cid = md.get("content_id") or md.get("video_id")
            if not cid or cid in analyzed:
                continue
            transcript = storage.get_transcript(cid)
            if not transcript:
                continue
            sig = sig_map.get(cid)
            if sig is None:
                continue
            new_items.append({
                "content_id": cid,
                "title": md.get("title", ""),
                "transcript": transcript,
                "comments": storage.get_comments(cid) or [],
                "create_time": md.get("create_time", ""),
                "has_signal": True,
                "is_new_signal": bool(sig.is_new),
                "signal_summary": sig.summary,
                "signal_new_points": list(sig.new_points),
                "signal_matched_points": list(sig.matched_points),
            })
        return new_items

    def _analyze_source(self, source, items: list[dict]) -> Optional[str]:
        """构造 prompt 喂 LLM。内容过多时分批分析，再 reduce 合并成一份连贯整理。"""
        BATCH = 8  # 每批最多分析 8 条，避免单次 LLM 调用输入过长超时
        if not items:
            return None

        # 少于一批直接分析
        if len(items) <= BATCH:
            return self._analyze_one_batch(source, items)

        # 分批分析
        parts: list[str] = []
        for i in range(0, len(items), BATCH):
            batch = items[i:i + BATCH]
            r = self._analyze_one_batch(source, batch)
            if r:
                parts.append(r)
        if not parts:
            return None
        # 只有一批成功，直接返回
        if len(parts) == 1:
            return parts[0]
        # 多批 → reduce 合并成一份连贯整理
        return self._merge_batches(source, parts) or "\n\n---\n\n".join(parts)

    def _merge_batches(self, source, parts: list[str]) -> Optional[str]:
        """把多份分批整理合并成一份连贯总结"""
        parts_block = "\n\n---\n\n".join(
            f"【整理 {i}】\n{p}" for i, p in enumerate(parts, 1)
        )
        template = config_service.prompt("analysis_merge_prompt_template")
        prompt = template.format(
            creator_name=source.display_name,
            batch_count=len(parts),
            parts_block=parts_block[:16000],  # 防止超长
        )
        try:
            return self.llm.chat(
                [
                    LLMMessage(role="system", content="你是电商行业的知识整理专家。把多份分批整理合并成一份连贯的总结，去重并按话题重组。"),
                    LLMMessage(role="user", content=prompt),
                ],
                config=config_service.get_llm_config(),
            )
        except Exception:
            return None

    def _analyze_one_batch(self, source, items: list[dict]) -> Optional[str]:
        """分析单批内容"""
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
        except Exception:
            return None

    @staticmethod
    def _summarize_repeats(source, items: list[dict]) -> str:
        """老调重弹内容的简短汇总（不调 LLM，省 token）"""
        titles = "、".join((it.get("title", "") or "无标题")[:15] for it in items[:5])
        points = []
        for it in items:
            for p in (it.get("signal_matched_points") or it.get("signal_new_points") or []):
                if p not in points:
                    points.append(p)
            if len(points) >= 5:
                break
        lines = [
            f"> 本期 {len(items)} 条内容**未带来新观点**，与作者此前观点重复。",
            "",
        ]
        if points:
            lines.append("**再次强调的观点**：")
            for p in points:
                lines.append(f"- {p}")
            lines.append("")
        if titles:
            lines.append(f"涉及内容：{titles}{' 等' if len(items) > 5 else ''}")
        return "\n".join(lines)

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

    def _write_report(
        self,
        group_slug: str,
        results: list[dict],
        insights: Optional[dict] = None,
        refresh_summary: Optional[dict] = None,
    ) -> tuple[Path, Path]:
        dir_ = paths.knowledge_dir_for_group(group_slug)
        dir_.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        md_path = dir_ / f"knowledge_{ts}.md"
        json_path = dir_ / f"knowledge_{ts}.json"

        total_new_signals = sum(r.get("new_signal_count", 0) for r in results)
        total_repeats = sum(r.get("repeat_count", 0) for r in results)

        lines = [
            "# 听风知识报告",
            f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "",
            f"**本期新信号**：{total_new_signals} 条新观点 · {total_repeats} 条内容与既有观点重复（已折叠）",
            "",
        ]
        refresh_lines = self._format_refresh_summary(refresh_summary)
        if refresh_lines:
            lines.extend(refresh_lines)
            lines.append("")

        # 跨博主行业信号段（有趋势时才出现，放最前）
        trend_lines = self._format_insights(insights)
        if trend_lines:
            lines.extend(trend_lines)
            lines.append("")
        for r in results:
            new_cnt = r.get("new_signal_count", 0)
            rep_cnt = r.get("repeat_count", 0)
            head = f"## {r['name']}"
            if new_cnt:
                head += f"（🆕 {new_cnt} 条新观点"
                if rep_cnt:
                    head += f" / ♻️ {rep_cnt} 条重复"
                head += "）"
            else:
                head += f"（♻️ {rep_cnt} 条重复，无新增）"
            lines.append(head)
            lines.append("")
            lines.append(r["analysis"])
            lines.append("")
            lines.append("---")
            lines.append("")
        lines.append("*由听风自动生成*")

        md_path.write_text("\n".join(lines), encoding="utf-8")
        json_path.write_text(
            json.dumps({
                "creators": results,
                "insights": insights,
                "refresh": refresh_summary,
                "stats": {
                    "new_signals": total_new_signals,
                    "repeats": total_repeats,
                },
            }, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return md_path, json_path

    @staticmethod
    def _format_refresh_summary(refresh_summary: Optional[dict]) -> list[str]:
        if not refresh_summary:
            return []
        details = refresh_summary.get("details") or []
        problem_details = [
            d for d in details
            if d.get("status") not in ("succeeded", "skipped")
        ]
        if not problem_details:
            return []
        lines = [
            "## 本次刷新状态",
            "",
            "> 部分来源未完整纳入本次报告；未完成的下载、转录或观点判定会在后续刷新中继续补跑。",
            "",
        ]
        for d in problem_details[:8]:
            name = d.get("source") or d.get("source_id") or "未知来源"
            status = d.get("status") or "unknown"
            errors = d.get("errors") or []
            first = errors[0].get("message") if errors and isinstance(errors[0], dict) else d.get("error", "")
            lines.append(f"- {name}: {status}" + (f"（{first[:80]}）" if first else ""))
        return lines

    @staticmethod
    def _format_insights(insights: Optional[dict]) -> list[str]:
        """把跨博主趋势提炼结果格式化成 markdown 段落"""
        if not insights or not insights.get("trends"):
            # 有信号但没形成趋势时，也显示一句说明（让用户知道系统做了分析）
            if insights and insights.get("raw_signal_count", 0) >= 2:
                days = insights.get("days", 14)
                return [
                    f"## 🌐 本期行业信号（近 {days} 天）",
                    "",
                    f"> 分析了 {insights.get('raw_signal_count', 0)} 条新信号，"
                    "各博主观点较分散，未形成明显共同趋势。",
                    "",
                    "---",
                ]
            return []
        trends = insights["trends"]
        days = insights.get("days", 14)
        raw_count = insights.get("raw_signal_count", 0)
        lines = [
            f"## 🌐 本期行业信号（近 {days} 天 · {raw_count} 条新信号）",
            "",
            "*多个博主同时在讲的观点，往往是正在形成的行业信号。*",
            "",
        ]
        for t in trends:
            momentum = t.get("momentum", "→ 稳定")
            sources = t.get("source_names", [])
            cnt = t.get("signal_count", len(sources))
            is_hot = cnt >= 3 or "升温" in momentum
            icon = "🔥" if is_hot else "•"
            sources_str = "、".join(sources[:4]) + (" 等" if len(sources) > 4 else "")
            lines.append(f"- {icon} **「{t.get('trend', '')}」** — {sources_str} 都在讲（{cnt} 信号，{momentum}）")
            if t.get("why_hot"):
                lines.append(f"  - {t['why_hot']}")
        lines.extend(["", "---", ""])
        return lines

    @staticmethod
    def _make_summary(results: list[dict]) -> str:
        names = "、".join(r["name"] for r in results[:5])
        total_new = sum(r.get("new_signal_count", 0) for r in results)
        total_all = sum(r["new_count"] for r in results)
        if total_new > 0:
            return f"本期 {len(results)} 个源（{names}）：🆕 {total_new} 条新观点，共 {total_all} 条内容"
        return f"本期 {len(results)} 个源（{names}）：{total_all} 条内容均与既有观点重复，无新增"
