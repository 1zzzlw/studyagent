"""沿用 Generative Agents 的记忆节点字段，补充 05 的衰减强化字段。"""

from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator


class ConceptNode(BaseModel):
    """一条事件、想法或聊天记录。字段只是数据，计算规则在引擎里。"""

    model_config = ConfigDict(validate_assignment=True)

    # 以下沿用参考项目的命名。两个 count 是写入序号，不是回忆次数。
    node_id: str = Field(description="唯一编号，例如 node_1")
    node_count: int = Field(ge=1, description="全部记忆中的写入序号")
    type_count: int = Field(ge=1, description="同类记忆中的写入序号")
    type: Literal["event", "thought", "chat"]
    depth: int = Field(default=0, ge=0, description="推导层次：事件为 0，想法按证据递增")
    created: AwareDatetime = Field(description="形成记忆的时间，使用带时区的 UTC 时间")
    expiration: AwareDatetime | None = Field(default=None, description="到期时间；None 表示未设期限")
    # 本版仅在确认使用旧记忆时更新；普通查看、取候选不会更新。
    last_accessed: AwareDatetime = Field(description="最近确认回忆时间，创建时等于 created")
    subject: str = Field(description="主语：谁")
    predicate: str = Field(description="谓语：做了什么")
    object: str = Field(description="宾语：对象是什么")
    description: str = Field(min_length=1, description="独立可理解的记忆正文")
    embedding_key: str | None = Field(default=None, description="保留原字段；本版不用向量，保持 None")
    poignancy: float = Field(ge=1, le=10, description="重要性，沿用参考项目的 1～10 分")
    keywords: set[str] = Field(default_factory=set, description="供关键词索引使用")
    # event/thought 保存关联节点 ID；chat 保存真实的 (说话人, 原话)。
    filling: list[str] | list[tuple[str, str]] = Field(default_factory=list)

    # 以下补充自 05：attention / emotional_impact 也保留，方便追溯初始评分。
    source_observation_id: str | None = Field(default=None, description="本轮交流的来源编号")
    attention: float = Field(default=1.0, ge=0, le=1)
    emotional_impact: float = Field(default=0.0, ge=0, le=1)
    initial_strength: float = Field(default=1.0, ge=0, le=1)
    strength_after_recall: float = Field(default=1.0, ge=0, le=1)
    stability_days: float = Field(default=30.0, gt=0)
    recall_count: int = Field(default=0, ge=0, description="成功采用旧记忆的累计次数")
    status: Literal["active", "fading", "forgotten", "superseded"] = "active"
    supersedes_id: str | None = Field(default=None, description="本条明确纠正的旧认识 ID")

    @model_validator(mode="after")
    def check_filling(self):
        """沿用 filling 的两种用途，但避免把对话原文当成证据 ID。"""
        if self.type == "chat":
            if any(isinstance(value, str) for value in self.filling):
                raise ValueError("chat 的 filling 应为 [(说话人, 原话), ...]")
        elif any(not isinstance(value, str) for value in self.filling):
            raise ValueError("event/thought 的 filling 应为关联节点 ID 列表")
        return self

    def spo_summary(self) -> tuple[str, str, str]:
        return self.subject, self.predicate, self.object
