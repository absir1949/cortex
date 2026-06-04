"""CLI - 薄壳，直接调 Service 层

用法：python -m app.cli <command> [args]
"""
from __future__ import annotations
import argparse
import sys
import time
from pathlib import Path

from rich.console import Console
from rich.table import Table


console = Console()


def cmd_migrate(args):
    """运行数据迁移"""
    from migrations import __init__ as _  # noqa
    import subprocess
    script = Path(__file__).resolve().parent.parent.parent / "migrations" / "002_migrate_data.py"
    cmd = [sys.executable, str(script)]
    if args.dry_run:
        cmd.append("--dry-run")
    if args.skip_backup:
        cmd.append("--skip-backup")
    subprocess.run(cmd, check=True)


def cmd_rollback(args):
    """回滚数据迁移"""
    import subprocess
    script = Path(__file__).resolve().parent.parent.parent / "migrations" / "002_rollback.py"
    cmd = [sys.executable, str(script)]
    if args.backup:
        cmd.extend(["--backup", args.backup])
    subprocess.run(cmd, check=True)


def cmd_groups(args):
    """列出知识组"""
    from app.services.group_service import GroupService
    from app.db.engine import get_session
    from app.db.repos import GroupRepo

    svc = GroupService()
    groups = svc.list()
    if not groups:
        console.print("[yellow]没有知识组[/yellow]")
        return

    t = Table(title="知识组")
    t.add_column("ID", style="cyan")
    t.add_column("名称", style="green")
    t.add_column("slug")
    t.add_column("启用")
    t.add_column("源数", style="yellow")
    with get_session() as s:
        repo = GroupRepo(s)
        for g in groups:
            t.add_row(
                str(g.id), g.name, g.slug,
                "✓" if g.enabled else "✗",
                str(repo.source_count(g.id)),
            )
    console.print(t)


def cmd_sources(args):
    """列出组下所有源"""
    from app.services.group_service import GroupService
    from app.services.source_service import SourceService

    g = GroupService().get_by_slug(args.slug)
    if not g:
        console.print(f"[red]group not found: {args.slug}[/red]")
        sys.exit(1)

    sources = SourceService().list_by_group(g.id)
    t = Table(title=f"{g.name} 的订阅源")
    t.add_column("ID"); t.add_column("类型"); t.add_column("平台"); t.add_column("名称")
    t.add_column("启用"); t.add_column("最近检查")
    for s in sources:
        t.add_row(
            str(s.id), s.type, s.platform, s.display_name,
            "✓" if s.enabled else "✗",
            (s.last_check or "")[:19],
        )
    console.print(t)


def cmd_run(args):
    """跑一次组采集 + 分析"""
    from app.services.group_service import GroupService
    from app.services.ingest_service import IngestService
    from app.services.knowledge_service import KnowledgeService

    g = GroupService().get_by_slug(args.slug)
    if not g:
        console.print(f"[red]group not found: {args.slug}[/red]")
        sys.exit(1)

    console.print(f"[cyan]开始采集组: {g.name}[/cyan]")
    summary = IngestService().run_group(g.id, force=args.force)
    console.print(f"[green]✓ 采集完成: {summary}[/green]")

    if not args.no_analyze:
        console.print("[cyan]开始知识提炼...[/cyan]")
        result = KnowledgeService().analyze_group(g.id)
        if result and result.get("report_id"):
            console.print(f"[green]✓ 生成报告: {result['report_path']}[/green]")


def cmd_search(args):
    """直接搜抖音（不走任务，调试用）"""
    from app.platforms import get_adapter
    adapter = get_adapter(args.platform)
    if not adapter:
        console.print(f"[red]未知平台: {args.platform}[/red]")
        sys.exit(1)
    results = adapter.search(args.query, limit=args.limit, days=args.days)
    t = Table(title=f"{args.platform} 搜索: {args.query}")
    t.add_column("content_id"); t.add_column("作者"); t.add_column("标题")
    t.add_column("发布时间"); t.add_column("点赞")
    for c in results:
        t.add_row(
            c.content_id, c.author_name, c.title[:40],
            (c.create_time or "")[:10],
            str(c.statistics.get("digg_count", 0)),
        )
    console.print(t)


def cmd_research(args):
    """按需研究（阻塞版，调试用）"""
    from app.services.group_service import GroupService
    from app.services.research_service import ResearchService

    g = GroupService().get_by_slug(args.slug) if args.slug else None
    result = ResearchService().run(
        args.question,
        group_id=g.id if g else None,
        days=args.days,
        search_limit=args.limit,
    )
    console.print(f"[green]✓ 报告生成: {result['report_path']}[/green]")
    console.print(f"证据数: {result['evidence_count']}")
    console.print(f"\n[bold]答案预览[/bold]\n{result['answer_preview']}")


def cmd_serve(args):
    """启动 FastAPI 服务（dev）"""
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
    )


def main():
    parser = argparse.ArgumentParser(prog="cortex")
    sub = parser.add_subparsers(dest="command")

    p_migrate = sub.add_parser("migrate", help="运行数据迁移")
    p_migrate.add_argument("--dry-run", action="store_true")
    p_migrate.add_argument("--skip-backup", action="store_true")
    p_migrate.set_defaults(func=cmd_migrate)

    p_rollback = sub.add_parser("rollback", help="回滚迁移")
    p_rollback.add_argument("--backup", help="指定备份目录")
    p_rollback.set_defaults(func=cmd_rollback)

    p_groups = sub.add_parser("groups", help="列出知识组")
    p_groups.set_defaults(func=cmd_groups)

    p_sources = sub.add_parser("sources", help="列出组下订阅源")
    p_sources.add_argument("slug", help="知识组 slug")
    p_sources.set_defaults(func=cmd_sources)

    p_run = sub.add_parser("run", help="手动跑一次组采集")
    p_run.add_argument("slug")
    p_run.add_argument("--force", action="store_true", help="忽略 interval")
    p_run.add_argument("--no-analyze", action="store_true", help="只采集不分析")
    p_run.set_defaults(func=cmd_run)

    p_search = sub.add_parser("search", help="调试：直接搜索")
    p_search.add_argument("platform")
    p_search.add_argument("query")
    p_search.add_argument("--limit", type=int, default=10)
    p_search.add_argument("--days", type=int, default=7)
    p_search.set_defaults(func=cmd_search)

    p_res = sub.add_parser("research", help="调试：按需研究（阻塞）")
    p_res.add_argument("question")
    p_res.add_argument("--slug", help="知识组 slug（可选）")
    p_res.add_argument("--days", type=int, default=7)
    p_res.add_argument("--limit", type=int, default=5)
    p_res.set_defaults(func=cmd_research)

    p_serve = sub.add_parser("serve", help="启动 FastAPI 服务")
    p_serve.add_argument("--host", default="0.0.0.0")
    p_serve.add_argument("--port", type=int, default=8080)
    p_serve.add_argument("--reload", action="store_true")
    p_serve.set_defaults(func=cmd_serve)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return
    args.func(args)


if __name__ == "__main__":
    main()
