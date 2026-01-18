"""Cortex CLI - 命令行入口"""
import sys
import signal
from pathlib import Path
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from config import CreatorConfig
from scheduler import CortexCore, CortexScheduler
from knowledge import extract_knowledge

console = Console()


class CortexCLI:
    """Cortex 命令行界面"""

    def __init__(self):
        self.config = CreatorConfig()
        self.core = CortexCore()
        self.scheduler = CortexScheduler()

    def cmd_list(self):
        """列出所有创作者"""
        creators = self.config.get_all()

        if not creators:
            console.print("[yellow]没有配置创作者[/yellow]")
            console.print("\n添加创作者:")
            console.print("  python cli.py add <名称> <平台> <ID>")
            return

        table = Table(title="创作者列表")
        table.add_column("名称", style="cyan")
        table.add_column("平台", style="green")
        table.add_column("ID", style="blue")
        table.add_column("间隔", style="yellow")
        table.add_column("状态", style="magenta")

        for c in creators:
            status = "✓ 启用" if c.get('enabled', True) else "✗ 禁用"
            table.add_row(
                c['name'],
                c['platform'],
                c['id'][:20] + '...',
                f"{c.get('interval_hours', 48)}h",
                status
            )

        console.print(table)

    def cmd_add(self, name: str, platform: str, creator_id: str, interval: int = 48):
        """添加创作者"""
        creator = self.config.add(name, platform, creator_id, interval)
        console.print(f"[green]✓ 已添加创作者: {name}[/green]")
        console.print(f"  平台: {platform}")
        console.print(f"  ID: {creator_id}")
        console.print(f"  间隔: {interval}h")

    def cmd_remove(self, name: str):
        """删除创作者"""
        self.config.remove(name)
        console.print(f"[green]✓ 已删除创作者: {name}[/green]")

    def cmd_run(self):
        """运行一次所有创作者"""
        self.core.run_once()

    def cmd_transcribe(self):
        """给已下载但未转录的视频补充转录"""
        self.core.run_once(skip_transcribe=False, transcribe_existing=True)

    def cmd_start(self):
        """启动定时调度"""
        self.scheduler.start()

        console.print("\n[green]按 Ctrl+C 停止[/green]")

        # 等待中断信号
        try:
            import time
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            self.scheduler.stop()

    def cmd_stop(self):
        """停止调度"""
        self.scheduler.stop()

    def cmd_status(self):
        """显示状态"""
        self.scheduler.status()

    def cmd_knowledge(self):
        """生成知识报告"""
        extract_knowledge()

    def cmd_videos(self, creator_name: str = None):
        """列出已处理视频"""
        if creator_name:
            # 显示特定创作者的视频
            from storage import StorageManager
            storage = StorageManager(creator_name)
            videos = storage.list_videos()

            console.print(f"\n[bold cyan]{creator_name}[/bold cyan] - {len(videos)} 个视频\n")

            for v in videos:
                console.print(f"  • {v.get('title', 'N/A')[:50]}")
                console.print(f"    {v.get('video_id', '')} | {v.get('create_time', '')}")

        else:
            # 显示所有创作者的视频统计
            data_dir = Path(__file__).parent / "data"

            total = 0
            for creator_dir in data_dir.iterdir():
                if not creator_dir.is_dir():
                    continue

                count = len(list(creator_dir.glob("*.json")))
                total += count
                console.print(f"  {creator_dir.name}: {count} 个视频")

            console.print(f"\n  总计: {total} 个视频")

    def run(self):
        """运行 CLI"""
        if len(sys.argv) < 2:
            self.show_help()
            return

        command = sys.argv[1].lower()

        if command == "list":
            self.cmd_list()

        elif command == "add":
            if len(sys.argv) < 5:
                console.print("[red]用法: python cli.py add <名称> <平台> <ID> [间隔] [/red]")
                return
            interval = int(sys.argv[5]) if len(sys.argv) > 5 else 48
            self.cmd_add(sys.argv[2], sys.argv[3], sys.argv[4], interval)

        elif command == "remove":
            if len(sys.argv) < 3:
                console.print("[red]用法: python cli.py remove <名称>[/red]")
                return
            self.cmd_remove(sys.argv[2])

        elif command == "run":
            self.cmd_run()

        elif command == "transcribe":
            self.cmd_transcribe()

        elif command == "start":
            self.cmd_start()

        elif command == "stop":
            self.cmd_stop()

        elif command == "status":
            self.cmd_status()

        elif command == "knowledge":
            self.cmd_knowledge()

        elif command == "videos":
            creator = sys.argv[2] if len(sys.argv) > 2 else None
            self.cmd_videos(creator)

        else:
            console.print(f"[red]未知命令: {command}[/red]")
            self.show_help()

    def show_help(self):
        """显示帮助"""
        help_text = """
[bold cyan]Cortex - 内容智能采集系统[/bold cyan]

[bold]命令:[/bold]

  python cli.py [yellow]list[/yellow]           - 列出所有创作者
  python cli.py [yellow]add[/yellow] <名称> <平台> <ID> [间隔]
                                  - 添加创作者
  python cli.py [yellow]remove[/yellow] <名称>    - 删除创作者
  python cli.py [yellow]run[/yellow]            - 运行一次（手动执行）
  python cli.py [yellow]transcribe[/yellow]     - 给已下载视频补充转录
  python cli.py [yellow]start[/yellow]          - 启动定时监控
  python cli.py [yellow]stop[/yellow]           - 停止监控
  python cli.py [yellow]status[/yellow]          - 查看状态
  python cli.py [yellow]knowledge[/yellow]       - 生成知识报告
  python cli.py [yellow]videos[/yellow] [名称]   - 查看已处理视频

[bold]示例:[/bold]

  python cli.py add 九栢米电商 douyin MS4wLjABAAAA... 48
  python cli.py run
  python cli.py start
  python cli.py knowledge

[bold]支持平台:[/bold]

  douyin  - 抖音
  (更多平台开发中...)
        """
        console.print(help_text)


if __name__ == "__main__":
    cli = CortexCLI()
    cli.run()
