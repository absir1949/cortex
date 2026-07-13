"""定时订阅采集 handler（也支持手动触发）"""
from __future__ import annotations
from app.models.group import TaskKind
from app.services.ingest_service import IngestService
from app.services.knowledge_service import KnowledgeService
from app.tasks.registry import register_handler
from app.tasks.runner import TaskContext
from app.db.schema import Task


@register_handler(TaskKind.INGEST_TARGET)
def handle_ingest_target(task: Task, ctx: TaskContext) -> dict:
    """共享采集目标级任务。params: {"target_id": int, "force": bool, "days": int?}"""
    params = task.params or {}
    target_id = params.get("target_id")
    if not target_id:
        raise ValueError("target_id required")
    force = bool(params.get("force", False))
    days_override = params.get("days")
    ctx.log(f"开始采集目标 {target_id}" + (f"（回看 {days_override} 天）" if days_override else ""))
    return IngestService().refresh_target(
        int(target_id),
        log_cb=lambda m: ctx.log(m),
        is_cancelled=ctx.is_cancelled,
        force=force,
        days_override=days_override,
        task_id=ctx.task_id,
    )


@register_handler(TaskKind.INGEST)
def handle_ingest(task: Task, ctx: TaskContext) -> dict:
    """
    params:
      {"group_id": int, "force": bool, "analyze": bool, "source_id": int?, "target_id": int?}

    如果指定 source_id，只跑该源；否则跑整个组。
    analyze=True 时采集完触发知识提炼（仅 group 模式）；默认只刷新不整理。
    """
    params = task.params or {}
    group_id = params.get("group_id") or task.group_id
    source_id = params.get("source_id") or task.source_id
    target_id = params.get("target_id")
    force = bool(params.get("force", False))
    analyze = bool(params.get("analyze", False))

    svc = IngestService()

    if target_id:
        ctx.log(f"开始采集目标 {target_id}")
        return svc.refresh_target(
            int(target_id),
            log_cb=lambda m: ctx.log(m),
            is_cancelled=ctx.is_cancelled,
            force=force,
            days_override=params.get("days"),
            task_id=ctx.task_id,
        )

    if source_id:
        from app.services.source_service import SourceService
        src = SourceService().get(source_id)
        if not src:
            raise ValueError(f"source {source_id} not found")
        # 单源刷新：支持 force 和 days 覆盖（作者主页"刷新这个作者"用）
        force = bool(params.get("force", True))
        days_override = params.get("days")
        ctx.log(f"开始采集源: {src.display_name}" + (f"（回看 {days_override} 天）" if days_override else ""))
        result = svc.refresh_source(
            src,
            log_cb=lambda m: ctx.log(m),
            is_cancelled=ctx.is_cancelled,
            force=force,
            days_override=days_override,
            task_id=ctx.task_id,
        )
        return {
            "new_contents": result["counts"].get("new_contents", 0),
            "source_id": source_id,
            "refresh": result,
        }

    if not group_id:
        raise ValueError("group_id or source_id required")

    ctx.log(f"开始采集组 {group_id}")
    result = svc.run_group(
        group_id,
        force=force,
        progress_cb=ctx.progress,
        log_cb=lambda m: ctx.log(m),
        is_cancelled=ctx.is_cancelled,
        task_id=ctx.task_id,
    )

    # 分析
    if analyze and not ctx.is_cancelled():
        ctx.log("开始知识提炼...")
        ctx.progress({"stage": "analyzing"})
        try:
            knowledge_result = KnowledgeService().analyze_group(group_id, refresh_summary=result)
            if knowledge_result and knowledge_result.get("report_id"):
                result["report_id"] = knowledge_result["report_id"]
                result["report_path"] = knowledge_result["report_path"]
                ctx.log(f"✓ 生成报告 id={knowledge_result['report_id']}")
        except Exception as e:
            ctx.log(f"知识提炼失败: {e}", level="warning")

    return result
