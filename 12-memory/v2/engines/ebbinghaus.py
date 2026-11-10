"""保留 05 的按天衰减、间隔强化规则；不负责存储、检索或调用模型。"""

import math
from datetime import datetime

from memory_structures import ConceptNode


class EbbinghausMemoryEngine:
    """插件只操作传入节点的强度字段，不拥有另一份记忆仓库。"""

    def register(self, node: ConceptNode) -> None:
        """只在新记忆形成时初始化；从存档恢复时不能重新初始化。"""
        # poignancy 为 1～10，先归一化再沿用 05 的三个评分权重。
        initial = round(
            0.3 * node.attention
            + 0.3 * node.emotional_impact
            + 0.4 * (node.poignancy / 10), 3,
        )
        node.initial_strength = initial
        node.strength_after_recall = initial
        node.stability_days = 1 + 89 * initial
        self.step(node, node.created)

    def get_current_strength(self, node: ConceptNode, now: datetime) -> float:
        """当前强度 = 上次基准强度 × exp(-经过天数 / 稳定性)。不修改节点。"""
        days = max(0.0, (now - node.last_accessed).total_seconds() / 86400)
        return node.strength_after_recall * math.exp(-days / node.stability_days)

    def recall(self, node: ConceptNode, now: datetime) -> None:
        """确认实际采用后才强化；保留 05 的间隔系数，避免连续查看不断刷强度。"""
        if node.status == "superseded":
            raise ValueError("被纠正的旧认识不能作为当前认识强化")
        days = max(0.0, (now - node.last_accessed).total_seconds() / 86400)
        spacing = 1 - math.exp(-days / node.stability_days)
        node.stability_days *= 1 + spacing
        base = node.strength_after_recall
        node.strength_after_recall = base + 0.2 * spacing * (1 - base)
        node.last_accessed = now
        node.recall_count += 1
        self.step(node, now)

    def step(self, node: ConceptNode, now: datetime) -> None:
        """只更新清晰程度；淡忘不会删除正文，也不会清除关联。"""
        if node.status == "superseded":
            return
        strength = self.get_current_strength(node, now)
        node.status = "active" if strength > 0.6 else "fading" if strength > 0.2 else "forgotten"
