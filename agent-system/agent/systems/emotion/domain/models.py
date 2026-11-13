from datetime import datetime
from pydantic import Field
from ....common.models import Model


class EmotionVector(Model):
    joy: float = Field(default=0.15, ge=0, le=1)
    sadness: float = Field(default=0.15, ge=0, le=1)
    anger: float = Field(default=0.15, ge=0, le=1)
    fear: float = Field(default=0.15, ge=0, le=1)
    trust: float = Field(default=0.15, ge=0, le=1)
    curiosity: float = Field(default=0.15, ge=0, le=1)


class EmotionState(Model):
    values: EmotionVector = Field(default_factory=EmotionVector)
    baseline: float = 0.1
    updated_at: datetime


class EmotionAppraisal(Model):
    reaction: EmotionVector
    emotional_impact: float = Field(ge=0, le=1)
    reason: str = Field(min_length=1, max_length=500)
