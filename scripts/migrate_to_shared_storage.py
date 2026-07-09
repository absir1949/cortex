"""迁移历史文件到共享采集存储布局

将旧目录 data/{group_slug}/{source_dir}/ 下的文件，
copy 到新目录 data/{platform}/creators/{creator_id}/。

策略（见 SHARED_INGEST_DESIGN.md 7.2）：
  - copy 不 move，旧文件保留，回滚只需改代码读旧路径
  - 先写 manifest（旧路径→新路径映射），用于校验和回滚
  - copy 后校验文件数和大小
  - 校验通过后同步 GlobalContent 的采集状态

用法：
  python scripts/migrate_to_shared_storage.py          # 执行迁移
  python scripts/migrate_to_shared_storage.py --verify   # 只校验，不迁移
  python scripts/migrate_to_shared_storage.py --rollback # 按 manifest 回滚（删新文件）
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from app.db.engine import get_engine, get_session
from app.db.schema import ContentItem, GlobalContent, Source, Creator
from app.storage import paths
from app.storage.fs import StorageManager, GlobalStorage
from sqlmodel import Session, select


# 迁移状态常量（与 ingest_service 一致）
STATUS_SUCCEEDED = "succeeded"
STATUS_PENDING = "pending"
STATUS_SKIPPED = "skipped"


def discover_source_dirs(session: Session) -> list[tuple[Source, str, Path]]:
    """找出所有有旧目录文件的 source，返回 (source, platform, old_dir)。"""
    results: list[tuple[Source, str, Path]] = []
    for src in session.exec(select(Source)).all():
        old_dir = paths.source_dir(src.directory)
        if not old_dir.exists():
            continue
        # 检查目录里是否有实际内容文件
        has_files = any(old_dir.iterdir())
        if has_files:
            results.append((src, src.platform, old_dir))
    return results


def build_manifest(
    session: Session,
    sources: list[tuple[Source, str, Path]],
) -> list[dict]:
    """为每个旧文件计算新路径，返回 manifest 条目列表。"""
    entries: list[dict] = []

    for src, platform, old_dir in sources:
        creator_id = src.creator_id
        owner_key = paths.content_owner_key(creator_id)
        new_dir = paths.content_dir(platform, owner_key)

        for old_file in old_dir.iterdir():
            if old_file.is_dir() or old_file.name.startswith("."):
                continue
            new_file = new_dir / old_file.name
            entries.append({
                "source_id": src.id,
                "creator_id": creator_id,
                "platform": platform,
                "old_path": str(old_file),
                "new_path": str(new_file),
                "filename": old_file.name,
                "size": old_file.stat().st_size,
            })

    return entries


def copy_files(manifest: list[dict], dry_run: bool = False) -> tuple[int, int]:
    """按 manifest copy 文件。返回 (copied, skipped)。"""
    copied = 0
    skipped = 0
    for entry in manifest:
        old_path = Path(entry["old_path"])
        new_path = Path(entry["new_path"])

        if new_path.exists() and new_path.stat().st_size == entry["size"]:
            skipped += 1
            continue

        if dry_run:
            print(f"  [dry-run] {old_path.name} -> {new_path}")
            copied += 1
            continue

        new_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(old_path), str(new_path))
        copied += 1

    return copied, skipped


def verify_manifest(manifest: list[dict]) -> tuple[int, int, int]:
    """校验新文件是否都存在且大小一致。返回 (ok, missing, size_mismatch)。"""
    ok = 0
    missing = 0
    size_mismatch = 0
    for entry in manifest:
        new_path = Path(entry["new_path"])
        if not new_path.exists():
            missing += 1
            continue
        if new_path.stat().st_size != entry["size"]:
            size_mismatch += 1
            continue
        ok += 1
    return ok, missing, size_mismatch


def sync_global_content_state(session: Session, manifest: list[dict]) -> int:
    """根据新目录的实际文件，同步 GlobalContent 的采集状态。

    返回更新的条目数。
    """
    updated = 0

    # 按 (platform, creator_id) 分组，为每组建一个 GlobalStorage
    grouped: dict[tuple[str, Optional[int]], list[dict]] = {}
    for entry in manifest:
        key = (entry["platform"], entry["creator_id"])
        grouped.setdefault(key, []).append(entry)

    for (platform, creator_id), entries in grouped.items():
        storage = GlobalStorage(platform, creator_id)
        # 从 manifest 提取该组的 content_ids
        content_ids: set[str] = set()
        for entry in entries:
            # 文件名格式：YYYY-MM-DD_{content_id}.{ext} 或 {content_id}.{ext}
            name = entry["filename"]
            # 去掉日期前缀和扩展名
            parts = name.rsplit(".", 1)[0]  # 去扩展名
            if "_" in parts:
                cid = parts.rsplit("_", 1)[-1]  # 取 content_id 部分
            else:
                cid = parts
            content_ids.add(cid)

        # 对每个 content_id 查 GlobalContent 并同步状态
        for cid in content_ids:
            gc = session.exec(
                select(GlobalContent).where(
                    GlobalContent.platform == platform,
                    GlobalContent.content_id == cid,
                )
            ).first()
            if not gc:
                continue

            changed = False
            transcript = storage.get_transcript(cid)
            if transcript and gc.transcript_status != STATUS_SUCCEEDED:
                gc.transcript_status = STATUS_SUCCEEDED
                gc.transcript_error = None
                changed = True

            comments = storage.get_comments(cid)
            if comments is not None and gc.comments_status != STATUS_SUCCEEDED:
                gc.comments_status = STATUS_SUCCEEDED
                gc.comments_error = None
                changed = True

            video = storage.get_video_path(cid)
            if video:
                gc.media_status = STATUS_SUCCEEDED
                gc.media_error = None
                gc.file_size = video.stat().st_size
                changed = True

            if changed:
                gc.updated_at = datetime.now().isoformat()
                session.add(gc)
                updated += 1

    session.commit()
    return updated


def run_migration(verify_only: bool = False) -> None:
    """主迁移流程。"""
    print("=" * 60)
    print("共享存储文件迁移")
    print(f"时间: {datetime.now().isoformat()}")
    print(f"模式: {'只校验' if verify_only else '执行迁移'}")
    print("=" * 60)

    with get_session() as session:
        sources = discover_source_dirs(session)
        print(f"\n发现 {len(sources)} 个有文件的旧 source 目录:")
        for src, platform, old_dir in sources:
            file_count = sum(1 for f in old_dir.iterdir() if f.is_file() and not f.name.startswith("."))
            print(f"  source {src.id}: {platform} creator={src.creator_id} ({file_count} files)")
            print(f"    旧: {old_dir}")
            print(f"    新: {paths.content_dir(platform, paths.content_owner_key(src.creator_id))}")

        manifest = build_manifest(session, sources)
        print(f"\nManifest: {len(manifest)} 个文件待迁移")

        if verify_only:
            ok, missing, mismatch = verify_manifest(manifest)
            print(f"\n校验结果: OK={ok}, 缺失={missing}, 大小不一致={mismatch}")
            if missing == 0 and mismatch == 0:
                print("✓ 全部文件已到位")
            else:
                print("✗ 有文件缺失或不一致，需要重新迁移")
            return

        # 写 manifest 文件
        manifest_dir = Path("state/migration_manifests")
        manifest_dir.mkdir(parents=True, exist_ok=True)
        manifest_file = manifest_dir / f"shared_storage_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        manifest_file.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Manifest 已保存: {manifest_file}")

        # 执行 copy
        print("\n开始 copy 文件...")
        copied, skipped = copy_files(manifest)
        print(f"Copy 完成: 新复制 {copied}, 已存在跳过 {skipped}")

        # 校验
        ok, missing, mismatch = verify_manifest(manifest)
        print(f"\n校验结果: OK={ok}, 缺失={missing}, 大小不一致={mismatch}")
        if missing > 0 or mismatch > 0:
            print("✗ 校验失败！请检查上面的缺失/不一致文件")
            print("  旧文件未被删除，可安全重试。")
            return

        # 同步 GlobalContent 状态
        print("\n同步 GlobalContent 采集状态...")
        updated = sync_global_content_state(session, manifest)
        print(f"✓ 更新了 {updated} 条 GlobalContent 状态")

        print("\n" + "=" * 60)
        print("✓ 迁移完成！")
        print(f"  - 旧目录保留在原位（不删除）")
        print(f"  - 回滚只需删 {paths.content_dir('', '').parent} 下的新目录")
        print(f"  - Manifest: {manifest_file}")
        print("=" * 60)


def run_rollback(manifest_file: str) -> None:
    """按 manifest 回滚（删除新文件）。"""
    manifest_path = Path(manifest_file)
    if not manifest_path.exists():
        print(f"✗ manifest 文件不存在: {manifest_file}")
        sys.exit(1)

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    print(f"回滚: 从 manifest {manifest_file} 删除 {len(manifest)} 个新文件")

    deleted = 0
    skipped = 0
    new_dirs_seen: set[str] = set()
    for entry in manifest:
        new_path = Path(entry["new_path"])
        if new_path.exists():
            new_path.unlink()
            deleted += 1
            new_dirs_seen.add(str(new_path.parent))
        else:
            skipped += 1

    # 清理空目录
    for d in sorted(new_dirs_seen, reverse=True):
        dir_path = Path(d)
        if dir_path.exists() and not any(dir_path.iterdir()):
            dir_path.rmdir()

    print(f"✓ 删除 {deleted} 个文件，跳过 {skipped} 个不存在的")
    print("旧目录文件未受影响，代码会自动回退到旧路径读取。")


def main():
    parser = argparse.ArgumentParser(description="迁移历史文件到共享采集存储")
    parser.add_argument("--verify", action="store_true", help="只校验不迁移")
    parser.add_argument("--rollback", type=str, help="按 manifest 文件回滚（删新文件）")
    args = parser.parse_args()

    if args.rollback:
        run_rollback(args.rollback)
    elif args.verify:
        run_migration(verify_only=True)
    else:
        run_migration(verify_only=False)


if __name__ == "__main__":
    main()
