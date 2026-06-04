"""数据迁移 v2 - 把 creators.json + data/MS4wLjAB_*/ 迁到新规范

新规范：
  data/{group_slug}/{source_slug}/*       （如 data/wechat-shop/creator-jiubaimi/*）
  knowledge/{group_slug}/*.md             （如 knowledge/wechat-shop/knowledge_*.md）

流程：
  1. 备份（rsync 全量到 backup/）
  2. 读 creators.json → 创建"微信小店"组 + 7 个 sources
  3. 物理 move 数据目录到新位置
  4. 物理 move knowledge/ 下 md/json 到 knowledge/wechat-shop/
  5. 扫描每个源的 .analyzed.json → 导入 DB analyzed_content 表
  6. 扫描 knowledge/wechat-shop/*.md → 导入 DB reports 表
  7. 写 schema_version v2

幂等：重复执行不会重复建表/导入
回滚：migrations/002_rollback.py
"""
from __future__ import annotations
import argparse
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

# 让脚本能直接运行
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlmodel import Session, select

from app.db.engine import get_engine
from app.db.migrations import run_migrations
from app.db.schema import (
    AnalyzedContent,
    KnowledgeGroup,
    Report,
    SchemaVersion,
    Source,
)
from app.models.group import ReportKind, SourceType
from app.settings import settings
from migrations.slugs import DISPLAY_NAME_TO_SLUG


MIGRATION_VERSION = 2
GROUP_NAME = "微信小店"
GROUP_SLUG = "wechat-shop"


def log(msg: str):
    print(f"[migrate-v2] {msg}")


def _plan(creators: list[dict]) -> list[dict]:
    """规划每个源的新目录名"""
    plans = []
    for c in creators:
        name = c["name"]
        slug_part = DISPLAY_NAME_TO_SLUG.get(name) or _fallback_slug(name)
        new_dir = f"{GROUP_SLUG}/{SourceType.CREATOR.value}-{slug_part}"
        plans.append({
            "name": name,
            "platform": c["platform"],
            "id": c["id"],
            "interval_hours": c.get("interval_hours"),
            "last_check": c.get("last_check"),
            "old_directory": c["directory"],
            "new_directory": new_dir,
        })
    return plans


def _fallback_slug(name: str) -> str:
    """中文 fallback：保留可读（仅剔除非法字符）"""
    import re
    return re.sub(r"[\\/:*?\"<>|\s]+", "-", name).strip("-") or "unnamed"


def dry_run(creators: list[dict]) -> None:
    print("=" * 70)
    print("Migration Plan (DRY RUN - 不会修改任何文件)")
    print("=" * 70)
    print(f"\n会创建知识组：'{GROUP_NAME}' (slug={GROUP_SLUG})\n")

    plans = _plan(creators)
    print(f"会创建 {len(plans)} 个源：")
    for p in plans:
        old = settings.data_dir / p["old_directory"]
        new = settings.data_dir / p["new_directory"]
        has_old = "exists" if old.exists() else "missing"
        file_count = len(list(old.glob("*"))) if old.exists() else 0
        print(f"  · {p['name']}")
        print(f"    old: data/{p['old_directory']}  [{has_old}, {file_count} files]")
        print(f"    new: data/{p['new_directory']}")

    # knowledge
    print(f"\n会移动 knowledge/*.md 到 knowledge/{GROUP_SLUG}/")
    md_files = list(settings.knowledge_dir.glob("knowledge_*.md"))
    print(f"  共 {len(md_files)} 个 md 文件")

    print("\n完整执行请去掉 --dry-run 参数。")


