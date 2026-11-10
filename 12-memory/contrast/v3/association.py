"""A-Mem 思路：候选邻居 -> 语义描述/链接决策 -> 按真实 ID 更新并立即持久化。"""
from .models import Candidate, NoteEvolution, eligible


def evolve(runtime, node, report=lambda message: None):
    report(f"关联：为 {node.node_id} 查找候选邻居")
    candidates = runtime.store.search(node.description, runtime.now, limit=5, exclude=[node.node_id])
    nodes = runtime.store.nodes
    neighbors = {item.node_id: nodes[item.node_id] for item in candidates}
    report(f"关联：整理 {node.node_id}，等待文字模型")
    result = runtime.gateway.ask(
        NoteEvolution,
        "为本条记忆生成关键词、简短context、分类tags和category。"
        "从候选邻居中选择真正相关的记忆ID放入links；相似词不一定代表同一事件。"
        "必要时仅更新邻居的context和tags，不能改变事实正文、时间、强度和纠正关系。"
        "context必须保留条件、不确定性和人物区别，不把不同人的事情合并。"
        "links和neighbor_updates.node_id只能来自候选邻居真实ID，不使用序号或自造ID。",
        {"当前记忆": runtime.context_node(node, nodes),
         "候选邻居": [runtime.context_node(item, nodes) for item in neighbors.values()]},
        "整理记忆语义说明并维护关联",
    )
    if not set(result.links).issubset(neighbors):
        raise ValueError("关联决策引用了未提供的邻居 ID")
    ids = [update.node_id for update in result.neighbor_updates]
    if len(set(ids)) != len(ids) or not set(ids).issubset(neighbors):
        raise ValueError("邻居更新目标无效或重复")
    # 整个输出校验完成后再改字段；不触碰 description 和衰减字段。
    node.evolution_history.append({"at": runtime.now.isoformat(), "source": node.node_id,
                                   "old_context": node.context, "new_context": result.context,
                                   "old_tags": node.tags, "new_tags": result.tags})
    node.keywords = result.keywords
    node.context, node.tags, node.category = result.context, result.tags, result.category
    node.links = list(dict.fromkeys([*node.links, *result.links]))
    node.association_ready = True
    changed = {node.node_id: node}
    for key in result.links:
        neighbor = neighbors[key]
        # 普通“相关”采用双向链接，避免只有新记忆能找旧记忆。
        neighbor.links = list(dict.fromkeys([*neighbor.links, node.node_id]))
        changed[key] = neighbor
    for update in result.neighbor_updates:
        neighbor = neighbors[update.node_id]
        neighbor.evolution_history.append({"at": runtime.now.isoformat(), "source": node.node_id,
                                          "old_context": neighbor.context, "new_context": update.context,
                                          "old_tags": neighbor.tags, "new_tags": update.tags})
        neighbor.context, neighbor.tags = update.context, update.tags
        changed[neighbor.node_id] = neighbor
    report(f"关联：保存语义说明与 {len(result.links)} 条链接")
    runtime.store.update(changed.values())


def expand_links(store, ranked, now, limit=8, include_evidence=False):
    """给扩展预留最多3个位置，避免先塞满直接命中再截断全部邻居。"""
    if not ranked:
        return []
    nodes = store.nodes
    result = list(ranked[:max(1, limit - 3)])
    seen = {item.node_id for item in result}
    by_id = {item.node_id: item for item in ranked}
    for parent in list(result):
        node = nodes[parent.node_id]
        targets = [(key, "link") for key in node.links]
        if include_evidence and node.type == "thought":
            targets = [(key, "evidence") for key in node.filling] + targets
        for key, relation in targets:
            child = nodes.get(key)
            if len(result) >= limit:
                break
            if key in seen or child is None or child.type == "chat" or not eligible(child, nodes, now):
                continue
            candidate = by_id.get(key, Candidate(node_id=key, score=parent.score))
            result.append(candidate.model_copy(update={"reason": f"{relation}:{parent.node_id}"}))
            seen.add(key)
    for item in ranked:
        if len(result) >= limit:
            break
        if item.node_id not in seen:
            result.append(item)
            seen.add(item.node_id)
    return result
