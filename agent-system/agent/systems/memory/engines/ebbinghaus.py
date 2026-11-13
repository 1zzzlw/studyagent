"""保留状态是记忆内部组件；注意力和情感冲击只作为初始化输入。"""
import math
from ..domain.models import RetentionState


class EbbinghausMemoryEngine:
    def initialize(self, attention, emotional_impact, importance, now):
        value = round(0.3 * attention + 0.3 * emotional_impact + 0.4 * importance / 10, 3)
        return RetentionState(initial_strength=value, strength_after_recall=value,
                              stability_days=1 + 89 * value, anchor_at=now)

    def strength(self, retention, now):
        days = max(0.0, (now - retention.anchor_at).total_seconds() / 86400)
        return retention.strength_after_recall * math.exp(-days / retention.stability_days)

    def reinforce(self, retention, now):
        days = max(0.0, (now - retention.anchor_at).total_seconds() / 86400)
        spacing = 1 - math.exp(-days / retention.stability_days)
        result = retention.model_copy(deep=True)
        result.stability_days *= 1 + spacing
        result.strength_after_recall += 0.2 * spacing * (1 - result.strength_after_recall)
        result.anchor_at = now
        result.last_recalled_at = now
        result.recall_count += 1
        return result
