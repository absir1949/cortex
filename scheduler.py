"""定时调度和核心处理逻辑"""
import time
from pathlib import Path
from datetime import datetime
from typing import List
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from rich.console import Console
from rich.progress import track

from config import CreatorConfig, Config
from platforms import get_adapter
from storage import StorageManager

console = Console()


class CortexCore:
    """Cortex 核心处理器"""

    def __init__(self):
        self.config = CreatorConfig()
        Config.ensure_dirs()

    def process_creator(self, creator: dict, skip_transcribe: bool = False, transcribe_existing: bool = False):
        """处理单个创作者

        Args:
            creator: 创作者配置
            skip_transcribe: 是否跳过转录
            transcribe_existing: 是否给已下载但未转录的视频补充转录
        """
        name = creator['name']
        platform = creator['platform']
        creator_id = creator['id']
        days = creator.get('days', 7)

        console.print(f"\n[bold cyan]🎯 处理创作者: {name}[/bold cyan]")

        # 初始化
        storage = StorageManager(name)
        adapter = get_adapter(platform, creator)

        # 如果是补充转录模式
        if transcribe_existing:
            self._transcribe_existing_videos(storage, name, skip_transcribe)
            return

        # 获取视频列表
        with console.status(f"[yellow]获取视频列表..."):
            videos = adapter.fetch_videos(creator_id, count=50)

        console.print(f"  获取到 {len(videos)} 个视频")

        # 显示最新视频的日期
        if videos:
            latest_date = max(v.create_time for v in videos)
            console.print(f"  最新视频日期: {latest_date}")

        # 过滤新视频
        new_videos = []
        existing_count = 0
        for video in videos:
            if not storage.exists(video.video_id):
                new_videos.append(video)
            else:
                existing_count += 1

        console.print(f"  新视频: {len(new_videos)} 个 (已存在: {existing_count} 个)")

        if not new_videos:
            console.print(f"  [dim]没有新视频，跳过[/dim]")
            return

        # 处理每个视频
        for video in track(new_videos, description="处理视频"):
            try:
                # 1. 下载视频
                temp_video_path = f"/tmp/{video.video_id}.mp4"
                if not adapter.download_video(video, temp_video_path):
                    console.print(f"    [red]✗[/red] {video.title[:30]} - 下载失败")
                    continue

                # 2. 保存视频
                import shutil
                final_path = storage.save_video(video.video_id, temp_video_path, video.create_time)

                # 3. 转录（如果未跳过）
                transcription_text = None
                if not skip_transcribe:
                    try:
                        from transcriber import transcribe_video
                        transcription_text = transcribe_video(str(final_path))
                        storage.save_transcript(video.video_id, transcription_text, video.create_time)
                    except Exception as e:
                        console.print(f"    [yellow]⚠[/yellow] {video.title[:30]} - 转写失败: {str(e)[:30]}")

                # 4. 保存元数据
                storage.save_metadata(video.video_id, {
                    'video_id': video.video_id,
                    'title': video.title,
                    'author': video.author,
                    'create_time': video.create_time,
                    'platform': video.platform,
                    'share_url': video.share_url,
                    'statistics': video.statistics,
                    'downloaded_at': datetime.now().isoformat(),
                    'file_size': Path(temp_video_path).stat().st_size,
                    'transcribed': transcription_text is not None
                })

                status = f"{'+' + str(len(transcription_text)) + '字' if transcription_text else '视频'}"
                console.print(f"    [green]✓[/green] {video.title[:40]} [{status}]")

                # 清理临时文件
                Path(temp_video_path).unlink(missing_ok=True)

            except Exception as e:
                console.print(f"    [red]✗[/red] {video.title[:30]} - {str(e)[:40]}")

        # 更新最后检查时间
        self.config.update_last_check(name)
        console.print(f"[green]✓ 完成[/green]")

    def _transcribe_existing_videos(self, storage, name: str, skip_transcribe: bool):
        """给已下载但未转录的视频补充转录"""
        import shutil
        from transcriber import transcribe_video

        # 找出已下载但未转录的视频
        videos_to_transcribe = []
        for video_file in storage.get_creator_dir().glob("*.mp4"):
            video_id = video_file.stem
            if not storage.has_transcript(video_id):
                # 读取元数据获取标题
                metadata = storage.get_metadata(video_id)
                title = metadata.get('title', video_id) if metadata else video_id
                videos_to_transcribe.append({
                    'video_id': video_id,
                    'path': video_file,
                    'title': title
                })

        if not videos_to_transcribe:
            console.print(f"  [dim]没有需要转录的视频[/dim]")
            return

        console.print(f"  需要转录: {len(videos_to_transcribe)} 个视频")

        for video_info in track(videos_to_transcribe, description="转录中"):
            try:
                if not skip_transcribe:
                    transcription_text = transcribe_video(str(video_info['path']))
                    storage.save_transcript(video_info['video_id'], transcription_text)
                    console.print(f"    [green]✓[/green] {video_info['title'][:40]} [+{len(transcription_text)}字]")
                else:
                    console.print(f"    [dim]⊘[/dim] {video_info['title'][:40]} [跳过]")
            except Exception as e:
                console.print(f"    [red]✗[/red] {video_info['title'][:30]} - {str(e)[:30]}")

        self.config.update_last_check(name)
        console.print(f"[green]✓ 完成[/green]")

    def run_once(self, skip_transcribe: bool = False, transcribe_existing: bool = False, force_check: bool = False):
        """运行一次所有创作者

        Args:
            skip_transcribe: 是否跳过转录
            transcribe_existing: 是否给已下载但未转录的视频补充转录
            force_check: 是否强制检查（忽略时间间隔）
        """
        creators = self.config.get_enabled()

        if not creators:
            console.print("[yellow]没有启用的创作者[/yellow]")
            return

        if force_check:
            console.print(f"\n[bold]Cortex - 强制检查 {len(creators)} 个创作者[/bold]")
        else:
            console.print(f"\n[bold]Cortex - 处理 {len(creators)} 个创作者[/bold]")

        for creator in creators:
            # 检查是否需要更新（除非强制检查）
            if not force_check:
                # 检查时间间隔
                last_check = creator.get('last_check')
                if last_check:
                    from datetime import datetime, timedelta
                    last_time = datetime.fromisoformat(last_check)
                    interval = timedelta(hours=creator.get('interval_hours', 48))
                    if datetime.now() - last_time < interval:
                        console.print(f"\n🎯 处理创作者: {creator['name']}")
                        console.print(f"  [dim]距离上次检查不足 {creator.get('interval_hours', 48)} 小时，跳过[/dim]")
                        continue

            self.process_creator(creator, skip_transcribe, transcribe_existing)

        console.print("\n[bold green]✓ 全部完成[/bold green]")


