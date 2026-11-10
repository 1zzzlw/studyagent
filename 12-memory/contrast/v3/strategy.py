"""借鉴 GA new_retrieve：语义候选 -> 相关性、重要性、近期性归一化重排。"""
from .models import Candidate
from .association import expand_links


def normalize(values):
    if not values:
        return {}
    low, high = min(values.values()), max(values.values())
    return {key: (value - low) / (high - low) if high > low else 0.5
            for key, value in values.items()}


def retrieve(store, query, now, limit=8):
    # 与另外两版相同：先由 Chroma 召回最多 30 条，再选最多 8 条回答上下文。
    nodes = store.nodes
    candidates = store.search(query, now, limit=30)
    ordered = sorted(candidates, key=lambda item: (-nodes[item.node_id].last_accessed.timestamp(), item.node_id))
    # 近期记忆分数更高，修正原仓库排序与指数方向相反的问题。
    recency = normalize({item.node_id: 0.99 ** rank for rank, item in enumerate(ordered)})
    importance = normalize({item.node_id: nodes[item.node_id].poignancy for item in candidates})
    relevance = normalize({item.node_id: item.similarity for item in candidates})
    ranked = [Candidate(
        node_id=item.node_id, similarity=item.similarity,
        recency=recency[item.node_id], importance=importance[item.node_id],
        score=0.5 * recency[item.node_id] + 3 * relevance[item.node_id] + 2 * importance[item.node_id],
        reason="ga_rank",
    ) for item in candidates]
    ranked = sorted(ranked, key=lambda item: (-item.score, item.node_id))
    return expand_links(store, ranked, now, limit, include_evidence=True)
