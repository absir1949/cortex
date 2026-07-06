"""跨博主趋势提炼 - 把多个博主的新观点放一起，找出共同趋势

设计：
  - 输入：组内最近 N 天的所有 is_new=True 信号
  - LLM 聚类：找被 ≥2 个博主讲的观点 = 行业趋势
  - 输出：结构化趋势列表 [{trend, source_names, signal_count, momentum, why_hot}]
  - 降级：信号不足或 LLM 失败 → 返回 None，日报照常出
"""
from __future__ import annotations
import json
import re
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Optional

from app.db.engine import get_session
from app.db.repos import SignalRepo, SourceRepo
from app.llm import OpenAICompatClient, LLMMessage
from app.services import config_service


# 单个博主的信号上限（避免某个高产博主霸占整个 prompt）
MAX_SIGNALS_PER_SOURCE = 8
# 信号块总字数上限
MAX_SIGNAL_BLOCK_CHARS = 6000


class InsightService:
    """跨博主趋势提炼"""

    def __init__(self):
        self.llm = OpenAICompatClient()

    def build_group_insights(self, group_id: int, *, days: int = 14) -> Optional[dict]:
        """提炼组内跨博主趋势。返回 {trends, raw_signal_count, days} 或 None"""
        signals = self._recent_new_signals(group_id, days)
        if len(signals) < 2:
            return None

        trends = self._llm_cluster(group_id, signals, days)
        if trends is None:
            return None  # LLM 失败

        # 过滤阈值：少于 min_sources 个博主的趋势不算
        min_sources = config_service.system_int("insight_min_sources", 2)
        trends = [t for t in trends if len(t.get("source_names", [])) >= min_sources]

        return {
            "trends": trends,
            "raw_signal_count": len(signals),
            "days": days,
        }

    # ============ 内部 ============

    def _recent_new_signals(self, group_id: int, days: int) -> list[dict]:
        """拿组内最近 N 天的 is_new=True 信号，附博主名"""
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        with get_session() as s:
            signals = SignalRepo(s).list_new_by_group(group_id, limit=500)
            # 按 created_at 过滤
            recent = []
            for sig in signals:
                try:
                    if sig.created_at and sig.created_at >= cutoff:
                        recent.append(sig)
                except Exception:
                    recent.append(sig)
            # 附博主名
            source_ids = {sig.source_id for sig in recent}
            sources = {src.id: src for src in SourceRepo(s).list_by_group(group_id)}
        out = []
        for sig in recent:
            src = sources.get(sig.source_id)
            out.append({
                "content_id": sig.content_id,
                "source_id": sig.source_id,
                "source_name": src.display_name if src else f"source#{sig.source_id}",
                "summary": sig.summary,
                "new_points": list(sig.new_points or []),
                "created_at": sig.created_at,
            })
        return out

    def _llm_cluster(self, group_id: int, signals: list[dict], days: int) -> Optional[list[dict]]:
        """喂 LLM 做跨源聚类，返回趋势列表"""
        # 按博主分组，每博主限制信号数
        by_source: dict[str, list[dict]] = defaultdict(list)
        for sig in signals:
            by_source[sig["source_name"]].append(sig)
        # 截断每个博主的信号
        for name in by_source:
            by_source[name] = by_source[name][:MAX_SIGNALS_PER_SOURCE]

        signals_block = self._build_signals_block(by_source)
        if not signals_block.strip():
            return []

        # 组名
        group_name = self._group_name(group_id)
        min_sources = config_service.system_int("insight_min_sources", 2)

        template = config_service.prompt("insight_prompt_template")
        prompt_text = template.format(
            group_name=group_name,
            days=days,
            min_sources=min_sources,
            signals_block=signals_block,
        )

        try:
            raw = self.llm.chat(
                [
                    LLMMessage(
                        role="system",
                        content="你是电商行业分析师，擅长从多个创作者的内容里发现共同趋势。严格按要求输出 JSON。",
                    ),
                    LLMMessage(role="user", content=prompt_text),
                ],
                config=config_service.get_llm_config(),
            )
        except Exception:
            return None

        parsed = self._parse_json(raw)
        if not parsed:
            return []
        trends = parsed.get("trends") or []
        # 规范化每条趋势
        normalized = []
        for t in trends if isinstance(trends, list) else []:
            if not isinstance(t, dict):
                continue
            try:
                signal_count = int(float(t.get("signal_count", 0) or 0))
            except (TypeError, ValueError):
                signal_count = len(self._as_str_list(t.get("source_names")))
            normalized.append({
                "trend": str(t.get("trend", "")).strip(),
                "source_names": self._as_str_list(t.get("source_names")),
                "signal_count": signal_count,
                "momentum": str(t.get("momentum", "→ 稳定")).strip(),
                "why_hot": str(t.get("why_hot", "")).strip(),
            })
        return normalized

    @staticmethod
    def _build_signals_block(by_source: dict[str, list[dict]]) -> str:
        """按博主分组列出新观点"""
        parts = []
        for name, sigs in by_source.items():
            points = []
            for sig in sigs:
                if sig.get("new_points"):
                    for p in sig["new_points"]:
                        if p not in points:
                            points.append(p)
                elif sig.get("summary"):
                    if sig["summary"] not in points:
                        points.append(sig["summary"])
            if not points:
                continue
            date_hint = (sigs[0].get("created_at", "") or "")[:10]
            lines = [f"### {name}（{len(sigs)} 条新信号，最近 {date_hint}）"]
            for p in points[:6]:
                lines.append(f"- {p}")
            parts.append("\n".join(lines))
        block = "\n\n".join(parts)
        return block[:MAX_SIGNAL_BLOCK_CHARS]

    @staticmethod
    def _group_name(group_id: int) -> str:
        from app.db.repos import GroupRepo
        try:
            with get_session() as s:
                g = GroupRepo(s).get(group_id)
                return g.name if g else str(group_id)
        except Exception:
            return str(group_id)

    @staticmethod
    def _parse_json(text: str) -> Optional[dict]:
        if not text:
            return None
        try:
            return json.loads(text)
        except Exception:
            pass
        m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(1))
            except Exception:
                pass
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
