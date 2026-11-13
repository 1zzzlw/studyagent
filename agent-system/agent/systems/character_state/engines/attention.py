"""初版工程规则；仅影响本次注意力，不冒充心理学定律。"""
from ..domain.models import AttentionAppraisal, CharacterState


def evaluate_attention(state: CharacterState, emotions: dict[str, float]) -> AttentionAppraisal:
    distraction = 0.2 * emotions["fear"] + 0.15 * emotions["sadness"]
    attention = max(0.05, min(1.0, (0.3 + 0.7 * state.energy)
                              * (1 - 0.6 * state.busyness) * (1 - distraction)))
    return AttentionAppraisal(
        attention=round(attention, 3),
        reason="结合角色精力、忙碌程度与本轮担忧/悲伤计算；不是用户的状态。",
    )
