"""观点信号判定服务 - 采集时逐条判断新旧

流程：
  1. 读博主观点档案（ProfileManager）
  2. 喂给 LLM：档案 + 本条转录 + 评论摘要 → 判断 is_new / matched / new_points
  3. 若是新观点 → 更新档案
  4. 落 Signal 表（无论新旧都记，日报据此区分重点）

降级策略：
  - LLM 调用失败 → 当作「无判定」，不写 Signal（不阻塞采集，日报仍走老逻辑）
  - JSON 解析失败 → 同上
"""
from __future__ import annotations
import json
import re
from typing import Optional

from app.db.engine import get_session
from app.db.repos import SignalRepo
from app.db.schema import Source
from app.llm import OpenAICompatClient, LLMMessage
from app.services import config_service
from app.services.profile_service import ProfileManager


# 喂给 LLM 的文本上限（避免超 token）
MAX_TRANSCRIPT_CHARS = 8000
MAX_COMMENT_CHARS = 1500


class SignalService:
    """逐条观点判定"""

    def __init__(self):
        self.llm = OpenAICompatClient()
        self.profiles = ProfileManager()

    def evaluate(
        self,
        source: Source,
        content_id: str,
        transcript: str,
        comments: Optional[list[dict]] = None,
        create_time: Optional[str] = None,
        raise_on_failure: bool = False,
        global_content_id: Optional[int] = None,
    ) -> Optional[dict]:
        """判定一条内容的观点新旧。

        返回 {is_new, summary, matched_points, new_points} 或 None（判定失败时）。
        """
        profile = self.profiles.load(source)

        transcript_block = (transcript or "")[:MAX_TRANSCRIPT_CHARS]
        comments_block = self._build_comments_block(comments or [])

        template = config_service.prompt("signal_judge_prompt_template")
        prompt_text = template.format(
            author=source.display_name,
            profile=profile,
            transcript=transcript_block,
            comments=comments_block or "（无评论）",
        )

        try:
            raw = self.llm.chat(
                [
                    LLMMessage(role="system", content="你是电商行业分析师，判断创作者内容是否带来新观点。严格按要求输出 JSON。"),
                    LLMMessage(role="user", content=prompt_text),
                ],
                config=config_service.get_llm_config(),
            )
        except Exception as e:
            if raise_on_failure:
                raise RuntimeError(f"LLM 观点判定调用失败: {e}") from e
            return None

        parsed = self._parse_json(raw)
        if not parsed:
            if raise_on_failure:
                preview = (raw or "")[:300].replace("\n", " ")
                raise RuntimeError(f"LLM 观点判定 JSON 解析失败: {preview}")
            return None

        # 规范化字段
        is_new = bool(parsed.get("is_new", False))
        summary = str(parsed.get("summary", "")).strip()
        matched = self._as_str_list(parsed.get("matched_points"))
        new_points = self._as_str_list(parsed.get("new_points"))

        # 新观点阈值：至少 N 个新观点才算「新信号」
        min_new = config_service.system_int("signal_min_new_points", 1)
        if is_new and len(new_points) < min_new:
            is_new = False

        # 新观点才更新档案（避免档案被重复内容撑大）
        profile_error = ""
        profile_updated = False
        if is_new and new_points:
            try:
                self.profiles.update(source, new_points, summary, date=create_time)
                profile_updated = True
            except Exception as e:
                profile_error = str(e)

        # 落 Signal 表
        with get_session() as s:
            SignalRepo(s).create(
                source_id=source.id,
                content_id=content_id,
                global_content_id=global_content_id,
                group_id=source.group_id,
                is_new=is_new,
                summary=summary,
                matched_points=matched,
                new_points=new_points,
            )

        return {
            "is_new": is_new,
            "summary": summary,
            "matched_points": matched,
            "new_points": new_points,
            "profile_updated": profile_updated,
            "profile_error": profile_error,
        }

    # ------ helpers ------

    @staticmethod
    def _build_comments_block(comments: list[dict]) -> str:
        if not comments:
            return ""
        lines = []
        for c in comments[:8]:
            author = c.get("author", "")
            text = c.get("text", "")
            likes = c.get("likes", 0)
            lines.append(f"- 👍{likes} @{author}: {text}")
        block = "\n".join(lines)
        return block[:MAX_COMMENT_CHARS]

    @staticmethod
    def _parse_json(text: str) -> Optional[dict]:
        """从 LLM 输出里抠 JSON（兼容代码块包裹和多余文本）"""
        if not text:
            return None
        # 先尝试直接 parse
        try:
            return json.loads(text)
        except Exception:
            pass
        # 抠 ```json ... ``` 代码块
        m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(1))
            except Exception:
                pass
        # 抠第一个 { ... } 块
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                pass
        return None

    @staticmethod
    def _as_str_list(val) -> list[str]:
        if isinstance(val, list):
            return [str(x).strip() for x in val if str(x).strip()]
        if isinstance(val, str) and val.strip():
            return [val.strip()]
        return []
