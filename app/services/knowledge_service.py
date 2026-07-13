"""AI 知识提炼 - 基于观点信号和作者档案生成阶段报告"""
from __future__ import annotations
import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
from sqlmodel import select

from app.db.engine import get_session
from app.db.repos import GroupContentRepo, GroupRepo, ReportRepo, SignalRepo, SourceContentRepo, SourceRepo
from app.db.schema import GlobalContent, Report
from app.llm import LLMUsageContext, OpenAICompatClient, LLMMessage, chat_with_usage
from app.models.group import ReportKind
from app.services import config_service
from app.services.profile_service import ProfileManager
from app.storage import paths
from app.storage.fs import GlobalStorage


# 报告层只消费已沉淀的结构化观点，不再回读原始转录/评论。
MAX_PROFILE_CHARS = 6000
MAX_SIGNAL_BLOCK_CHARS = 12000
MAX_CREATOR_SUMMARY_BLOCK_CHARS = 16000


class KnowledgeService:
    """专题知识整理：Signal 卡片 -> 作者阶段摘要 -> 专题综合。"""

    def __init__(self):
        self.llm = OpenAICompatClient()
        self.profiles = ProfileManager()

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
        consumed_global_ids: list[int] = []
        global_buckets = self._collect_new_group_items(group_id, sources)

        for source in sources:
            new_items = global_buckets.get(source.id, [])
            if not new_items:
                continue

            period_summary = self._build_creator_period_summary(source, new_items)
            if not period_summary:
                continue
            analyzed_results.append(period_summary)

            # 标记已分析（只有 analysis 成功才标记）
            consumed_global_ids.extend([int(it["global_content_id"]) for it in new_items if it.get("global_content_id")])

        if not analyzed_results:
            return {"creators": [], "report_id": None, "report_path": None}

        insights = self._build_group_synthesis(group, analyzed_results)

        # 落地报告
        report_md, report_json_path = self._write_report(
            group.id,
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
                sources_used=[
                    {
                        "source_id": r["source_id"],
                        "creator_id": r.get("creator_id"),
                        "new_count": r["new_count"],
                        "new_signal_count": r.get("new_signal_count", 0),
                        "period_start": r.get("period_start"),
                        "period_end": r.get("period_end"),
                    }
                    for r in analyzed_results
                ],
            ))
            report_id = report.id
            if consumed_global_ids:
                GroupContentRepo(s).mark_analyzed(group_id, consumed_global_ids)

        return {
            "creators": analyzed_results,
            "report_id": report_id,
            "report_path": str(report_md),
        }

    def answer_question(
        self,
        question: str,
        evidence: list[dict],
        *,
        group_id: Optional[int] = None,
    ) -> str:
        """外部搜索问答用的 LLM 调用
        evidence = [{content_id, url, author, title, transcript?, comments: [{author, text, likes}]}]
        """
        llm_config = config_service.get_llm_config()
        template = config_service.prompt("research_prompt_template")
        evidence_block = self._build_evidence_block(evidence)
        prompt = template.format(question=question, evidence_block=evidence_block)

        return chat_with_usage(
            self.llm,
            [
                LLMMessage(role="system", content="你是电商行业分析师，基于证据回答问题，严谨并标注来源。"),
                LLMMessage(role="user", content=prompt),
            ],
            config=llm_config,
            usage_context=LLMUsageContext(
                operation="research_answer",
                group_id=group_id,
            ),
        )

    def answer_group_question(
        self,
        group_id: int,
        question: str,
        *,
        days: int = 30,
        limit: int = 12,
    ) -> dict:
        """问听风：只基于专题内已有材料回答，不触发外部搜索。"""
        with get_session() as s:
            group = GroupRepo(s).get(group_id)
            if not group:
                raise ValueError("group not found")

        evidence_pool = self.collect_group_evidence(
            group_id,
            question=question,
            days=days,
            limit=limit,
        )
        if not evidence_pool:
            return {
                "answer": "这个专题里还没有可用于回答的转录、评论或观点信号。先刷新专题，等内容进入知识库后再问会更准。",
                "evidence": [],
                "scope": "internal",
                "days": days,
                "evidence_count": 0,
            }

        prompt = self._build_group_ask_prompt(question, evidence_pool)
        try:
            answer = chat_with_usage(
                self.llm,
                [
                    LLMMessage(
                        role="system",
                        content=(
                            "你是听风的专题阅读助手。只能基于用户当前专题内给出的证据回答；"
                            "不要使用外部知识，不要编造来源。证据不足时要直说。"
                        ),
                    ),
                    LLMMessage(role="user", content=prompt),
                ],
                config=config_service.get_llm_config(),
                usage_context=LLMUsageContext(
                    operation="ask_answer",
                    group_id=group_id,
                ),
            )
        except Exception as e:
            raise RuntimeError(f"问听风失败：{e}") from e

        return {
            "answer": answer,
            "evidence": [
                {
                    "content_id": ev.get("content_id", ""),
                    "global_content_id": ev.get("global_content_id"),
                    "platform": ev.get("platform", ""),
                    "source_id": ev.get("source_id"),
                    "author": ev.get("author", ""),
                    "title": ev.get("title", ""),
                    "url": ev.get("url", ""),
                    "create_time": ev.get("create_time", ""),
                    "signal_summary": ev.get("signal_summary", ""),
                    "new_points": ev.get("new_points", []),
                    "snippet": ev.get("snippet", ""),
                }
                for ev in evidence_pool
            ],
            "scope": "internal",
            "days": days,
            "evidence_count": len(evidence_pool),
        }

    # ============ 内部 ============

    def collect_group_evidence(
        self,
        group_id: int,
        *,
        question: str,
        days: int,
        limit: int,
    ) -> list[dict]:
        """收集专题内可用于问听风的证据。

        证据来源统一走 GroupContent -> GlobalContent。外部搜索沉淀进专题后可能
        没有 SourceContent 关系，这类内容仍可作为问答证据，但不会进入作者报告链路。
        """
        return self._collect_group_evidence_global(
            group_id,
            question=question,
            days=days,
            limit=limit,
        )

    @staticmethod
    def _question_terms(question: str) -> list[str]:
        text = question.lower()
        raw = re.findall(r"[a-zA-Z0-9_\u4e00-\u9fff]+", text)
        stop = {
            "最近", "这些", "他们", "她们", "它们", "什么", "怎么", "如何",
            "观点", "变化", "强调", "一下", "哪些", "有没有", "关于", "这个",
            "那个", "专题", "作者", "内容",
        }
        terms: list[str] = []
        for token in raw:
            if token in stop:
                continue
            if re.fullmatch(r"[\u4e00-\u9fff]+", token) and len(token) > 4:
                # 中文长句没有空格时，用 2-4 字片段提高召回。
                for size in (4, 3, 2):
                    for i in range(0, len(token) - size + 1):
                        gram = token[i:i + size]
                        if gram not in stop and gram not in terms:
                            terms.append(gram)
            elif len(token) >= 2:
                terms.append(token)
        return terms[:40]

    @staticmethod
    def _parse_time(value: str) -> Optional[datetime]:
        if not value:
            return None
        raw = value.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(raw)
            return parsed.replace(tzinfo=None) if parsed.tzinfo else parsed
        except ValueError:
            pass
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                return datetime.strptime(value[:len(fmt)], fmt)
            except ValueError:
                continue
        return None

    def _collect_group_evidence_global(
        self,
        group_id: int,
        *,
        question: str,
        days: int,
        limit: int,
    ) -> list[dict]:
        terms = self._question_terms(question)
        cutoff = datetime.now() - timedelta(days=days)
        candidates: list[dict] = []
        with get_session() as s:
            global_ids = GroupContentRepo(s).list_global_ids_by_group(group_id, limit=1000)
            if not global_ids:
                return []
            global_items = s.exec(select(GlobalContent).where(GlobalContent.id.in_(global_ids))).all()
            source_content_repo = SourceContentRepo(s)
            for global_item in global_items:
                created = self._parse_time(global_item.create_time)
                if created and created < cutoff:
                    continue
                sig = SignalRepo(s).get_by_content(
                    0,
                    global_item.content_id,
                    global_content_id=global_item.id,
                )
                linked_sources = source_content_repo.sources_for_global_in_group(group_id, global_item.id)
                source = linked_sources[0] if linked_sources else None
                storage = GlobalStorage(global_item.platform, global_item.creator_id)
                transcript = storage.get_transcript(global_item.content_id) or ""
                comments = storage.get_comments(global_item.content_id) or []
                if not transcript and not comments and not sig:
                    continue

                comment_text = "\n".join((c.get("text", "") or "") for c in comments[:12])
                signal_summary = sig.summary if sig else ""
                new_points = list(sig.new_points or []) if sig else []
                searchable = "\n".join([
                    global_item.title,
                    signal_summary,
                    "\n".join(new_points),
                    transcript,
                    comment_text,
                ]).lower()
                term_score = sum(1 for t in terms if t and t in searchable)
                signal_score = 2 if sig and sig.is_new else (1 if sig else 0)
                recency_score = 0
                if created:
                    age_days = max(0, (datetime.now() - created).days)
                    recency_score = max(0, days - age_days) / max(days, 1)
                score = term_score * 3 + signal_score + recency_score
                if not terms:
                    score += recency_score

                snippet_source = transcript or comment_text or signal_summary
                candidates.append({
                    "score": score,
                    "global_content_id": global_item.id,
                    "platform": global_item.platform,
                    "content_id": global_item.content_id,
                    "source_id": source.id if source else None,
                    "author": (source.display_name if source else global_item.author_name) or "",
                    "title": global_item.title,
                    "url": global_item.url,
                    "create_time": global_item.create_time,
                    "transcript": transcript,
                    "comments": comments,
                    "signal_summary": signal_summary,
                    "new_points": new_points,
                    "snippet": snippet_source[:220].replace("\n", " "),
                })

        candidates.sort(key=lambda ev: (ev["score"], ev.get("create_time", "")), reverse=True)
        positive = [ev for ev in candidates if ev["score"] > 0]
        return positive[:limit] if positive else candidates[:limit]

    def _collect_new_group_items(self, group_id: int, sources: list) -> dict[int, list[dict]]:
        """从 GroupContent 水位收集本专题未分析内容，并按 source 分桶。
        """
        with get_session() as s:
            group_contents = GroupContentRepo(s).list_unanalyzed_by_group(group_id, limit=500)
            if not group_contents:
                return {}
            source_content_repo = SourceContentRepo(s)
            source_by_id = {src.id: src for src in sources}
            buckets: dict[int, list[dict]] = {}
            for group_content in group_contents:
                global_item = s.get(GlobalContent, group_content.global_content_id)
                if not global_item:
                    continue
                sig = SignalRepo(s).get_by_content(
                    0,
                    global_item.content_id,
                    global_content_id=global_item.id,
                )
                if sig is None:
                    continue
                linked_sources = source_content_repo.sources_for_global_in_group(group_id, global_item.id)
                source = linked_sources[0] if linked_sources else None
                if source is None or source.id not in source_by_id:
                    continue
                buckets.setdefault(source.id, []).append({
                    "global_content_id": global_item.id,
                    "platform": global_item.platform,
                    "creator_id": global_item.creator_id,
                    "content_id": global_item.content_id,
                    "title": global_item.title,
                    "url": global_item.url,
                    "author_name": global_item.author_name,
                    "create_time": global_item.create_time,
                    "has_signal": True,
                    "is_new_signal": bool(sig.is_new),
                    "signal_summary": sig.summary,
                    "signal_new_points": list(sig.new_points or []),
                    "signal_matched_points": list(sig.matched_points or []),
                })
        return buckets

    @classmethod
    def _build_group_ask_prompt(cls, question: str, evidence: list[dict]) -> str:
        evidence_block = cls._build_evidence_block(evidence)
        return (
            f"用户问题：{question}\n\n"
            "下面是当前专题内部已经采集、转录和判定过的材料。请只基于这些材料回答。\n\n"
            f"{evidence_block}\n\n"
            "请用中文输出：\n"
            "1. 先给 3-5 条直接结论；\n"
            "2. 再说明依据来自哪些作者/内容；\n"
            "3. 如果证据不足或只来自少数作者，要明确标注不确定性；\n"
            "4. 不要提外部资料，不要把没有证据的判断写成事实。"
        )

    def _build_creator_period_summary(self, source, items: list[dict]) -> Optional[dict]:
        """把本期内容压成作者阶段摘要。

        输入必须已经完成 Signal 判定；这里不读取原始转录，避免报告层重复消耗。
        """
        cards = self._build_signal_cards(source, items)
        if not cards:
            return None

        new_cards = [card for card in cards if card["is_new_signal"]]
        repeat_cards = [card for card in cards if not card["is_new_signal"]]
        if new_cards:
            analysis = self._summarize_creator_period(source, new_cards, repeat_cards)
        else:
            analysis = self._summarize_repeats(source, items)
        if not analysis:
            raise RuntimeError(f"作者阶段摘要为空: source_id={source.id}")

        dates = [card["create_time"][:10] for card in cards if card.get("create_time")]
        period_start = min(dates) if dates else None
        period_end = max(dates) if dates else None
        return {
            "name": source.display_name,
            "source_id": source.id,
            "creator_id": source.creator_id,
            "analysis": analysis,
            "new_count": len(cards),
            "new_signal_count": len(new_cards),
            "repeat_count": len(repeat_cards),
            "period_start": period_start,
            "period_end": period_end,
            "signal_cards": cards,
            "evidence_global_ids": [
                int(card["global_content_id"])
                for card in cards
                if card.get("global_content_id") is not None
            ],
        }

    def _summarize_creator_period(self, source, new_cards: list[dict], repeat_cards: list[dict]) -> Optional[str]:
        profile = self.profiles.load(source)[:MAX_PROFILE_CHARS]
        template = config_service.prompt("creator_period_prompt_template")
        prompt = template.format(
            creator_name=source.display_name,
            profile=profile,
            new_count=len(new_cards),
            repeat_count=len(repeat_cards),
            signal_cards_block=self._build_signal_cards_block(new_cards),
            repeat_cards_block=self._build_repeat_cards_block(repeat_cards),
        )
        text = chat_with_usage(
            self.llm,
            [
                LLMMessage(
                    role="system",
                    content=(
                        "你是听风的作者观点分析员。你只基于作者观点档案和本期观点卡片做阶段摘要，"
                        "不要要求原始转录，不要编造卡片外证据。"
                    ),
                ),
                LLMMessage(role="user", content=prompt),
            ],
            config=config_service.get_llm_config(),
            usage_context=LLMUsageContext(
                operation="report_creator_period",
                group_id=source.group_id,
                source_id=source.id,
                creator_id=source.creator_id,
            ),
        ).strip()
        if not text:
            raise RuntimeError(f"作者阶段摘要 LLM 返回为空: source_id={source.id}")
        return text

    @staticmethod
    def _build_signal_cards(source, items: list[dict]) -> list[dict]:
        cards: list[dict] = []
        for it in items:
            new_points = [str(p).strip() for p in (it.get("signal_new_points") or []) if str(p).strip()]
            matched_points = [str(p).strip() for p in (it.get("signal_matched_points") or []) if str(p).strip()]
            summary = str(it.get("signal_summary") or "").strip()
            content_id = str(it.get("content_id") or "")
            platform = str(it.get("platform") or getattr(source, "platform", "") or "")
            cards.append({
                "global_content_id": it.get("global_content_id"),
                "platform": platform,
                "content_id": content_id,
                "evidence_key": f"{platform}/{content_id}" if platform else content_id,
                "source_id": getattr(source, "id", None),
                "creator_id": getattr(source, "creator_id", None) or it.get("creator_id"),
                "source_name": getattr(source, "display_name", "") or it.get("author_name") or "",
                "title": str(it.get("title") or "").strip(),
                "url": str(it.get("url") or "").strip(),
                "create_time": str(it.get("create_time") or "").strip(),
                "is_new_signal": bool(it.get("is_new_signal")),
                "summary": summary,
                "new_points": new_points,
                "matched_points": matched_points,
            })
        return sorted(cards, key=lambda card: card.get("create_time") or "")

    @staticmethod
    def _build_signal_cards_block(cards: list[dict]) -> str:
        parts: list[str] = []
        for i, card in enumerate(cards, 1):
            lines = [
                f"### 卡片 {i}: {card.get('title') or card.get('content_id') or '无标题'}",
                f"- 时间: {card.get('create_time') or '未知'}",
                f"- 证据: {card.get('evidence_key') or card.get('content_id')}",
            ]
            if card.get("summary"):
                lines.append(f"- 单条摘要: {card['summary']}")
            if card.get("new_points"):
                lines.append("- 新增观点:")
                lines.extend(f"  - {p}" for p in card["new_points"])
            if card.get("matched_points"):
                lines.append("- 命中旧观点:")
                lines.extend(f"  - {p}" for p in card["matched_points"][:5])
            parts.append("\n".join(lines))
        block = "\n\n".join(parts)
        return block[:MAX_SIGNAL_BLOCK_CHARS]

    @staticmethod
    def _build_repeat_cards_block(cards: list[dict]) -> str:
        if not cards:
            return "（无重复内容）"
        points: list[str] = []
        titles: list[str] = []
        for card in cards:
            title = card.get("title") or card.get("content_id")
            if title and title not in titles:
                titles.append(title)
            for p in card.get("matched_points") or []:
                if p not in points:
                    points.append(p)
            if len(points) >= 8 and len(titles) >= 8:
                break
        lines = [f"本期 {len(cards)} 条内容命中既有观点，报告中折叠处理。"]
        if points:
            lines.append("重复/延续的观点：")
            lines.extend(f"- {p}" for p in points[:8])
        if titles:
            lines.append("涉及内容：")
            lines.extend(f"- {t}" for t in titles[:8])
        return "\n".join(lines)

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

    def _build_group_synthesis(self, group, results: list[dict]) -> Optional[dict]:
        """基于本次报告的作者阶段摘要做专题综合。

        这一步只看本期水位内的新观点卡片和作者摘要，保证洞察和报告一致。
        """
        new_cards = [
            card
            for result in results
            for card in result.get("signal_cards", [])
            if card.get("is_new_signal")
        ]
        if not new_cards:
            return None

        period = self._period_from_cards([
            card
            for result in results
            for card in result.get("signal_cards", [])
        ])
        source_names = {
            str(card.get("source_name") or "")
            for card in new_cards
            if card.get("source_name")
        }
        if len(new_cards) < 2 or len(source_names) < 2:
            return None

        summaries_block = self._build_creator_summaries_block(results)
        template = config_service.prompt("group_synthesis_prompt_template")
        prompt = template.format(
            group_name=getattr(group, "name", "") or str(getattr(group, "id", "")),
            creator_count=len(source_names),
            signal_count=len(new_cards),
            summaries_block=summaries_block,
        )
        raw = chat_with_usage(
            self.llm,
            [
                LLMMessage(
                    role="system",
                    content=(
                        "你是听风的专题分析员。你只基于本期作者阶段摘要做跨作者综合，"
                        "输出严格 JSON，不编造未出现的作者或证据。"
                    ),
                ),
                LLMMessage(role="user", content=prompt),
            ],
            config=config_service.get_llm_config(),
            usage_context=LLMUsageContext(
                operation="report_group_synthesis",
                group_id=getattr(group, "id", None),
            ),
        )

        parsed = self._parse_json(raw)
        if not parsed:
            raise RuntimeError("专题综合 LLM 返回不是合法 JSON")

        trends = []
        for trend in parsed.get("trends") or []:
            if not isinstance(trend, dict):
                continue
            source_list = self._as_str_list(trend.get("source_names"))
            try:
                count = int(float(trend.get("signal_count") or len(source_list)))
            except (TypeError, ValueError):
                count = len(source_list)
            trends.append({
                "trend": str(trend.get("trend") or "").strip(),
                "source_names": source_list,
                "signal_count": count,
                "momentum": str(trend.get("momentum") or "-> 稳定").strip(),
                "why_hot": str(trend.get("why_hot") or "").strip(),
            })
        trends = [t for t in trends if t["trend"]]
        return {
            "overview": str(parsed.get("overview") or "").strip(),
            "trends": trends,
            "questions": self._as_str_list(parsed.get("questions")),
            "raw_signal_count": len(new_cards),
            "creator_count": len(source_names),
            "period": period,
            "basis": "creator_period_summaries",
        }

    @staticmethod
    def _build_creator_summaries_block(results: list[dict]) -> str:
        parts: list[str] = []
        for result in results:
            cards = [card for card in result.get("signal_cards", []) if card.get("is_new_signal")]
            if not cards:
                continue
            lines = [
                f"## {result.get('name')}",
                f"- 本期新信号: {result.get('new_signal_count', 0)}",
                f"- 本期重复: {result.get('repeat_count', 0)}",
                f"- 覆盖时间: {result.get('period_start') or '未知'} 至 {result.get('period_end') or '未知'}",
                "",
                str(result.get("analysis") or "").strip(),
                "",
                "本期观点卡片：",
            ]
            for card in cards[:10]:
                lines.append(f"- {card.get('evidence_key')}: {card.get('summary') or card.get('title')}")
                for point in (card.get("new_points") or [])[:3]:
                    lines.append(f"  - {point}")
            parts.append("\n".join(lines))
        block = "\n\n---\n\n".join(parts)
        return block[:MAX_CREATOR_SUMMARY_BLOCK_CHARS]

    @staticmethod
    def _period_from_cards(cards: list[dict]) -> Optional[dict]:
        dates = [str(card.get("create_time") or "")[:10] for card in cards if card.get("create_time")]
        if not dates:
            return None
        return {"start": min(dates), "end": max(dates)}

    @staticmethod
    def _parse_json(text: str) -> Optional[dict]:
        if not text:
            return None
        try:
            return json.loads(text)
        except Exception:
            pass
        match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except Exception:
                pass
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except Exception:
                pass
        return None

    @staticmethod
    def _as_str_list(value) -> list[str]:
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        if isinstance(value, str) and value.strip():
            return [value.strip()]
        return []

    @staticmethod
    def _build_evidence_block(evidence: list[dict]) -> str:
        parts: list[str] = []
        for i, ev in enumerate(evidence, 1):
            header = f"【证据 {i}】{ev.get('author', '')} · {ev.get('title', '')[:50]}\n来源：{ev.get('url', '')}"
            body: list[str] = []
            if ev.get("signal_summary") or ev.get("new_points"):
                body.append("[观点信号]")
                if ev.get("signal_summary"):
                    body.append(f"  摘要：{ev.get('signal_summary')}")
                for p in ev.get("new_points") or []:
                    body.append(f"  - {p}")
            if ev.get("text"):
                text = ev["text"]
                body.append(f"[正文]\n{text[:1600]}" + ("..." if len(text) > 1600 else ""))
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
        group_id: int,
        results: list[dict],
        insights: Optional[dict] = None,
        refresh_summary: Optional[dict] = None,
    ) -> tuple[Path, Path]:
        dir_ = paths.knowledge_dir_for_group(group_id)
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
            "> 本报告基于已判定的观点信号和作者观点档案生成，不重复读取原始转录。",
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
        signal_cards = [
            card
            for result in results
            for card in result.get("signal_cards", [])
        ]
        json_path.write_text(
            json.dumps({
                "version": 2,
                "basis": "signal_cards+creator_profiles",
                "creators": results,
                "creator_period_summaries": results,
                "signal_cards": signal_cards,
                "insights": insights,
                "refresh": refresh_summary,
                "stats": {
                    "new_signals": total_new_signals,
                    "repeats": total_repeats,
                    "signal_cards": len(signal_cards),
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
                period = insights.get("period") or {}
                period_label = ""
                if period.get("start") and period.get("end"):
                    period_label = f"{period['start']} 至 {period['end']} · "
                return [
                    f"## 🌐 本期行业信号（{period_label}{insights.get('raw_signal_count', 0)} 条新信号）",
                    "",
                    f"> {insights.get('overview') or '各作者观点较分散，未形成明显共同趋势。'}",
                    "",
                    "---",
                ]
            return []
        trends = insights["trends"]
        raw_count = insights.get("raw_signal_count", 0)
        period = insights.get("period") or {}
        period_label = ""
        if period.get("start") and period.get("end"):
            period_label = f"{period['start']} 至 {period['end']} · "
        lines = [
            f"## 🌐 本期行业信号（{period_label}{raw_count} 条新信号）",
            "",
            f"> {insights.get('overview') or '多个作者同时在讲的观点，往往是正在形成的行业信号。'}",
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
