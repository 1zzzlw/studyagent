"""v3：沿用原 v2/05 的按天衰减和间隔强化；不参与向量相似度计算。"""
import math
from datetime import datetime

from .models import ConceptNode


class EbbinghausMemoryEngine:
    def register(self, node: ConceptNode) -> None:
        initial = round(0.3 * node.attention + 0.3 * node.emotional_impact
                        + 0.4 * node.poignancy / 10, 3)
        node.initial_strength = initial
        node.strength_after_recall = initial
        node.stability_days = 1 + 89 * initial
        self.step(node, node.created)

    def strength(self, node: ConceptNode, now: datetime) -> float:
        days = max(0.0, (now - node.last_accessed).total_seconds() / 86400)
        return node.strength_after_recall * math.exp(-days / node.stability_days)

    def recall(self, node: ConceptNode, now: datetime) -> None:
        if node.status == "superseded":
            raise ValueError("不能强化已被纠正的旧认识")
        days = max(0.0, (now - node.last_accessed).total_seconds() / 86400)
        spacing = 1 - math.exp(-days / node.stability_days)
        node.stability_days *= 1 + spacing
        base = node.strength_after_recall
        node.strength_after_recall = base + 0.2 * spacing * (1 - base)
        node.last_accessed = now
        node.recall_count += 1
        self.step(node, now)

    def step(self, node: ConceptNode, now: datetime) -> None:
        if node.status != "superseded":
            value = self.strength(node, now)
            node.status = "active" if value > 0.6 else "fading" if value > 0.2 else "forgotten"

    def effective_strength(self, node, nodes, now, visiting=frozenset()):
        """反思不会把模糊的依据自动洗成清晰事实；取自身与证据强度的较小值。"""
        if node.node_id in visiting:
            return 0.0
        strength = self.strength(node, now)
        if node.type == "thought":
            sources = [self.effective_strength(nodes[key], nodes, now, visiting | {node.node_id})
                       for key in node.filling if key in nodes]
            return min([strength, *sources]) if sources else 0.0
        return strength
