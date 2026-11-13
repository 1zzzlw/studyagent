from datetime import datetime
from ..domain.models import CharacterState
from ..engines.attention import evaluate_attention

class CharacterStateService:
    def __init__(self, repository):
        self.repository = repository

    def snapshot(self, now: datetime) -> CharacterState:
        payload = self.repository.get_snapshot("character")
        state = CharacterState.model_validate(payload) if payload else CharacterState(updated_at=now)
        # 固定活动由用户显式修改；不从用户说“我累了”推断角色精力。
        return state

    def update(self, changes: dict, now: datetime) -> CharacterState:
        state = CharacterState.model_validate({
            **self.snapshot(now).model_dump(), **changes, "updated_at": now,
        })
        self.repository.save_snapshot("character", state.model_dump(mode="json"))
        return state

    def appraise(self, state, emotion_values):
        return evaluate_attention(state, emotion_values)
