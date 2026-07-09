"""将文件系统里的孤儿文件导入 GlobalContent/SourceContent/GroupContent

背景：部分历史内容有文件（转录/元数据）但从未进过 content_items 表，
导致 GlobalContent 为空。此脚本扫描新目录下的 metadata json，为缺失的
内容补建 GlobalContent + SourceContent + GroupContent 记录。

用法：
  PYTHONPATH=. python scripts/import_orphan_files.py           # 执行导入
  PYTHONPATH=. python scripts/import_orphan_files.py --dry-run # 只看不导
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from app.db.engine import get_engine, get_session
from app.db.schema import (
    Creator, GlobalContent, GroupContent, KnowledgeGroup,
    Source, SourceContent, IngestTarget,
)
from app.db.repos import (
    GlobalContentRepo, GroupContentRepo, IngestTargetRepo,
    SourceContentRepo, SourceRepo,
)
from app.storage.fs import GlobalStorage, StorageManager
from app.models.content import Content, ContentType
from sqlmodel import Session, select


STATUS_SUCCEEDED = "succeeded"
STATUS_PENDING = "pending"
STATUS_SKIPPED = "skipped"


def parse_content_id(filename: str) -> str:
    """从文件名提取 content_id：YYYY-MM-DD_{content_id}.{ext} 或 {content_id}.{ext}"""
    name = filename.rsplit(".", 1)[0]  # 去扩展名
    if "_" in name:
        return name.rsplit("_", 1)[-1]
    return name


def read_metadata(storage: GlobalStorage, content_id: str) -> dict:
    """读取 metadata json（文件名格式 YYYY-MM-DD_{content_id}.json）"""
    for f in storage.base.glob(f"*_{content_id}.json"):
        if f.name.endswith(".comments.json"):
            continue
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
    # 无日期前缀
    for f in storage.base.glob(f"{content_id}.json"):
        if f.name.endswith(".comments.json"):
            continue
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
    return {}


def import_orphans(dry_run: bool = False) -> None:
    print("=" * 60)
    print("孤儿文件导入 GlobalContent")
    print(f"模式: {'只看' if dry_run else '执行'}")
    print("=" * 60)

    total_created = 0
    total_skipped = 0

    with get_session() as session:
        # 所有 source
        sources = list(session.exec(select(Source)).all())
        # source 按 (platform, creator_id) 分组
        by_creator: dict[tuple[str, Optional[int]], list[Source]] = {}
        for src in sources:
            key = (src.platform, src.creator_id)
            by_creator.setdefault(key, []).append(src)

        for (platform, creator_id), srcs in by_creator.items():
            if not creator_id:
                continue

            storage = GlobalStorage(platform, creator_id)
            metadata_files = [f for f in storage.base.glob("*.json")
                              if not f.name.endswith(".comments.json")]
            if not metadata_files:
                continue

            # 该 creator 已有的 GlobalContent content_ids
            existing_ids = set(session.exec(
                select(GlobalContent.content_id).where(
                    GlobalContent.platform == platform,
                    GlobalContent.creator_id == creator_id,
                )
            ).all())

            creator = session.get(Creator, creator_id)
            creator_name = creator.name if creator else "unknown"
            orphan_count = 0

            for md_file in metadata_files:
                content_id = parse_content_id(md_file.name)
                if not content_id or content_id in existing_ids:
                    total_skipped += 1
                    continue

                md = read_metadata(storage, content_id)
                orphan_count += 1

                if dry_run:
                    continue

                # 建 GlobalContent
                now = datetime.now().isoformat()
                has_transcript = storage.get_transcript(content_id) is not None
                has_comments = storage.get_comments(content_id) is not None
                has_video = storage.get_video_path(content_id) is not None

                gc = GlobalContent(
                    platform=platform,
                    content_id=content_id,
                    creator_id=creator_id,
                    content_type="video",
                    title=md.get("title", ""),
                    author_id=md.get("author_id", ""),
                    author_name=md.get("author", creator_name),
                    url=md.get("url", ""),
                    create_time=md.get("create_time", ""),
                    first_seen_at=md.get("downloaded_at", now),
                    last_seen_at=now,
                    updated_at=now,
                    media_status=STATUS_SUCCEEDED if has_video else STATUS_SKIPPED,
                    transcript_status=STATUS_SUCCEEDED if has_transcript else STATUS_PENDING,
                    comments_status=STATUS_SUCCEEDED if has_comments else STATUS_SKIPPED,
                    signal_status=STATUS_PENDING,
                    profile_status=STATUS_PENDING,
                    statistics=md.get("statistics", {}),
                    file_size=md.get("file_size", 0),
                )
                session.add(gc)
                session.flush()
                gc_id = gc.id

                # 为每个订阅该 creator 的 source 建 SourceContent + GroupContent
                # 找该 creator 对应的 IngestTarget
                for src in srcs:
                    target = IngestTargetRepo(session).ensure_for_source(src)
                    SourceContentRepo(session).upsert(
                        source_id=src.id,
                        global_content_id=gc_id,
                        ingest_target_id=target.id,
                        matched_query="" if src.type == "creator" else src.identifier,
                    )
                    GroupContentRepo(session).upsert(
                        group_id=src.group_id,
                        global_content_id=gc_id,
                    )

                existing_ids.add(content_id)
                total_created += 1

            if orphan_count > 0:
                print(f"  creator {creator_id} ({creator_name}, {platform}): "
                      f"{orphan_count} 个孤儿{'（dry-run）' if dry_run else ' 已导入'}, "
                      f"{len(existing_ids)} 已有")

            if not dry_run:
                session.commit()

    print(f"\n总计: 新建 {total_created} 条 GlobalContent, 跳过 {total_skipped} 条已有")
    if not dry_run:
        print("✓ 孤儿文件导入完成")


def main():
    parser = argparse.ArgumentParser(description="导入孤儿文件到 GlobalContent")
    parser.add_argument("--dry-run", action="store_true", help="只看不导")
    args = parser.parse_args()
    import_orphans(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
