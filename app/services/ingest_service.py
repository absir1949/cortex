"""定时订阅采集 - 按组遍历所有 sources，执行采集→下载→转录→评论→保存"""
from __future__ import annotations
from datetime import datetime
from typing import Callable, Optional

from app.db.engine import get_session
from app.db.repos import GroupRepo, SourceRepo
from app.db.schema import Source, KnowledgeGroup
from app.platforms import get_adapter, Capability
from app.services import config_service
from app.storage.fs import StorageManager


class IngestService:
    """采集服务 - 对单个源或整个组运行"""

    def run_group(
        self,
        group_id: int,
        *,
        force: bool = False,
        progress_cb: Optional[Callable[[dict], None]] = None,
        log_cb: Optional[Callable[[str], None]] = None,
        is_cancelled: Optional[Callable[[], bool]] = None,
    ) -> dict:
        """跑一个组下所有启用的 source。返回统计"""
        with get_session() as s:
            group = GroupRepo(s).get(group_id)
            sources = SourceRepo(s).list_by_group(group_id, enabled_only=True)
        if not group:
            raise ValueError(f"group {group_id} not found")

        summary = {"group_id": group_id, "sources_run": 0, "new_contents_total": 0, "details": []}
        for i, source in enumerate(sources, 1):
            if is_cancelled and is_cancelled():
                self._log(log_cb, "任务被取消")
                break
            if not force and self._should_skip(source):
                self._log(log_cb, f"[skip] {source.display_name}: 距上次检查不足 interval_hours")
                continue
            if progress_cb:
                progress_cb({"stage": "ingesting", "done": i - 1, "total": len(sources), "current": source.display_name})
            self._log(log_cb, f"[{i}/{len(sources)}] 处理源: {source.display_name}")
            try:
                n = self.run_source(
                    source,
                    log_cb=log_cb,
                    is_cancelled=is_cancelled,
                )
                summary["sources_run"] += 1
                summary["new_contents_total"] += n
                summary["details"].append({"source": source.display_name, "new": n})
            except Exception as e:
                self._log(log_cb, f"[error] {source.display_name}: {e}")
                summary["details"].append({"source": source.display_name, "error": str(e)})

        if progress_cb:
            progress_cb({"stage": "done", "total": len(sources), "done": len(sources)})
        return summary

    def run_source(
        self,
        source: Source,
        *,
        log_cb: Optional[Callable[[str], None]] = None,
        is_cancelled: Optional[Callable[[], bool]] = None,
    ) -> int:
        """跑单个源，返回本次新增内容数"""
        adapter = get_adapter(source.platform)
        if not adapter:
            raise RuntimeError(f"unsupported platform: {source.platform}")

        config = config_service.effective_for_source(source.id)
        storage = StorageManager(source.directory)

        # 1. 获取内容列表（博主/关键词）
        if source.type == "creator":
            if not adapter.has(Capability.FETCH_CREATOR):
                raise RuntimeError(f"{source.platform} 不支持博主采集")
            contents = adapter.fetch_creator_content(
                source.identifier,
                limit=config.get("content_limit", 50),
                days=config.get("days"),
            )
        elif source.type == "keyword":
            if not adapter.has(Capability.SEARCH):
                raise RuntimeError(f"{source.platform} 不支持关键词搜索")
            contents = adapter.search(
                source.identifier,
                limit=config.get("content_limit", 50),
                days=config.get("days"),
            )
        else:
            raise RuntimeError(f"未知源类型: {source.type}")

        self._log(log_cb, f"  拿到 {len(contents)} 条候选")

        # 2. 过滤已存在的
        new_contents = [c for c in contents if not storage.exists(c.content_id)]
        self._log(log_cb, f"  新内容: {len(new_contents)} 条（{len(contents) - len(new_contents)} 条已存在）")

        # 3. 每条：下载 → 转录 → 抓评论 → 保存
        new_count = 0
        for c in new_contents:
            if is_cancelled and is_cancelled():
                break
            try:
                # 下载
                if adapter.has(Capability.DOWNLOAD_MEDIA) and c.media_urls:
                    tmp_path = f"/tmp/{c.content_id}.mp4"
                    if not adapter.download_media(c, tmp_path):
                        self._log(log_cb, f"  [skip] {c.title[:30]} 下载失败")
                        continue
                    file_size = __import__("pathlib").Path(tmp_path).stat().st_size
                    storage.save_video(c.content_id, tmp_path, c.create_time)
                    final_path = storage.base / f"{(c.create_time or '').split('T')[0]}_{c.content_id}.mp4"
                    __import__("pathlib").Path(tmp_path).unlink(missing_ok=True)
                else:
                    file_size = 0
                    final_path = None

                # 转录
                transcript = None
                if config.get("transcribe_enabled", True) and c.should_transcribe() and final_path:
                    try:
                        from app.transcribe import transcribe_video
                        transcript = transcribe_video(str(final_path))
                        storage.save_transcript(c.content_id, transcript, c.create_time)
                    except Exception as e:
                        self._log(log_cb, f"  [warn] 转录失败 {c.title[:30]}: {e}")

                # 评论
                if adapter.has(Capability.FETCH_COMMENTS):
                    try:
                        comments = adapter.fetch_comments(
                            c.content_id,
                            top_n=config.get("comment_top_n", 20),
                            fetch_replies=True,
                        )
                        storage.save_comments(
                            c.content_id,
                            [cm.model_dump() for cm in comments],
                            c.create_time,
                        )
                    except Exception as e:
                        self._log(log_cb, f"  [warn] 评论抓取失败: {e}")

                # 元数据
                storage.save_metadata(c.content_id, {
                    "content_id": c.content_id,
                    "title": c.title,
                    "author": c.author_name,
                    "author_id": c.author_id,
                    "create_time": c.create_time,
                    "platform": c.platform,
                    "url": c.url,
                    "statistics": c.statistics,
                    "downloaded_at": datetime.now().isoformat(),
                    "file_size": file_size,
                    "transcribed": transcript is not None,
                })
                new_count += 1
                self._log(log_cb, f"  ✓ {c.title[:40]}{' [+' + str(len(transcript)) + '字]' if transcript else ''}")
            except Exception as e:
                self._log(log_cb, f"  ✗ {c.title[:30]}: {e}")

        # 4. 标记已检查
        with get_session() as s:
            SourceRepo(s).mark_checked(source.id, ok=True)
        return new_count

    # ------ helpers ------

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
