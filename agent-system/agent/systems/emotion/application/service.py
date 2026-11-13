from ..domain.models import EmotionAppraisal, EmotionState
from ..engines.dynamics import PERSONALITY, apply, recover


class EmotionService:
    def __init__(self, repository, model):
        self.repository, self.model = repository, model

    def snapshot(self, now):
        payload = self.repository.get_snapshot("emotion")
        state = EmotionState.model_validate(payload) if payload else EmotionState(updated_at=now)
        return recover(state, now)

    def appraise(self, message, state, memories, now):
        # 只计算候选状态；协调层确认这一批仍有效后才提交，避免连发时重复累加。
        before = self.snapshot(now)
        appraisal = self.model.ask(
            EmotionAppraisal,
            "评价角色读到消息后的反应，reaction 是角色自身的目标情绪，不是用户情绪的复制。"
            "结合当前处境、人格、原有情绪和有来源的经历；不要把用户的疲惫当作角色疲惫。"
            "emotional_impact 表示这一次内容带来的冲击，不等于当前最强情绪。"
            "reason 是可读的简短评价依据，不输出隐藏思维过程。",
            {"角色名": self.repository.character_name, "人格参数": PERSONALITY,
             "当前时间": now.isoformat(), "当前时区": "Asia/Shanghai（北京时间）",
             "人物状态": state.model_dump(mode="json"),
             "原有情绪": before.model_dump(mode="json"), "相关经历": memories,
             "用户原话": message},
            purpose="emotion",
        )
        after = apply(before, appraisal.reaction, now)
        return appraisal, before, after
