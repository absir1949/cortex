"""观点档案管理 - 每个博主一份持续更新的观点沉淀

档案存文件系统（group 级）：knowledge/{group_slug}/profiles/{source_id}.md
设计：
  - load() 读现有档案，没有则返回空档案骨架
  - update() 调 LLM 把新观点合并进档案（保留原有结构，增量更新）
  - 档案格式 markdown：核心方法论 / 反复强调 / 最近转变 / 已讲过的点
"""
from __future__ import annotations
import threading
from datetime import datetime
from typing import Optional

from app.db.engine import get_session
from app.db.repos import GroupRepo, SourceRepo
from app.db.schema import Source
from app.llm import LLMUsageContext, OpenAICompatClient, LLMMessage, chat_with_usage
from app.storage import paths
from app.services import config_service


# 按 source_id 分桶的文件锁：防止并发采集任务同时更新同一博主档案导致丢失更新
_profile_locks: dict[int, threading.Lock] = {}
_locks_guard = threading.Lock()


def _get_profile_lock(source_id: int) -> threading.Lock:
    """获取（或创建）某个 source 的专属锁"""
    with _locks_guard:
        if source_id not in _profile_locks:
            _profile_locks[source_id] = threading.Lock()
        return _profile_locks[source_id]


# 档案初始骨架
_EMPTY_PROFILE = """# 观点档案

## 核心方法论
（暂无）

## 反复强调
（暂无）

## 最近转变
（暂无）

## 已讲过的点
（暂无）
"""


class ProfileManager:
    """博主的观点档案读写 + LLM 增量更新。

    档案按 creator_id 全局存储（knowledge/profiles/{creator_id}.md），
    同一博主即使被多个组关注也共用一份档案。
    """

    def __init__(self):
        self.llm = OpenAICompatClient()

    @staticmethod
    def _creator_id_of(source: Source) -> Optional[int]:
        """取 source 关联的 creator_id；没有则按 (platform, identifier) 现查"""
        if source.creator_id:
            return source.creator_id
        # 兜底：老 source 可能 creator_id 未回填，现查 alias
        from app.db.repos import CreatorRepo
        with get_session() as s:
            creator = CreatorRepo(s).find_by_platform_uid(source.platform, source.identifier)
            return creator.id if creator else None

    def load(self, source: Source) -> str:
        """读档案；不存在则返回空骨架"""
        cid = self._creator_id_of(source)
        if cid is None:
            return _EMPTY_PROFILE
        path = paths.profile_path(cid)
        if path.exists():
            return path.read_text(encoding="utf-8")
        return _EMPTY_PROFILE

    def update(
        self,
        source: Source,
        new_points: list[str],
        summary: str,
        *,
        date: Optional[str] = None,
        global_content_id: Optional[int] = None,
    ) -> str:
        """把新观点合并进档案。调 LLM 增量更新，返回新档案内容。

        整个「读→LLM→写」序列持锁，防止并发采集任务同时更新同一博主档案导致丢失更新。
        """
        if not new_points:
            return self.load(source)

        cid = self._creator_id_of(source)
        if cid is None:
            return self.load(source)
        path = paths.profile_path(cid)
        path.parent.mkdir(parents=True, exist_ok=True)

        # 按 creator 加锁：同一博主的档案串行更新，不同博主可并行
        with _get_profile_lock(cid):
            current = self.load(source)
            date_str = date or datetime.now().strftime("%Y-%m-%d")
            new_points_block = "\n".join(f"- {p}" for p in new_points)

            template = config_service.prompt("profile_update_prompt_template")
            prompt_text = template.format(
                author=source.display_name,
                profile=current,
                new_points=new_points_block,
                summary=summary,
                date=date_str,
            )

            try:
                updated = chat_with_usage(
                    self.llm,
                    [
                        LLMMessage(role="system", content="你是电商行业分析师，负责维护创作者的观点档案，只做增量合并，输出完整 markdown。"),
                        LLMMessage(role="user", content=prompt_text),
                    ],
                    config=config_service.get_llm_config(),
                    usage_context=LLMUsageContext(
                        operation="profile_update",
                        group_id=source.group_id,
                        source_id=source.id,
                        creator_id=cid,
                        global_content_id=global_content_id,
                    ),
                )
            except Exception:
                # LLM 失败时降级：手动把新观点追加到「已讲过的点」末尾，保证不丢
                updated = self._fallback_append(current, new_points, date_str)

            updated = updated.strip() or current
            path.write_text(updated, encoding="utf-8")
            return updated

    @staticmethod
    def _fallback_append(profile: str, new_points: list[str], date: str) -> str:
        """LLM 失败时的降级：直接在「已讲过的点」末尾追加"""
        lines = profile.splitlines()
        append = [f"- [{date}] {p}" for p in new_points]
        # 找到「已讲过的点」段落
        for i, line in enumerate(lines):
            if line.strip() == "## 已讲过的点":
                # 删掉占位的「（暂无）」
                tail = lines[i + 1:] if i + 1 < len(lines) else []
                # 过滤掉占位
                tail = [l for l in tail if l.strip() not in ("（暂无）", "(暂无)")]
                return "\n".join(lines[:i + 1] + [""] + append + [""] + tail) + "\n"
        # 没找到段落就追加到末尾
        return profile.rstrip() + "\n\n## 已讲过的点\n\n" + "\n".join(append) + "\n"
