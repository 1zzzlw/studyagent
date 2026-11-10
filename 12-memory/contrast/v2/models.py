"""A-Mem 记忆笔记及模型输出；不包含 GA 节点或衰减强化字段。"""
from typing import Literal
from uuid import uuid4

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator


class MemoryNote(BaseModel):
    """沿用 A-Mem 的字段名称。时间使用带时区的 ISO 时间，便于持久化和展示。"""
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: str(uuid4()))
    content: str = Field(min_length=1, description="记忆原文，语义演化不改写正文")
    keywords: list[str] = Field(default_factory=list, description="具体关键词")
    context: str = "General"
    tags: list[str] = Field(default_factory=list, description="分类标签")
    category: str = "Uncategorized"
    links: list[str] = Field(default_factory=list, description="本笔记指向的相关笔记 ID")
    timestamp: AwareDatetime
    last_accessed: AwareDatetime
    retrieval_count: int = Field(default=0, ge=0, description="正常提问时进入回答上下文的累计次数，不参与排序")
    evolution_history: list[dict] = Field(default_factory=list, description="关联或语义描述的修改记录")


class NoteAnalysis(BaseModel):
    """对应 A-Mem 的 analyze_content：只理解内容，不评价记忆强度。"""
    keywords: list[str]
    context: str
    tags: list[str]


class NeighborUpdate(BaseModel):
    id: str = Field(description="候选邻居的真实 ID，不使用数组序号")
    context: str
    tags: list[str]


class NoteEvolution(BaseModel):
    """对应 process_memory 的两种动作；strengthen 在这里指建立链接。"""
    should_evolve: bool
    actions: list[Literal["strengthen", "update_neighbor"]]
    suggested_connections: list[str]
    tags_to_update: list[str]
    neighbor_updates: list[NeighborUpdate]


class RecallReply(BaseModel):
    """仅用于聊天应用展示回答与引用，不属于记忆存储结构。"""
    outcome: Literal["answered", "recalled", "uncertain", "not_recalled"]
    answer: str = Field(min_length=1)
    used_memory_ids: list[str]

    @model_validator(mode="after")
    def check_references(self):
        if (self.outcome == "recalled") != bool(self.used_memory_ids):
            raise ValueError("只有 recalled 回答携带实际采用的记忆 ID")
        return self


class Candidate(BaseModel):
    id: str
    score: float | None = None
    reason: str = "semantic"
