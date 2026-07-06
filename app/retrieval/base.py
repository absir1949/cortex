"""知识库检索层抽象 - 为阶段 B（基于知识库积累的问答）预留接口

现阶段不实现具体检索器，只定义抽象。阶段 B 实现 KeywordRetriever（FTS5）
或 VectorRetriever（向量库）时不改上层 ResearchService。

设计：
  - Retriever.retrieve(question, group_id) → list[EvidenceChunk]
  - EvidenceChunk 是统一结构，无论来自档案/转录/信号/报告
  - ResearchService 未来按 mode 分叉：kb_only / kb_plus_search / search_only
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Literal


# 证据来源类型
EvidenceType = Literal["profile", "transcript", "signal", "report"]


@dataclass
class EvidenceChunk:
    """检索召回的统一证据片段"""
    type: EvidenceType                 # profile=观点档案 / transcript=转录 / signal=信号 / report=报告
    source_ref: str                    # 来源引用（如 creator_id / content_id / report_id）
    text: str                          # 文本内容
    score: float = 0.0                 # 相关性分数（0-1）
    metadata: dict = field(default_factory=dict)  # 附加信息（博主名、URL、时间等）


class Retriever(ABC):
    """知识库检索器抽象基类。

    阶段 B 实现：
      - KeywordRetriever: 基于 SQLite FTS5 的关键词检索（第一阶段，够用）
      - VectorRetriever: 基于向量库的语义检索（第二阶段，需要 embed()）
    """

    @abstractmethod
    def retrieve(
        self,
        question: str,
        group_id: int,
        *,
        top_k: int = 10,
    ) -> list[EvidenceChunk]:
        """从知识库检索与问题相关的证据片段。

        Args:
            question: 用户问题
            group_id: 知识库 ID
            top_k: 最多返回的片段数

        Returns:
            按相关性排序的证据列表
        """
        ...