def backup(plans: list[dict]) -> Path:
    """全量备份要动的目录"""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_root = settings.backup_dir / f"migration_v2_{ts}"
    backup_root.mkdir(parents=True, exist_ok=True)

    # 备份 creators.json
    creators_json = settings.base_dir / "creators.json"
    if creators_json.exists():
        shutil.copy(creators_json, backup_root / "creators.json")

    # 备份每个旧目录
    for p in plans:
        old_path = settings.data_dir / p["old_directory"]
        if old_path.exists():
            dest = backup_root / "data" / p["old_directory"]
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(old_path, dest)

    # 备份 knowledge 根目录下的 md/json
    for f in settings.knowledge_dir.glob("knowledge_*"):
        if f.is_file():
            dest = backup_root / "knowledge" / f.name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(f, dest)

    # 备份 cortex.db（如果存在）
    if settings.db_path.exists():
        shutil.copy(settings.db_path, backup_root / "cortex.db")

    log(f"✓ 备份完成：{backup_root}")
    (backup_root / "_manifest.json").write_text(
        json.dumps({"version": MIGRATION_VERSION, "plans": plans, "created": ts}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return backup_root


def execute(creators: list[dict], skip_backup: bool = False) -> None:
    """真正执行迁移"""
    settings.ensure_dirs()

    # 先跑 v1 确保 schema 存在
    run_migrations(verbose=False)

    # 检查是否已经跑过 v2
    with Session(get_engine()) as s:
        already = s.exec(select(SchemaVersion).where(SchemaVersion.version == MIGRATION_VERSION)).first()
        if already:
            log(f"v{MIGRATION_VERSION} 已经应用过（applied_at={already.applied_at}），跳过。如需重跑请先 rollback。")
            return

    plans = _plan(creators)

    # 1. 备份
    if not skip_backup:
        backup(plans)

    # 2. 建 KnowledgeGroup
    with Session(get_engine()) as s:
        existing_group = s.exec(select(KnowledgeGroup).where(KnowledgeGroup.slug == GROUP_SLUG)).first()
        if existing_group:
            group = existing_group
            log(f"知识组 '{GROUP_NAME}' 已存在 (id={group.id})")
        else:
            group = KnowledgeGroup(
                name=GROUP_NAME,
                slug=GROUP_SLUG,
                description="从 creators.json 自动迁移（v2）",
                defaults={"interval_hours": 48, "content_limit": 50, "days": 7, "comment_top_n": 20},
            )
            s.add(group)
            s.commit()
            s.refresh(group)
            log(f"✓ 创建知识组 '{GROUP_NAME}' (id={group.id})")

    # 3. 每个源：迁目录 + 建 Source 记录
    moved: list[dict] = []
    for p in plans:
        old_path = settings.data_dir / p["old_directory"]
        new_path = settings.data_dir / p["new_directory"]

        # 目录移动（幂等）
        if old_path.exists() and not new_path.exists():
            new_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(old_path), str(new_path))
            log(f"✓ 移动目录: {p['old_directory']} → {p['new_directory']}")
            moved.append(p)
        elif new_path.exists():
            log(f"  新目录已存在，跳过: {p['new_directory']}")
        elif not old_path.exists():
            log(f"  源目录不存在，只创建空目录: {p['new_directory']}")
            new_path.mkdir(parents=True, exist_ok=True)

        # DB 记录
        with Session(get_engine()) as s:
            existing_src = s.exec(
                select(Source).where(
                    Source.group_id == group.id,
                    Source.platform == p["platform"],
                    Source.identifier == p["id"],
                )
            ).first()
            if existing_src:
                log(f"  源已存在: {p['name']}")
                continue
            src = Source(
                group_id=group.id,
                type=SourceType.CREATOR.value,
                platform=p["platform"],
                identifier=p["id"],
                display_name=p["name"],
                enabled=True,
                interval_hours=p.get("interval_hours"),
                directory=p["new_directory"],
                last_check=p.get("last_check"),
            )
            s.add(src)
            s.commit()
            s.refresh(src)
            log(f"  ✓ 创建源记录: {p['name']} (source_id={src.id})")

    # 4. 移动 knowledge md/json 到组目录
    group_knowledge_dir = settings.knowledge_dir / GROUP_SLUG
    group_knowledge_dir.mkdir(parents=True, exist_ok=True)

    for f in list(settings.knowledge_dir.glob("knowledge_*")):
        if not f.is_file():
            continue
        target = group_knowledge_dir / f.name
        if target.exists():
            continue
        shutil.move(str(f), str(target))
        log(f"✓ 移动报告: {f.name}")

    # 5. 导入 .analyzed.json → DB
    with Session(get_engine()) as s:
        group_id = group.id
        sources = s.exec(select(Source).where(Source.group_id == group_id)).all()
        for src in sources:
            analyzed_file = settings.data_dir / src.directory / ".analyzed.json"
            if not analyzed_file.exists():
                continue
            try:
                ids = json.loads(analyzed_file.read_text(encoding="utf-8")).get("video_ids", [])
            except Exception:
                continue
            existing = set(s.exec(
                select(AnalyzedContent.content_id).where(AnalyzedContent.source_id == src.id)
            ).all())
            added = 0
            for cid in ids:
                if cid in existing:
                    continue
                s.add(AnalyzedContent(source_id=src.id, content_id=cid))
                added += 1
            if added:
                s.commit()
                log(f"✓ 导入 {added} 条 analyzed_content: {src.display_name}")

    # 6. 导入 knowledge 报告元数据
    with Session(get_engine()) as s:
        existing_paths = {r.content_md_path for r in s.exec(select(Report)).all()}
        for md in sorted(group_knowledge_dir.glob("knowledge_*.md")):
            if str(md) in existing_paths:
                continue
            stem = md.stem  # knowledge_20260417_091945
            ts_part = stem.replace("knowledge_", "")
            try:
                created_at = datetime.strptime(ts_part, "%Y%m%d_%H%M%S").isoformat()
            except Exception:
                created_at = datetime.now().isoformat()
            json_path = md.with_suffix(".json")
            report = Report(
                group_id=group_id,
                kind=ReportKind.SCHEDULED.value,
                title=f"{GROUP_NAME} · {ts_part}",
                summary="",
                content_md_path=str(md),
                content_json_path=str(json_path) if json_path.exists() else None,
                sources_used=[],
                created_at=created_at,
            )
            s.add(report)
        s.commit()
        log("✓ 报告元数据已导入")

    # 7. 记录迁移版本
    with Session(get_engine()) as s:
        s.add(SchemaVersion(
            version=MIGRATION_VERSION,
            note="002_migrate_data: creators.json → groups + sources + file move",
        ))
        s.commit()

    log(f"✓ 迁移 v{MIGRATION_VERSION} 完成")


def load_creators() -> list[dict]:
    path = settings.base_dir / "creators.json"
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8")).get("creators", [])


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="只打印计划，不修改任何文件")
    parser.add_argument("--skip-backup", action="store_true", help="跳过备份（危险）")
    args = parser.parse_args()

    creators = load_creators()
    if not creators:
        log("没有找到 creators.json 或为空")
        sys.exit(0)

    if args.dry_run:
        dry_run(creators)
    else:
        execute(creators, skip_backup=args.skip_backup)
