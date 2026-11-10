"""A-Mem process_memory：新笔记与邻居比较，建立链接或更新邻居描述。"""
from .models import NoteAnalysis, NoteEvolution


def analyze_content(runtime, content):
    return runtime.gateway.ask(
        NoteAnalysis,
        "分析这条笔记的关键词、简短背景 context 和分类 tags。"
        "保留人物、条件和不确定性，不把问题、邀请或猜测写成已确认事实。"
        "只分析用户提供的内容，不添加未提供的经历。",
        {}, content,
    )


def process_memory(runtime, note, report=print):
    """strengthen 是 A-Mem 的关联动作，既不计算强度，也不生成新 thought。"""
    report("A-Mem：为新笔记检索邻居")
    candidates = runtime.store.search(note.content, limit=5)
    if not candidates:
        return
    notes = runtime.store.nodes
    neighbors = {item.id: notes[item.id] for item in candidates}
    report("A-Mem：判断关联与邻居描述是否需要演化，等待文字模型")
    decision = runtime.gateway.ask(
        NoteEvolution,
        "根据新笔记和候选邻居判断是否需要演化，should_evolve 可以为 false。"
        "strengthen 表示给新笔记建立相关 links 并设置 tags_to_update；"
        "update_neighbor 表示修改特定邻居的 context 和 tags。"
        "suggested_connections 和 neighbor_updates.id 只能使用提供的真实邻居 ID。"
        "不同人物、不同事件不能因为词语相似就合并。不改写正文，也不把推测当事实。"
        "不执行的动作使用空列表；邻居更新按 ID 指定。",
        {"new_note": runtime.context_node(note),
         "neighbors": [runtime.context_node(item) for item in neighbors.values()]},
        "判断本次笔记演化动作",
    )
    if not decision.should_evolve:
        return
    ids = [update.id for update in decision.neighbor_updates]
    if not set(decision.suggested_connections).issubset(neighbors):
        raise ValueError("关联决策引用了无效邻居 ID")
    if len(ids) != len(set(ids)) or not set(ids).issubset(neighbors):
        raise ValueError("邻居更新目标无效或重复")
    changed = []
    if "strengthen" in decision.actions:
        note.links = list(dict.fromkeys(decision.suggested_connections))
        note.tags = decision.tags_to_update
        note.evolution_history.append({"at": runtime.now.isoformat(), "action": "strengthen",
                                       "links": note.links, "tags": note.tags})
    if "update_neighbor" in decision.actions:
        for update in decision.neighbor_updates:
            neighbor = neighbors[update.id]
            neighbor.evolution_history.append({"at": runtime.now.isoformat(), "source": note.id,
                                              "old_context": neighbor.context, "new_context": update.context,
                                              "old_tags": neighbor.tags, "new_tags": update.tags})
            neighbor.context, neighbor.tags = update.context, update.tags
            changed.append(neighbor)
    # 新笔记由调用方 add；邻居语义更新立即持久化，不重新向量化。
    runtime.store.update(changed)
    report(f"A-Mem：建立 {len(note.links)} 条关联，更新 {len(changed)} 条邻居描述")
