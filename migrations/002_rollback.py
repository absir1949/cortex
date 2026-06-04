"""数据迁移 v2 回滚

策略：从 backup/migration_v2_* 里最新的备份恢复。
操作：
  1. 找最新备份目录
  2. 恢复 creators.json
  3. 把新目录 data/wechat-shop/* move 回原位（根据 manifest）
  4. 恢复 knowledge/ 根目录（把 knowledge/wechat-shop/*.md 搬回根）
  5. 恢复 cortex.db
"""
from __future__ import annotations
import argparse
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.settings import settings


def log(msg: str):
    print(f"[rollback-v2] {msg}")


def find_latest_backup() -> Path | None:
    if not settings.backup_dir.exists():
        return None
    candidates = sorted(settings.backup_dir.glob("migration_v2_*"), reverse=True)
    return candidates[0] if candidates else None


def rollback(backup_path: Path) -> None:
    manifest_path = backup_path / "_manifest.json"
    if not manifest_path.exists():
        log(f"❌ 备份无效（缺少 _manifest.json）: {backup_path}")
        sys.exit(1)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    plans = manifest.get("plans", [])

    # 1. 恢复 creators.json
    src = backup_path / "creators.json"
    if src.exists():
        shutil.copy(src, settings.base_dir / "creators.json")
        log("✓ 恢复 creators.json")

    # 2. 恢复 data 目录
    for p in plans:
        old_dir = settings.data_dir / p["old_directory"]
        new_dir = settings.data_dir / p["new_directory"]
        backup_data_dir = backup_path / "data" / p["old_directory"]

        # 删新目录（如果存在且有内容）
        if new_dir.exists():
            shutil.rmtree(new_dir)
            log(f"  删除新目录: {p['new_directory']}")

        # 从备份恢复旧目录
        if backup_data_dir.exists():
            old_dir.parent.mkdir(parents=True, exist_ok=True)
            if old_dir.exists():
                shutil.rmtree(old_dir)
            shutil.copytree(backup_data_dir, old_dir)
            log(f"✓ 恢复 data/{p['old_directory']}")

    # 清理空的 wechat-shop 目录
    for slug_dir in settings.data_dir.glob("*"):
        if slug_dir.is_dir() and not any(slug_dir.iterdir()):
            slug_dir.rmdir()

    # 3. knowledge 目录：把 knowledge/wechat-shop/*.md 搬回根，删空目录
    for slug_dir in settings.knowledge_dir.iterdir():
        if not slug_dir.is_dir():
            continue
        for f in list(slug_dir.glob("knowledge_*")):
            target = settings.knowledge_dir / f.name
            if not target.exists():
                shutil.move(str(f), str(target))
                log(f"  恢复报告: {f.name}")
        if slug_dir.exists() and not any(slug_dir.iterdir()):
            slug_dir.rmdir()

    # 4. 恢复 cortex.db
    backup_db = backup_path / "cortex.db"
    if backup_db.exists():
        shutil.copy(backup_db, settings.db_path)
        log("✓ 恢复 cortex.db")
    elif settings.db_path.exists():
        # 没有备份 DB（首次迁移前 DB 就没建），干脆删掉
        settings.db_path.unlink()
        log("✓ 删除 cortex.db（首次迁移前本就不存在）")

    log(f"✓ 回滚完成（从 {backup_path.name}）")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--backup", type=str, help="指定备份目录（默认取最新）")
    args = parser.parse_args()

    if args.backup:
        backup_path = Path(args.backup)
    else:
        backup_path = find_latest_backup()
        if not backup_path:
            log("❌ 没找到 backup/migration_v2_* 目录")
            sys.exit(1)
        log(f"使用最新备份: {backup_path.name}")

    rollback(backup_path)
