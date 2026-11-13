from datetime import datetime
from typing import Literal
from pydantic import Field
from ....common.models import Model


class MemoryNode(Model):
    """记忆内容与语义关系；不持有人物当前状态或本次情感反应。"""
    node_id: str
    character_id: str
    conversation_id: str
    type: Literal["chat", "event", "thought"]
    description: str = Field(min_length=1)
    created_at: datetime
    expires_at: datetime | None = None
    # 事实有效性不等于记忆清晰程度；淡忘不代表事实被纠正。
    validity: Literal["active", "superseded"] = "active"
    supersedes_id: str | None = None
    subject: str = "用户"
    predicate: str = "表示"
    object: str = ""
    importance: float = Field(default=5, ge=1, le=10)
    depth: int = Field(default=0, ge=0)
    keywords: list[str] = Field(default_factory=list)
    context: str = ""
    tags: list[str] = Field(default_factory=list)
    category: str = ""
    # 三类关系分开：原话来源、有方向的反思证据、无方向的普通关联。
    source_message_ids: list[str] = Field(default_factory=list)
    evidence_memory_ids: list[str] = Field(default_factory=list)
    related_memory_ids: list[str] = Field(default_factory=list)
    index_state: Literal["none", "pending", "ready", "failed"] = "pending"


class RetentionState(Model):
    """衰减强化插件的独立数据，不改变正文内容。"""
    initial_strength: float = Field(ge=0, le=1)
    strength_after_recall: float = Field(ge=0, le=1)
    stability_days: float = Field(gt=0)
    anchor_at: datetime
    recall_count: int = Field(default=0, ge=0)
    last_recalled_at: datetime | None = None


class MemoryDraft(Model):
    """模型提炼的新事件草稿；通过引用检查后才生成持久节点。"""
    description: str = Field(min_length=1, max_length=2000)
    subject: str
    predicate: str
    object: str
    importance: float = Field(ge=1, le=10)
    keywords: list[str]
    context: str
    tags: list[str]
    category: str
    related_memory_ids: list[str] = Field(default_factory=list)
    supersedes_id: str | None = None


class NeighborUpdate(Model):
    node_id: str
    context: str
    tags: list[str]


class Formation(Model):
    """一次调用同时整理新事件和有限邻居，避免逐节点反复请求模型。"""
    events: list[MemoryDraft] = Field(default_factory=list, max_length=3)
    neighbor_updates: list[NeighborUpdate] = Field(default_factory=list, max_length=5)


class Insight(Model):
    """反思产生的认识及其依据；不是用户亲口确认的事实。"""
    description: str = Field(min_length=1, max_length=2000)
    evidence_memory_ids: list[str] = Field(min_length=2)
    keywords: list[str]
    importance: float = Field(ge=1, le=10)


class Reflection(Model):
    thoughts: list[Insight] = Field(default_factory=list, max_length=2)
