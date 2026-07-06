"""仅生成报告（不重新采集）

基于 DB 里已有的信号和转录文件，跑一次 analyze_group 产出日报。
用于：采集中断后补产报告、手动刷新日报、定时只整理不采集。
"""
from __future__ import annotations
from app.db.schema import Task
from app.models.group import TaskKind
from app.services.knowledge_service import KnowledgeService
from app.tasks.registry import register_handler
from app.tasks.runner import TaskContext


@register_handler(TaskKind.ANALYZE)
def handle_analyze(task: Task, ctx: TaskContext) -> dict:
    """
    params: {"group_id": int}
    """
    params = task.params or {}
    group_id = params.get("group_id") or task.group_id
    if not group_id:
        raise ValueError("group_id required")

    ctx.log(f"开始整理报告（组 {group_id}），基于已有信号")
    ctx.progress({"stage": "analyzing"})
    result = KnowledgeService().analyze_group(group_id)

    if not result or not result.get("report_id"):
        ctx.log("没有可整理的新内容（所有内容已分析过或无新信号）")
        return {"report_id": None}

    ctx.log(f"✓ 生成报告 id={result['report_id']}")
    return {
        "report_id": result["report_id"],
        "report_path": result.get("report_path"),
    }
