from datetime import datetime
from pydantic import Field
from ....common.models import Model

class CharacterState(Model):
    energy: float = Field(default=0.7, ge=0, le=1)
    busyness: float = Field(default=0.1, ge=0, le=1)
    activity: str = Field(default="休息时聊天", min_length=1, max_length=100)
    attention_focus: str = Field(default="当前对话", min_length=1, max_length=100)
    environment: str = Field(default="安静的房间", min_length=1, max_length=200)
    current_intent: str = Field(default="理解对方并自然交流", min_length=1, max_length=200)
    updated_at: datetime

class AttentionAppraisal(Model):
    attention: float = Field(ge=0, le=1)
    reason: str
