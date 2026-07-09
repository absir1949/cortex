"""刷新流水线 - 按状态补齐 内容→转录→观点信号→观点档案"""
from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from app.db.engine import get_session
from app.db.repos import ContentRepo, GroupRepo, RefreshRunRepo, SignalRepo, SourceRepo
from app.db.schema import Source
from app.models.content import Content
from app.platforms import get_adapter, Capability
from app.services import config_service
from app.storage.fs import StorageManager


STATUS_PENDING = "pending"
STATUS_SUCCEEDED = "succeeded"
STATUS_FAILED = "failed"
STATUS_SKIPPED = "skipped"
STATUS_CANCELED = "canceled"


class IngestService:
    """刷新服务 - 对单个源或整个专题运行可补偿的处理流水线"""

    # ============ public API ============

    def run_group(
        self,
        group_id: int,
        *,
        force: bool = False,
        progress_cb: Optional[Callable[[dict], None]] = None,
        log_cb: Optional[Callable[[str], None]] = None,
        is_cancelled: Optional[Callable[[], bool]] = None,
        task_id: Optional[str] = None,
    ) -> dict:
        """刷新一个专题下所有启用 source，返回刷新统计。"""
        with get_session() as s:
            group = GroupRepo(s).get(group_id)
            sources = SourceRepo(s).list_by_group(group_id, enabled_only=True)
        if not group:
            raise ValueError(f"group {group_id} not found")

        with get_session() as s:
            group_run = RefreshRunRepo(s).start(
                scope="group",
                group_id=group_id,
                task_id=task_id,
            )

        summary = {
            "group_id": group_id,
            "refresh_run_id": group_run.id,
            "sources_run": 0,
            "new_contents_total": 0,
            "counts": self._empty_counts(),
            "details": [],
            "errors": [],
        }

        from app.tasks.runner import CancelledError
        try:
            for i, source in enumerate(sources, 1):
                self._check_cancelled(is_cancelled)
                if not force and self._should_skip(source):
                    self._log(log_cb, f"[skip] {source.display_name}: 距上次检查不足 interval_hours")
                    summary["details"].append({
                        "source_id": source.id,
                        "source": source.display_name,
                        "status": STATUS_SKIPPED,
                        "reason": "interval",
                    })
                    continue

                if progress_cb:
                    progress_cb({
                        "stage": "ingesting",
                        "done": i - 1,
                        "total": len(sources),
                        "current": source.display_name,
                    })
                self._log(log_cb, f"[{i}/{len(sources)}] 刷新源: {source.display_name}")

                try:
                    result = self.refresh_source(
                        source,
                        log_cb=log_cb,
                        is_cancelled=is_cancelled,
                        force=force,
                        parent_run_id=group_run.id,
                        task_id=task_id,
                    )
                    summary["sources_run"] += 1
                    self._merge_counts(summary["counts"], result["counts"])
                    summary["new_contents_total"] += result["counts"].get("new_contents", 0)
                    summary["details"].append({
                        "source_id": source.id,
                        "source": source.display_name,
                        "status": result["status"],
                        "refresh_run_id": result.get("refresh_run_id"),
                        "counts": result["counts"],
                        "errors": result.get("errors", []),
                    })
                    if result["status"] != STATUS_SUCCEEDED:
                        summary["errors"].append({
                            "source_id": source.id,
                            "source": source.display_name,
                            "status": result["status"],
                            "errors": result.get("errors", []),
                        })
                except CancelledError:
                    raise
                except Exception as e:
                    msg = str(e)
                    self._log(log_cb, f"[error] {source.display_name}: {msg}")
                    summary["details"].append({
                        "source_id": source.id,
                        "source": source.display_name,
                        "status": STATUS_FAILED,
                        "error": msg,
                    })
                    summary["errors"].append({
                        "source_id": source.id,
                        "source": source.display_name,
                        "error": msg,
                    })
        except CancelledError:
            summary["status"] = STATUS_CANCELED
            with get_session() as s:
                RefreshRunRepo(s).finish(
                    group_run.id,
                    status=STATUS_CANCELED,
                    counts=summary["counts"],
                    errors=summary["errors"],
                )
            self._log(log_cb, "任务被取消")
            raise

        if progress_cb:
            progress_cb({"stage": "done", "total": len(sources), "done": len(sources)})

        if summary["errors"] and summary["sources_run"] == 0:
            status = STATUS_FAILED
        elif summary["errors"]:
            status = "partial_failed"
        else:
            status = STATUS_SUCCEEDED
        summary["status"] = status

        with get_session() as s:
            RefreshRunRepo(s).finish(
                group_run.id,
                status=status,
                counts=summary["counts"],
                errors=summary["errors"],
            )
        return summary

    def run_source(
        self,
        source: Source,
        *,
        log_cb: Optional[Callable[[str], None]] = None,
        is_cancelled: Optional[Callable[[], bool]] = None,
        force: bool = False,
        days_override: Optional[int] = None,
    ) -> int:
        """兼容旧调用：返回本次新发现内容数。"""
        result = self.refresh_source(
            source,
            log_cb=log_cb,
            is_cancelled=is_cancelled,
            force=force,
            days_override=days_override,
        )
        return int(result["counts"].get("new_contents", 0))

    def refresh_source(
        self,
        source: Source,
        *,
        log_cb: Optional[Callable[[str], None]] = None,
        is_cancelled: Optional[Callable[[], bool]] = None,
        force: bool = False,
        days_override: Optional[int] = None,
        parent_run_id: Optional[int] = None,
        task_id: Optional[str] = None,
    ) -> dict:
        """刷新单个 source：发现内容，并补齐缺失处理阶段。"""
        adapter = get_adapter(source.platform)
        if not adapter:
            raise RuntimeError(f"unsupported platform: {source.platform}")

        config = config_service.effective_for_source(source.id)
        days = days_override if days_override is not None else config.get("days")
        storage = StorageManager(source.directory)
        counts = self._empty_counts()
        errors: list[dict] = []

        with get_session() as s:
            refresh_run = RefreshRunRepo(s).start(
                scope="source",
                group_id=source.group_id,
                source_id=source.id,
                parent_run_id=parent_run_id,
                task_id=task_id,
                lookback_days=days,
            )

        from app.tasks.runner import CancelledError
        try:
            self._check_cancelled(is_cancelled)
            contents = self._fetch_contents(adapter, source, config, days)

            self._log(log_cb, f"  拿到 {len(contents)} 条候选")
            unique_contents = self._dedupe(contents)
            if len(unique_contents) != len(contents):
                self._log(log_cb, f"  候选去重: {len(contents)} → {len(unique_contents)} 条")

            counts["discovered"] = len(contents)
            counts["deduped"] = len(unique_contents)

            storage_ids = self._storage_content_ids(storage)
            with get_session() as s:
                known_ids = ContentRepo(s).known_ids(source.id)
            new_ids = {c.content_id for c in unique_contents if c.content_id not in known_ids and c.content_id not in storage_ids}
            counts["new_contents"] = len(new_ids)
            counts["known_contents"] = max(len(unique_contents) - len(new_ids), 0)
            self._log(log_cb, f"  新发现: {counts['new_contents']} 条（{counts['known_contents']} 条已知）")

            # 先把平台列表和本地已有文件都同步进 content_items，后续阶段只看状态补齐。
            for content in unique_contents:
                self._check_cancelled(is_cancelled)
                with get_session() as s:
                    ContentRepo(s).upsert_from_content(source, content)
                self._sync_file_state(source, storage, content.content_id)
            self._bootstrap_storage_metadata(source, storage)

            process_counts, process_errors = self._process_media_and_transcripts(
                source,
                adapter,
                storage,
                unique_contents,
                config,
                log_cb=log_cb,
                is_cancelled=is_cancelled,
            )
            self._merge_counts(counts, process_counts)
            errors.extend(process_errors)

            signal_counts, signal_errors = self._evaluate_missing_signals(
                source,
                storage,
                log_cb=log_cb,
                is_cancelled=is_cancelled,
            )
            self._merge_counts(counts, signal_counts)
            errors.extend(signal_errors)

            profile_counts, profile_errors = self._apply_missing_profiles(
                source,
                log_cb=log_cb,
                is_cancelled=is_cancelled,
            )
            self._merge_counts(counts, profile_counts)
            errors.extend(profile_errors)

            status = "partial_failed" if errors else STATUS_SUCCEEDED
            self._finish_source_refresh(source, refresh_run.id, status, counts, errors)
            return {
                "source_id": source.id,
                "source": source.display_name,
                "refresh_run_id": refresh_run.id,
                "status": status,
                "counts": counts,
                "errors": errors,
            }
        except CancelledError:
            self._finish_source_refresh(source, refresh_run.id, STATUS_CANCELED, counts, errors)
            raise
        except Exception as e:
            msg = str(e)
            errors.append({"stage": "refresh", "message": msg})
            counts["failed"] += 1
            self._finish_source_refresh(source, refresh_run.id, STATUS_FAILED, counts, errors)
            raise

    # ============ pipeline stages ============

    def _fetch_contents(self, adapter, source: Source, config: dict, days: Optional[int]) -> list[Content]:
        if source.type == "creator":
            if not adapter.has(Capability.FETCH_CREATOR):
                raise RuntimeError(f"{source.platform} 不支持博主采集")
            return adapter.fetch_creator_content(
                source.identifier,
                limit=config.get("content_limit", 50),
                days=days,
            )
        if source.type == "keyword":
            if not adapter.has(Capability.SEARCH):
                raise RuntimeError(f"{source.platform} 不支持关键词搜索")
            return adapter.search(
                source.identifier,
                limit=config.get("content_limit", 50),
                days=days,
            )
        raise RuntimeError(f"未知源类型: {source.type}")

    @staticmethod
    def _dedupe(contents: list[Content]) -> list[Content]:
        seen_ids = set()
        unique_contents = []
        for content in contents:
            if content.content_id in seen_ids:
                continue
            seen_ids.add(content.content_id)
            unique_contents.append(content)
        return unique_contents

    def _process_media_and_transcripts(
        self,
        source: Source,
        adapter,
        storage: StorageManager,
        contents: list[Content],
        config: dict,
        *,
        log_cb: Optional[Callable[[str], None]],
        is_cancelled: Optional[Callable[[], bool]],
    ) -> tuple[dict, list[dict]]:
        counts = self._empty_counts()
        errors: list[dict] = []
        max_workers = 2 if source.platform == "wechat_channels" else 5
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {
                pool.submit(self._process_content_assets, source, adapter, storage, content, config): content
                for content in contents
            }
            for fut in as_completed(futures):
                if is_cancelled and is_cancelled():
                    break
                content = futures[fut]
                try:
                    result = fut.result()
                except Exception as e:
                    result = {"errors": [{"stage": "asset", "content_id": content.content_id, "message": str(e)}]}

                self._merge_counts(counts, result.get("counts", {}))
                for err in result.get("errors", []):
                    errors.append(err)
                    self._log(log_cb, f"  [warn] {content.title[:30]} {err.get('message', '')}")

                transcript_len = result.get("transcript_len", 0)
                cached_tag = " [cache]" if result.get("cached") else ""
                if not result.get("errors"):
                    self._log(
                        log_cb,
                        f"  ✓ {content.title[:40]}{' [+' + str(transcript_len) + '字]' if transcript_len else ''}{cached_tag}",
                    )
        return counts, errors

    def _process_content_assets(
        self,
        source: Source,
        adapter,
        storage: StorageManager,
        content: Content,
        config: dict,
    ) -> dict:
        counts = self._empty_counts()
        errors: list[dict] = []
        transcript = storage.get_transcript(content.content_id)
        final_path = storage.get_video_path(content.content_id)
        file_size = final_path.stat().st_size if final_path else 0

        # 媒体下载：已有视频不重复下载；失败保留状态，后续刷新可重试。
        if content.should_transcribe() and adapter.has(Capability.DOWNLOAD_MEDIA):
            if final_path:
                self._update_content_stage(
                    source.id,
                    content.content_id,
                    media_status=STATUS_SUCCEEDED,
                    media_error="",
                    file_size=file_size,
                )
            else:
                tmp_path = f"/tmp/cortex_{source.id}_{content.content_id}.mp4"
                try:
                    if not adapter.download_media(content, tmp_path):
                        raise RuntimeError("下载失败")
                    file_size = Path(tmp_path).stat().st_size
                    storage.save_video(content.content_id, tmp_path, content.create_time)
                    Path(tmp_path).unlink(missing_ok=True)
                    final_path = storage.get_video_path(content.content_id)
                    counts["downloaded"] += 1
                    self._update_content_stage(
                        source.id,
                        content.content_id,
                        media_status=STATUS_SUCCEEDED,
                        media_error="",
                        file_size=file_size,
                    )
                except Exception as e:
                    msg = str(e)
                    errors.append({"stage": "download", "content_id": content.content_id, "message": msg})
                    counts["failed"] += 1
                    self._update_content_stage(
                        source.id,
                        content.content_id,
                        media_status=STATUS_FAILED,
                        media_error=msg,
                    )
        else:
            self._update_content_stage(source.id, content.content_id, media_status=STATUS_SKIPPED, media_error="")

        # 转录：已有转录直接复用；非视频文本内容可把正文当作 transcript。
        if config.get("transcribe_enabled", True) and content.should_transcribe():
            if transcript:
                self._update_content_stage(source.id, content.content_id, transcript_status=STATUS_SUCCEEDED, transcript_error="")
            elif final_path:
                try:
                    from app.storage.cache import ContentCache
                    cached = ContentCache().get_transcript(content.platform, content.content_id)
                    if cached:
                        transcript = cached
                    else:
                        from app.transcribe import transcribe_video
                        transcript = transcribe_video(str(final_path))
                    storage.save_transcript(content.content_id, transcript, content.create_time)
                    from app.api.contents import invalidate_transcript_cache
                    invalidate_transcript_cache(content.content_id, platform=content.platform)
                    # 转录成功后删除视频文件，只保留转录文本和元数据（省空间）
                    if final_path and final_path.exists():
                        final_path.unlink(missing_ok=True)
                    counts["transcribed"] += 1
                    self._update_content_stage(source.id, content.content_id, transcript_status=STATUS_SUCCEEDED, transcript_error="")
                except Exception as e:
                    msg = str(e)
                    errors.append({"stage": "transcribe", "content_id": content.content_id, "message": msg})
                    counts["failed"] += 1
                    self._update_content_stage(
                        source.id,
                        content.content_id,
                        transcript_status=STATUS_FAILED,
                        transcript_error=msg,
                    )
            else:
                msg = "缺少视频文件，无法转录"
                errors.append({"stage": "transcribe", "content_id": content.content_id, "message": msg})
                counts["failed"] += 1
                self._update_content_stage(source.id, content.content_id, transcript_status=STATUS_FAILED, transcript_error=msg)
        elif content.text:
            if not transcript:
                storage.save_transcript(content.content_id, content.text, content.create_time)
                transcript = content.text
                counts["transcribed"] += 1
            self._update_content_stage(source.id, content.content_id, transcript_status=STATUS_SUCCEEDED, transcript_error="")
        else:
            self._update_content_stage(source.id, content.content_id, transcript_status=STATUS_SKIPPED, transcript_error="")

        # 评论失败不阻断观点判定，但需要留下状态。
        if adapter.has(Capability.FETCH_COMMENTS):
            try:
                if storage.get_comments(content.content_id) is None:
                    comments = adapter.fetch_comments(
                        content.content_id,
                        top_n=config.get("comment_top_n", 20),
                        fetch_replies=True,
                        creator_id=source.identifier,
                    )
                    storage.save_comments(
                        content.content_id,
                        [cm.model_dump() for cm in comments],
                        content.create_time,
                    )
                    counts["comments"] += 1
                self._update_content_stage(source.id, content.content_id, comments_status=STATUS_SUCCEEDED, comments_error="")
            except Exception as e:
                msg = str(e)
                errors.append({"stage": "comments", "content_id": content.content_id, "message": msg})
                counts["failed"] += 1
                self._update_content_stage(source.id, content.content_id, comments_status=STATUS_FAILED, comments_error=msg)
        else:
            self._update_content_stage(source.id, content.content_id, comments_status=STATUS_SKIPPED, comments_error="")

        # 元数据文件仍然保留，作为本地可读缓存；DB 状态才是处理水位。
        storage.save_metadata(content.content_id, {
            "content_id": content.content_id,
            "title": content.title,
            "author": content.author_name,
            "author_id": content.author_id,
            "create_time": content.create_time,
            "platform": content.platform,
            "url": content.url,
            "statistics": content.statistics,
            "downloaded_at": datetime.now().isoformat(),
            "file_size": file_size,
            "transcribed": storage.has_transcript(content.content_id),
        })

        return {
            "counts": counts,
            "errors": errors,
            "transcript_len": len(storage.get_transcript(content.content_id) or ""),
            "cached": False,
        }

    def _evaluate_missing_signals(
        self,
        source: Source,
        storage: StorageManager,
        *,
        log_cb: Optional[Callable[[str], None]],
        is_cancelled: Optional[Callable[[], bool]],
    ) -> tuple[dict, list[dict]]:
        counts = self._empty_counts()
        errors: list[dict] = []
        with get_session() as s:
            ready_items = ContentRepo(s).list_ready_for_signal(source.id)
        if ready_items:
            self._log(log_cb, f"  待观点判定: {len(ready_items)} 条")

        from app.services.signal_service import SignalService
        signal_service = SignalService()

        for item in ready_items:
            if is_cancelled and is_cancelled():
                break
            transcript = storage.get_transcript(item.content_id)
            if not transcript:
                msg = "状态为已转录，但本地转录文件缺失"
                errors.append({"stage": "signal", "content_id": item.content_id, "message": msg})
                counts["failed"] += 1
                self._update_content_stage(
                    source.id,
                    item.content_id,
                    transcript_status=STATUS_FAILED,
                    transcript_error=msg,
                    signal_status=STATUS_PENDING,
                )
                continue

            with get_session() as s:
                existing = SignalRepo(s).get_by_content(source.id, item.content_id)
            if existing:
                updates = {"signal_status": STATUS_SUCCEEDED, "signal_error": ""}
                if not existing.is_new or not existing.new_points:
                    updates["profile_status"] = STATUS_SKIPPED
                    updates["profile_error"] = ""
                self._update_content_stage(source.id, item.content_id, **updates)
                continue

            try:
                self._check_cancelled(is_cancelled)
                sig = signal_service.evaluate(
                    source,
                    item.content_id,
                    transcript,
                    comments=storage.get_comments(item.content_id) or [],
                    create_time=item.create_time,
                    raise_on_failure=True,
                )
                if not sig:
                    raise RuntimeError("观点判定无结果")
                counts["signaled"] += 1
                profile_status = STATUS_SKIPPED
                profile_error = ""
                if sig.get("is_new") and sig.get("new_points"):
                    if sig.get("profile_error"):
                        profile_status = STATUS_FAILED
                        profile_error = sig.get("profile_error") or "观点档案更新失败"
                    else:
                        profile_status = STATUS_SUCCEEDED
                        counts["profile_updated"] += 1
                self._update_content_stage(
                    source.id,
                    item.content_id,
                    signal_status=STATUS_SUCCEEDED,
                    signal_error="",
                    profile_status=profile_status,
                    profile_error=profile_error,
                )
                if sig.get("is_new"):
                    self._log(log_cb, f"  🆕 新观点: {sig.get('summary','')[:40]}")
                else:
                    self._log(log_cb, f"  ♻️ 老调重弹（{len(sig.get('matched_points',[]))} 点命中档案）")
            except Exception as e:
                msg = str(e)
                errors.append({"stage": "signal", "content_id": item.content_id, "message": msg})
                counts["failed"] += 1
                self._update_content_stage(
                    source.id,
                    item.content_id,
                    signal_status=STATUS_FAILED,
                    signal_error=msg,
                )
                self._log(log_cb, f"  [warn] 观点判定失败: {item.title[:30]} {msg}")
        return counts, errors

    def _apply_missing_profiles(
        self,
        source: Source,
        *,
        log_cb: Optional[Callable[[str], None]],
        is_cancelled: Optional[Callable[[], bool]],
    ) -> tuple[dict, list[dict]]:
        counts = self._empty_counts()
        errors: list[dict] = []
        with get_session() as s:
            ready_items = ContentRepo(s).list_ready_for_profile(source.id)
        if ready_items:
            self._log(log_cb, f"  待观点档案更新: {len(ready_items)} 条")

        from app.services.profile_service import ProfileManager
        profile_manager = ProfileManager()

        for item in ready_items:
            self._check_cancelled(is_cancelled)
            with get_session() as s:
                sig = SignalRepo(s).get_by_content(source.id, item.content_id)
            if not sig:
                continue
            if not sig.is_new or not sig.new_points:
                self._update_content_stage(
                    source.id,
                    item.content_id,
                    profile_status=STATUS_SKIPPED,
                    profile_error="",
                )
                continue
            try:
                profile_manager.update(
                    source,
                    list(sig.new_points),
                    sig.summary,
                    date=item.create_time,
                )
                counts["profile_updated"] += 1
                self._update_content_stage(
                    source.id,
                    item.content_id,
                    profile_status=STATUS_SUCCEEDED,
                    profile_error="",
                )
                self._log(log_cb, f"  ✓ 观点档案已更新: {sig.summary[:40]}")
            except Exception as e:
                msg = str(e)
                counts["failed"] += 1
                errors.append({"stage": "profile", "content_id": item.content_id, "message": msg})
                self._update_content_stage(
                    source.id,
                    item.content_id,
                    profile_status=STATUS_FAILED,
                    profile_error=msg,
                )
                self._log(log_cb, f"  [warn] 观点档案更新失败: {item.title[:30]} {msg}")
        return counts, errors

    # ============ state helpers ============

    def _bootstrap_storage_metadata(self, source: Source, storage: StorageManager) -> None:
        """把历史文件纳入 content_items，使旧内容也能补判定/补档案。"""
        for md in storage.list_metadata():
            cid = md.get("content_id") or md.get("video_id")
            if not cid:
                continue
            with get_session() as s:
                ContentRepo(s).upsert_from_metadata(source, md)
            self._sync_file_state(source, storage, str(cid))

    def _sync_file_state(self, source: Source, storage: StorageManager, content_id: str) -> None:
        video = storage.get_video_path(content_id)
        transcript = storage.get_transcript(content_id)
        comments = storage.get_comments(content_id)
        with get_session() as s:
            repo = ContentRepo(s)
            item = repo.get(source.id, content_id)
            sig = SignalRepo(s).get_by_content(source.id, content_id)

        updates = {}
        if video:
            updates["media_status"] = STATUS_SUCCEEDED
            updates["media_error"] = ""
            updates["file_size"] = video.stat().st_size
        if transcript:
            updates["transcript_status"] = STATUS_SUCCEEDED
            updates["transcript_error"] = ""
        if comments is not None:
            updates["comments_status"] = STATUS_SUCCEEDED
            updates["comments_error"] = ""
        if sig:
            updates["signal_status"] = STATUS_SUCCEEDED
            updates["signal_error"] = ""
            if not sig.is_new or not sig.new_points:
                updates["profile_status"] = STATUS_SKIPPED
                updates["profile_error"] = ""
            elif item and item.profile_status == STATUS_PENDING:
                # 兼容历史数据：content_items 之前已有的 Signal，大概率已同步过档案；
                # 但绝不覆盖显式 failed，failed 会交给 profile repair 阶段重试。
                updates["profile_status"] = STATUS_SUCCEEDED
                updates["profile_error"] = ""
        if updates:
            self._update_content_stage(source.id, content_id, **updates)

    def _finish_source_refresh(
        self,
        source: Source,
        refresh_run_id: int,
        status: str,
        counts: dict,
        errors: list[dict],
    ) -> None:
        first_error = errors[0]["message"] if errors else ("canceled" if status == STATUS_CANCELED else None)
        with get_session() as s:
            SourceRepo(s).mark_checked(source.id, ok=status == STATUS_SUCCEEDED, error=first_error)
            RefreshRunRepo(s).finish(
                refresh_run_id,
                status=status,
                counts=counts,
                errors=errors,
            )

    @staticmethod
    def _update_content_stage(source_id: int, content_id: str, **kwargs) -> None:
        with get_session() as s:
            ContentRepo(s).update_stage(source_id, content_id, **kwargs)

    @staticmethod
    def _storage_content_ids(storage: StorageManager) -> set[str]:
        out = set()
        for md in storage.list_metadata():
            cid = md.get("content_id") or md.get("video_id")
            if cid:
                out.add(str(cid))
        return out

    @staticmethod
    def _empty_counts() -> dict:
        return {
            "discovered": 0,
            "deduped": 0,
            "new_contents": 0,
            "known_contents": 0,
            "downloaded": 0,
            "transcribed": 0,
            "comments": 0,
            "signaled": 0,
            "profile_updated": 0,
            "failed": 0,
        }

    @staticmethod
    def _merge_counts(target: dict, src: dict) -> None:
        for key, value in (src or {}).items():
            if isinstance(value, int):
                target[key] = int(target.get(key, 0)) + value

    @staticmethod
    def _check_cancelled(is_cancelled: Optional[Callable[[], bool]]) -> None:
        if is_cancelled and is_cancelled():
            from app.tasks.runner import CancelledError
            raise CancelledError("task cancelled")

    # ------ legacy helpers ------

    @staticmethod
    def _should_skip(source: Source) -> bool:
        config = config_service.effective_for_source(source.id)
        interval_hours = int(config.get("interval_hours", 48))
        if not source.last_check:
            return False
        try:
            last = datetime.fromisoformat(source.last_check)
        except Exception:
            return False
        return (datetime.now() - last).total_seconds() < interval_hours * 3600

    @staticmethod
    def _log(cb, msg: str) -> None:
        if cb:
            cb(msg)
        else:
            print(msg)
