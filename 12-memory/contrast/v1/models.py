"""v1 记忆结构与模型输出；基于原版 v2，算法不写在数据类中。"""
from datetime import datetime
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator


class ConceptNode(BaseModel):
    """沿用原版 v2：事件、想法、聊天、来源/证据和衰减字段。"""
    model_config = ConfigDict(validate_assignment=True, allow_inf_nan=False)
    node_id: str
    node_count: int = Field(ge=1)
    type_count: int = Field(ge=1)
    type: Literal["event", "thought", "chat"] = "event"
    depth: int = Field(default=0, ge=0)
    created: AwareDatetime
    expiration: AwareDatetime | None = None
    last_accessed: AwareDatetime
    subject: str = "用户"
    predicate: str = "表示"
    object: str = "过去的经历"
    description: str = Field(min_length=1)
    keywords: set[str] = Field(default_factory=set)
    poignancy: float = Field(default=5, ge=1, le=10)
    filling: list[str] | list[tuple[str, str]] = Field(default_factory=list)
    source_observation_id: str | None = None
    origin: Literal["seed", "dialogue", "reflection"] = "dialogue"
    attention: float = Field(default=1, ge=0, le=1)
    emotional_impact: float = Field(default=0, ge=0, le=1)
    initial_strength: float = Field(default=1, ge=0, le=1)
    strength_after_recall: float = Field(default=1, ge=0, le=1)
    stability_days: float = Field(default=30, gt=0)
    recall_count: int = Field(default=0, ge=0)
    status: Literal["active", "fading", "forgotten", "superseded"] = "active"
    supersedes_id: str | None = None
    reflected: bool = False


    @model_validator(mode="after")
    def validate_times_and_filling(self):
        if self.last_accessed < self.created:
            raise ValueError("回忆时间不能早于形成时间")
        if self.type == "chat":
            if any(isinstance(item, str) for item in self.filling):
                raise ValueError("chat.filling 保存实际双方原话")
        elif any(not isinstance(item, str) for item in self.filling):
            raise ValueError("event/thought.filling 保存证据 ID")
        return self


class RecallReply(BaseModel):
    outcome: Literal["answered", "recalled", "uncertain", "not_recalled"]
    answer: str = Field(min_length=1)
    used_memory_ids: list[str]

    @model_validator(mode="after")
    def validate_usage(self):
        if (self.outcome == "recalled") != bool(self.used_memory_ids):
            raise ValueError("只有 recalled 才能列出实际采用的长期记忆")
        return self


class MemoryDraft(BaseModel):
    """共同的事实提炼格式；独立反思只由支持反思的版本负责。"""
    description: str = Field(min_length=1)
    subject: str
    predicate: str
    object: str
    keywords: set[str]
    poignancy: float = Field(ge=1, le=10)
    attention: float = Field(ge=0, le=1)
    emotional_impact: float = Field(ge=0, le=1)
    filling: list[str] = Field(default_factory=list)
    supersedes_id: str | None = None


class Appraisal(BaseModel):
    memories: list[MemoryDraft] = Field(max_length=5)


class Insight(BaseModel):
    description: str = Field(min_length=1)
    # 数量和引用合法性逐条检查，避免一个错误导致整批有效认识被拒绝。
    evidence_refs: list[str] = Field(description="至少两个不同的候选资料 ref，例如 M1、M2；不填记忆 ID")
    keywords: set[str]
    poignancy: float = Field(ge=1, le=10)


class Insights(BaseModel):
    thoughts: list[Insight] = Field(max_length=3)


class Candidate(BaseModel):
    node_id: str
    similarity: float | None = None
    score: float = 0
    recency: float | None = None
    importance: float | None = None
    reason: str = "semantic"


def eligible(node: ConceptNode, nodes: dict[str, ConceptNode], now: datetime,
             visiting: frozenset[str] = frozenset()) -> bool:
    """失效证据会使派生认识失效，避免从 thought 绕过纠正和到期规则。"""
    if node.node_id in visiting or node.status == "superseded":
        return False
    if node.expiration is not None and node.expiration <= now:
        return False
    if node.type == "thought":
        return bool(node.filling) and all(
            key in nodes and eligible(nodes[key], nodes, now, visiting | {node.node_id})
            for key in node.filling
        )
    return True
