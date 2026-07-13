"""外部资料搜索：问题 -> 平台搜索 -> 转录/评论 -> 问听风回答。"""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from app.db.engine import get_session
from app.db.repos import GlobalContentRepo, GroupContentRepo
from app.models.content import Content, ContentType
from app.platforms import Capability, get_adapter
from app.services import config_service
from app.services.knowledge_service import KnowledgeService
from app.storage import paths
from app.storage.fs import GlobalStorage


class ResearchService:
    """搜索外部资料并生成问听风回答。

    这层只负责外部证据生产，不再创建 Report。阶段性报告由 KnowledgeService
    消费 GroupContent 水位单独生成，产品入口和数据语义保持分离。
    """

    def __init__(self):
        self.knowledge = KnowledgeService()

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
        internal_evidence: Optional[list[dict]] = None,
        progress_cb: Optional[Callable[[dict], None]] = None,
        log_cb: Optional[Callable[[str], None]] = None,
        is_cancelled: Optional[Callable[[], bool]] = None,
    ) -> dict:
        """执行一次外部搜索问答。返回 {answer, evidence, evidence_count, evidence_path}。"""
        sys_cfg = (
            config_service.effective_for_group(group_id)
            if group_id
            else config_service.all_system_values(redact_secrets=False)
        )
        limit = search_limit or sys_cfg.get("research_search_limit", 10)
        top_n = comment_top_n if comment_top_n is not None else sys_cfg.get("comment_top_n", 20)
        from app.platforms import list_platforms

        platform_list = platforms or list_platforms()
        workspace = paths.research_dir_for_task(task_id or datetime.now().strftime("research_%Y%m%d_%H%M%S"))
        workspace.mkdir(parents=True, exist_ok=True)
        (workspace / "inputs").mkdir(exist_ok=True)
        (workspace / "comments").mkdir(exist_ok=True)
        (workspace / "transcripts").mkdir(exist_ok=True)

        stats = {"transcript_hit": 0, "comment_hit": 0, "video_hit": 0, "total": 0}
        internal_evidence = list(internal_evidence or [])

        self._log(log_cb, f"问题：{question}")
        self._log(log_cb, f"内部证据：{len(internal_evidence)} 条")
        self._log(log_cb, f"外部平台：{platform_list} | 近 {days} 天 | 最多 {limit} 条")

        self._progress(progress_cb, {"stage": "searching", "done": 0, "total": 1})
        all_contents: list[tuple[str, Content]] = []
        for platform in platform_list:
            adapter = get_adapter(platform)
            if not adapter:
                raise RuntimeError(f"未知平台：{platform}")
            if not adapter.has(Capability.SEARCH):
                self._log(log_cb, f"[skip] {platform} 不支持搜索")
                continue
            found = adapter.search(question, limit=limit, days=days)
            self._log(log_cb, f"[{platform}] 搜索到 {len(found)} 条")
            for content in found:
                all_contents.append((platform, content))

        if not all_contents:
            raise RuntimeError("外部搜索没有找到任何内容")

        self._cancel_check(is_cancelled)
        self._progress(progress_cb, {"stage": "fetched_search", "found": len(all_contents)})

        external_evidence: list[dict] = []
        total = len(all_contents)

        def work(platform: str, content: Content) -> dict:
            adapter = get_adapter(platform)
            if not adapter:
                raise RuntimeError(f"未知平台：{platform}")

            content_id = content.content_id
            storage = GlobalStorage(platform, None)
            item = {
                "kind": "content",
                "content_id": content_id,
                "platform": platform,
                "content_type": self._content_type_value(content),
                "url": content.url,
                "author_id": content.author_id,
                "author": content.author_name,
                "title": content.title,
                "text": (content.text or "").strip(),
                "create_time": content.create_time,
                "statistics": content.statistics or {},
                "transcript": None,
                "comments": [],
                "from_cache": {"transcript": False, "comments": False, "video": False},
            }

            cached_transcript = storage.get_transcript(content_id)
            if cached_transcript:
                item["transcript"] = cached_transcript
                item["from_cache"]["transcript"] = True
                stats["transcript_hit"] += 1
            else:
                local_video: Optional[Path] = None
                cached_video = storage.get_video_path(content_id)
                if cached_video:
                    local_video = cached_video
                    item["from_cache"]["video"] = True
                    stats["video_hit"] += 1
                elif content.media_urls and adapter.has(Capability.DOWNLOAD_MEDIA):
                    local_video = workspace / "inputs" / f"{content_id}.mp4"
                    downloaded = adapter.download_media(content, str(local_video))
                    if downloaded:
                        try:
                            storage.save_video(content_id, str(local_video), content.create_time)
                        except Exception as e:
                            self._log(log_cb, f"  [{content_id[:8]}] 视频入库失败: {e}")
                    else:
                        local_video = None

                if local_video and sys_cfg.get("transcribe_enabled", True) and content.should_transcribe():
                    try:
                        from app.transcribe import transcribe_video

                        transcript = transcribe_video(str(local_video)).strip()
                        if transcript:
                            item["transcript"] = transcript
                            (workspace / "transcripts" / f"{content_id}.txt").write_text(transcript, encoding="utf-8")
                    except Exception as e:
                        self._log(log_cb, f"  [{content_id[:8]}] 转录失败: {e}")

            cached_comments = storage.get_comments(content_id)
            if cached_comments is not None:
                item["comments"] = cached_comments
                item["from_cache"]["comments"] = True
                stats["comment_hit"] += 1
            elif adapter.has(Capability.FETCH_COMMENTS) and top_n > 0:
                try:
                    comments = adapter.fetch_comments(
                        content_id,
                        top_n=top_n,
                        fetch_replies=True,
                        creator_id=content.author_id,
                    )
                    item["comments"] = [comment.model_dump() for comment in comments]
                    (workspace / "comments" / f"{content_id}.json").write_text(
                        json.dumps(item["comments"], ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                except Exception as e:
                    self._log(log_cb, f"  [{content_id[:8]}] 评论失败: {e}")

            stats["total"] += 1
            return item

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = {
                pool.submit(work, platform, content): (platform, content)
                for platform, content in all_contents
            }
            done = 0
            for fut in as_completed(futures):
                if is_cancelled and is_cancelled():
                    break
                try:
                    external_evidence.append(fut.result())
                except Exception as e:
                    self._log(log_cb, f"  处理失败: {e}")
                done += 1
                self._progress(progress_cb, {"stage": "collecting", "done": done, "total": total})

        self._cancel_check(is_cancelled)

        if stats["total"] > 0:
            self._log(
                log_cb,
                f"全局缓存命中: 转录 {stats['transcript_hit']}/{stats['total']}，"
                f"评论 {stats['comment_hit']}/{stats['total']}，"
                f"视频 {stats['video_hit']}/{stats['total']}",
            )

        usable_external = [
            item
            for item in external_evidence
            if item.get("transcript") or item.get("text") or item.get("comments")
        ]
        self._log(log_cb, f"外部证据可用: {len(usable_external)} / {len(external_evidence)} 条")
        if not usable_external:
            raise RuntimeError("外部搜索结果没有可用证据（正文、转录和评论都为空）")

        if group_id:
            self._persist_external_evidence(group_id, usable_external)

        combined_evidence = internal_evidence + usable_external
        if not combined_evidence:
            raise RuntimeError("没有可用于回答的证据")

        self._progress(progress_cb, {"stage": "answering"})
        self._log(log_cb, "调 LLM 汇总回答...")
        answer = self.knowledge.answer_question(question, combined_evidence, group_id=group_id)

        evidence_payload = {
            "question": question,
            "answer": answer,
            "internal_evidence_count": len(internal_evidence),
            "external_evidence_count": len(usable_external),
            "evidence": combined_evidence,
            "generated_at": datetime.now().isoformat(),
        }
        evidence_path = workspace / "evidence.json"
        evidence_path.write_text(json.dumps(evidence_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        answer_path = workspace / "answer.md"
        answer_path.write_text(answer, encoding="utf-8")

        ask_evidence = self._ask_evidence(combined_evidence)
        return {
            "answer": answer,
            "answer_path": str(answer_path),
            "evidence_path": str(evidence_path),
            "evidence_count": len(ask_evidence),
            "internal_evidence_count": len(internal_evidence),
            "external_evidence_count": len(usable_external),
            "evidence": ask_evidence,
        }

    # ------ persistence ------

    @staticmethod
    def _content_type_value(content: Content) -> str:
        raw = content.content_type
        return str(raw.value if hasattr(raw, "value") else raw)

    def _persist_external_evidence(self, group_id: int, evidence: list[dict]) -> None:
        with get_session() as session:
            global_repo = GlobalContentRepo(session)
            group_repo = GroupContentRepo(session)
            for item in evidence:
                content = Content(
                    content_id=item["content_id"],
                    platform=item["platform"],
                    content_type=ContentType(item.get("content_type") or ContentType.VIDEO.value),
                    url=item.get("url", ""),
                    author_id=item.get("author_id", ""),
                    author_name=item.get("author", ""),
                    title=item.get("title", ""),
                    text=item.get("text", ""),
                    create_time=item.get("create_time", ""),
                    statistics=item.get("statistics") or {},
                )
                global_item = global_repo.upsert_from_content(content)
                if global_item.id is None:
                    raise RuntimeError("global content persisted without id")

                group_repo.upsert(group_id=group_id, global_content_id=global_item.id)
                item["global_content_id"] = global_item.id

                storage = GlobalStorage(item["platform"], global_item.creator_id)
                storage.save_metadata(item["content_id"], {
                    "platform": item["platform"],
                    "content_id": item["content_id"],
                    "content_type": item.get("content_type", ""),
                    "title": item.get("title", ""),
                    "author_id": item.get("author_id", ""),
                    "author": item.get("author", ""),
                    "url": item.get("url", ""),
                    "create_time": item.get("create_time", ""),
                    "statistics": item.get("statistics") or {},
                    "external_search_at": datetime.now().isoformat(),
                })
                text_for_storage = (item.get("transcript") or item.get("text") or "").strip()
                if text_for_storage:
                    storage.save_transcript(item["content_id"], text_for_storage, item.get("create_time"))
                if item.get("comments"):
                    storage.save_comments(item["content_id"], item["comments"], item.get("create_time"))

                global_repo.update_stage(
                    global_item.id,
                    transcript_status="succeeded" if text_for_storage else "skipped",
                    comments_status="succeeded" if item.get("comments") else "skipped",
                    signal_status="pending",
                )

    @staticmethod
    def _ask_evidence(evidence: list[dict]) -> list[dict]:
        rows: list[dict] = []
        for item in evidence:
            rows.append({
                "kind": "content",
                "content_id": item.get("content_id", ""),
                "global_content_id": item.get("global_content_id"),
                "platform": item.get("platform", ""),
                "source_id": item.get("source_id"),
                "author": item.get("author", ""),
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "create_time": item.get("create_time", ""),
                "signal_summary": item.get("signal_summary", ""),
                "new_points": item.get("new_points", []),
                "snippet": (
                    item.get("snippet")
                    or item.get("transcript")
                    or item.get("text")
                    or " ".join(str(c.get("text", "")) for c in (item.get("comments") or [])[:3])
                )[:220].replace("\n", " "),
            })
        return rows

    # ------ helpers ------

    @staticmethod
    def _log(cb, msg: str):
        if cb:
            cb(msg)
        else:
            print(msg)

    @staticmethod
    def _progress(cb, progress: dict):
        if cb:
            cb(progress)

    @staticmethod
    def _cancel_check(is_cancelled):
        if is_cancelled and is_cancelled():
            from app.tasks.runner import CancelledError

            raise CancelledError("task cancelled")
