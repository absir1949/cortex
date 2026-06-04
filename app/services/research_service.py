"""按需研究 - 输入问题 → 搜抖音 → 下载转录评论 → AI 回答"""
from __future__ import annotations
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from app.db.engine import get_session
from app.db.repos import ReportRepo
from app.db.schema import Report
from app.models.content import Content
from app.models.group import ReportKind
from app.platforms import get_adapter, Capability
from app.services import config_service
from app.services.knowledge_service import KnowledgeService
from app.storage import paths, ContentCache


class ResearchService:

    def __init__(self):
        self.knowledge = KnowledgeService()
        self.cache = ContentCache()

    def run(
        self,
        question: str,
        *,
        group_id: Optional[int] = None,
        task_id: str = "",
        platforms: Optional[list[str]] = None,
        days: Optional[int] = 7,
        search_limit: Optional[int] = 10,
        comment_top_n: Optional[int] = 20,
        progress_cb: Optional[Callable[[dict], None]] = None,
        log_cb: Optional[Callable[[str], None]] = None,
        is_cancelled: Optional[Callable[[], bool]] = None,
    ) -> dict:
        """执行一次研究。返回 {report_id, report_path, evidence_count, answer}"""
        # 默认参数
        sys_cfg = config_service.effective_for_group(group_id) if group_id else config_service.all_system_values(redact_secrets=False)
        limit = search_limit or sys_cfg.get("research_search_limit", 10)
        top_n = comment_top_n or sys_cfg.get("comment_top_n", 20)
        platform_list = platforms or ["douyin"]

        workspace = paths.research_dir_for_task(task_id or datetime.now().strftime("research_%Y%m%d_%H%M%S"))
        workspace.mkdir(parents=True, exist_ok=True)
        (workspace / "inputs").mkdir(exist_ok=True)
        (workspace / "comments").mkdir(exist_ok=True)
        (workspace / "transcripts").mkdir(exist_ok=True)

        # 缓存命中统计（用于日志展示）
        stats = {"transcript_hit": 0, "comment_hit": 0, "video_hit": 0, "total": 0}

        self._log(log_cb, f"问题：{question}")
        self._log(log_cb, f"平台：{platform_list} | 近 {days} 天 | 最多 {limit} 条")

        # ----- 1. 搜索 -----
        self._progress(progress_cb, {"stage": "searching", "done": 0, "total": 1})
        all_contents: list[tuple[str, Content]] = []  # (platform, content)
        for plat in platform_list:
            adapter = get_adapter(plat)
            if not adapter or not adapter.has(Capability.SEARCH):
                self._log(log_cb, f"[skip] {plat} 不支持搜索")
                continue
            try:
                found = adapter.search(question, limit=limit, days=days)
                self._log(log_cb, f"[{plat}] 搜索到 {len(found)} 条")
                for c in found:
                    all_contents.append((plat, c))
            except Exception as e:
                self._log(log_cb, f"[{plat}] 搜索失败: {e}")

        if not all_contents:
            raise RuntimeError("没有搜索到任何内容")

        self._cancel_check(is_cancelled)
        self._progress(progress_cb, {"stage": "fetched_search", "found": len(all_contents)})

        # ----- 2. 下载 + 转录（并行） -----
        evidence_items: list[dict] = []
        total = len(all_contents)

        def work(idx: int, plat: str, c: Content) -> dict:
            """单条：查缓存 → 下载 → 转录 → 评论 → 写 cache → 返回 evidence"""
            adapter = get_adapter(plat)
            item = {
                "content_id": c.content_id,
                "platform": plat,
                "url": c.url,
                "author": c.author_name,
                "title": c.title,
                "create_time": c.create_time,
                "transcript": None,
                "comments": [],
                "from_cache": {"transcript": False, "comments": False, "video": False},
            }
            cid = c.content_id

            # ---- 1. 转录：先查缓存 ----
            cached_transcript = self.cache.get_transcript(cid)
            if cached_transcript:
                item["transcript"] = cached_transcript
                item["from_cache"]["transcript"] = True
                stats["transcript_hit"] += 1
            else:
                # 视频文件：先查缓存，没有再下载
                cached_video = self.cache.get_video_path(cid)
                if cached_video:
                    local_video = cached_video
                    item["from_cache"]["video"] = True
                    stats["video_hit"] += 1
                else:
                    local_video = workspace / "inputs" / f"{cid}.mp4"
                    downloaded = False
                    if c.media_urls and adapter.has(Capability.DOWNLOAD_MEDIA):
                        try:
                            downloaded = adapter.download_media(c, str(local_video))
                        except Exception as e:
                            self._log(log_cb, f"  [{cid[:8]}] 下载失败: {e}")
                    if not downloaded:
                        local_video = None

                # 转录（可关）
                if local_video and sys_cfg.get("transcribe_enabled", True) and c.should_transcribe():
                    try:
                        from app.transcribe import transcribe_video
                        transcript = transcribe_video(str(local_video))
                        item["transcript"] = transcript
                        # 落盘到 cache 供以后复用
                        (workspace / "transcripts" / f"{cid}.txt").write_text(transcript, encoding="utf-8")
                    except Exception as e:
                        self._log(log_cb, f"  [{cid[:8]}] 转录失败: {e}")

            # ---- 2. 评论：先查缓存 ----
            cached_comments = self.cache.get_comments(cid)
            if cached_comments is not None:
                item["comments"] = cached_comments
                item["from_cache"]["comments"] = True
                stats["comment_hit"] += 1
            elif adapter.has(Capability.FETCH_COMMENTS):
                try:
                    comments = adapter.fetch_comments(cid, top_n=top_n, fetch_replies=True)
                    item["comments"] = [cm.model_dump() for cm in comments]
                    (workspace / "comments" / f"{cid}.json").write_text(
                        json.dumps(item["comments"], ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                except Exception as e:
                    self._log(log_cb, f"  [{cid[:8]}] 评论失败: {e}")

            stats["total"] += 1
            return item

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = {pool.submit(work, i, plat, c): (i, plat, c)
                       for i, (plat, c) in enumerate(all_contents)}
            done = 0
            for fut in as_completed(futures):
                if is_cancelled and is_cancelled():
                    break
                try:
                    item = fut.result()
                    evidence_items.append(item)
                except Exception as e:
                    self._log(log_cb, f"  处理失败: {e}")
                done += 1
                self._progress(progress_cb, {
                    "stage": "collecting",
                    "done": done,
                    "total": total,
                })

        self._cancel_check(is_cancelled)

        # 命中统计
        if stats["total"] > 0:
            self._log(
                log_cb,
                f"缓存命中: 转录 {stats['transcript_hit']}/{stats['total']}，"
                f"评论 {stats['comment_hit']}/{stats['total']}，"
                f"视频 {stats['video_hit']}/{stats['total']}",
            )

        # 过滤掉没有任何信号的条目（既没转录也没评论）
        usable = [it for it in evidence_items if it.get("transcript") or it.get("comments")]
        self._log(log_cb, f"证据可用: {len(usable)} / {len(evidence_items)} 条")
        if not usable:
            raise RuntimeError("所有内容都没有可用证据（转录+评论都空）")

        # ----- 3. LLM 回答 -----
        self._progress(progress_cb, {"stage": "answering"})
        self._log(log_cb, "调 LLM 汇总回答...")
        answer = self.knowledge.answer_question(question, usable)

        # ----- 4. 落地报告 -----
        report_md = workspace / "report.md"
        lines = [
            f"# 研究报告：{question}",
            f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"**证据条数**: {len(usable)}",
            "",
            "## 答案",
            "",
            answer,
            "",
            "## 证据来源",
            "",
        ]
        for i, it in enumerate(usable, 1):
            lines.append(f"### {i}. {it['author']} · {it['title'][:60]}")
            lines.append(f"- 平台：{it['platform']}  |  发布：{it.get('create_time','')[:10]}")
            lines.append(f"- URL：{it['url']}")
            if it.get("transcript"):
                lines.append(f"- 转录字数：{len(it['transcript'])}")
            if it.get("comments"):
                lines.append(f"- 评论条数：{len(it['comments'])}")
            lines.append("")
        lines.append("---")
        lines.append("*由 Cortex 按需研究自动生成*")
        report_md.write_text("\n".join(lines), encoding="utf-8")

        # 写 evidence.json（给之后检索用）
        (workspace / "evidence.json").write_text(
            json.dumps({
                "question": question,
                "answer": answer,
                "evidence": usable,
                "generated_at": datetime.now().isoformat(),
            }, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        # ----- 5. 落 reports 表 -----
        with get_session() as s:
            rep = ReportRepo(s).create(Report(
                group_id=group_id,
                task_id=task_id or None,
                kind=ReportKind.RESEARCH.value,
                title=f"研究：{question[:80]}",
                summary=(answer[:200] + ("..." if len(answer) > 200 else "")) if answer else "",
                content_md_path=str(report_md),
                content_json_path=str(workspace / "evidence.json"),
                sources_used=[{"platform": it["platform"], "content_id": it["content_id"], "url": it["url"]}
                              for it in usable],
            ))

        return {
            "report_id": rep.id,
            "report_path": str(report_md),
            "evidence_count": len(usable),
            "answer_preview": (answer[:500] + "...") if len(answer) > 500 else answer,
        }

    # ------ helpers ------

    @staticmethod
    def _log(cb, msg: str):
        if cb:
            cb(msg)
        else:
            print(msg)

    @staticmethod
    def _progress(cb, p: dict):
        if cb:
            cb(p)

    @staticmethod
    def _cancel_check(is_cancelled):
        if is_cancelled and is_cancelled():
            from app.tasks.runner import CancelledError
            raise CancelledError("task cancelled")