class CortexScheduler:
    """Cortex 定时调度器"""

    def __init__(self):
        self.core = CortexCore()
        self.scheduler = BackgroundScheduler()
        self.running = False

    def start(self):
        """启动定时调度"""
        if self.running:
            console.print("[yellow]调度器已在运行[/yellow]")
            return

        creators = self.core.config.get_enabled()

        for creator in creators:
            interval_hours = creator.get('interval_hours', 48)
            trigger = IntervalTrigger(hours=interval_hours)

            self.scheduler.add_job(
                self.core.process_creator,
                trigger=trigger,
                id=f"creator_{creator['name']}",
                args=[creator],
                name=f"{creator['name']} ({interval_hours}h)"
            )

        self.scheduler.start()
        self.running = True

        console.print(f"[green]✓ 调度器已启动[/green]")
        console.print(f"  监控 {len(creators)} 个创作者")

        # 显示下次运行时间
        self.show_next_runs()

    def show_next_runs(self):
        """显示下次运行时间"""
        jobs = self.scheduler.get_jobs()
        if not jobs:
            return

        console.print("\n[bold]下次运行时间:[/bold]")
        for job in jobs:
            next_run = job.next_run_time.strftime('%Y-%m-%d %H:%M:%S') if job.next_run_time else 'Unknown'
            console.print(f"  {job.name}: {next_run}")

    def stop(self):
        """停止调度"""
        if not self.running:
            return

        self.scheduler.shutdown()
        self.running = False
        console.print("[yellow]调度器已停止[/yellow]")

    def status(self):
        """显示状态"""
        if self.running:
            console.print("[green]● 调度器运行中[/green]")
            self.show_next_runs()
        else:
            console.print("[dim]○ 调度器未启动[/dim]")
