"""GA 事件/反思/证据 + A-Mem 语义整理/邻居维护 + 可替换保留引擎。"""
import math
from ...memory.domain.models import MemoryNode, Formation, Reflection
from ...memory.engines.ebbinghaus import EbbinghausMemoryEngine
from ....common.models import new_id


class MemoryService:
    def __init__(self, repository, index, model, engine=None):
        self.repo, self.index, self.model = repository, index, model
        self.engine = engine or EbbinghausMemoryEngine()

    def eligible(self, node, nodes, now, visiting=frozenset()):
        if node.node_id in visiting or node.validity != "active":
            return False
        if node.expires_at is not None and node.expires_at <= now:
            return False
        if node.type == "thought":
            return bool(node.evidence_memory_ids) and all(
                key in nodes and self.eligible(nodes[key], nodes, now, visiting | {node.node_id})
                for key in node.evidence_memory_ids)
        return True

    def effective_strength(self, node, nodes, retentions, now, visiting=frozenset()):
        if not self.eligible(node, nodes, now) or node.node_id in visiting:
            return 0.0
        value = self.engine.strength(retentions[node.node_id], now)
        if node.type == "thought":
            values = [self.effective_strength(nodes[key], nodes, retentions, now,
                                              visiting | {node.node_id}) for key in node.evidence_memory_ids]
            return min([value, *values])
        return value

    def views(self, now):
        nodes, retentions = self.repo.nodes(), self.repo.retentions()
        processing = self.repo.processing()
        result = []
        for node in nodes.values():
            strength = self.effective_strength(node, nodes, retentions, now)
            value = node.model_dump(mode="json")
            value.update(current_strength=round(strength, 4),
                         clarity="清晰" if strength > 0.6 else "模糊" if strength > 0.2 else "淡忘",
                         eligible=self.eligible(node, nodes, now),
                         retention=retentions[node.node_id].model_dump(mode="json"),
                         processing=processing[node.node_id])
            result.append(value)
        return result

    def recall(self, query, now, report):
        nodes, retentions = self.repo.nodes(), self.repo.retentions()
        hits = self.index.search(query, self.repo.character_id)
        ranked = []
        for key, similarity in hits:
            node = nodes.get(key)
            if not node or node.type == "chat" or not self.eligible(node, nodes, now):
                continue
            days = max(0, (now - retentions[key].anchor_at).total_seconds() / 86400)
            # 强度与相关性分开：借鉴 GA 的多因素排序，时间项仅是近期性。
            score = 0.75 * max(0, similarity) + 0.15 * node.importance / 10 + 0.1 * math.exp(-days / 30)
            ranked.append((score, key, similarity))
        ranked.sort(reverse=True)
        selected = {key: {"similarity": sim, "reason": "semantic"}
                    for _, key, sim in ranked[:5]}
        for key in list(selected):
            node = nodes[key]
            for target in node.evidence_memory_ids + node.related_memory_ids:
                if len(selected) >= 8:
                    break
                if target in nodes and nodes[target].type != "chat" and self.eligible(nodes[target], nodes, now):
                    selected.setdefault(target, {"similarity": None, "reason": f"related_to:{key}"})
        view = {value["node_id"]: value for value in self.views(now)}
        recalled = [{**view[key], **meta} for key, meta in selected.items()]
        report("retrieval", f"检索完成：本轮提供 {len(recalled)} 条长期回忆",
               {"query": query, "candidates": recalled})
        return recalled

    def index_nodes(self, nodes, report):
        nodes = [node for node in nodes if node.type != "chat"]
        if not nodes:
            return
        ids = [node.node_id for node in nodes]
        self.repo.index_state(ids, "pending")
        report("indexing", f"向量化并更新 {len(ids)} 条记忆", {"memory_ids": ids})
        try:
            self.index.upsert(nodes)
        except Exception:
            self.repo.index_state(ids, "failed")
            raise
        self.repo.index_state(ids, "ready")
        report("indexed", "Chroma 索引已更新；正文与证据保存在 SQLite", {"memory_ids": ids})

    def record_usage(self, used_ids, allowed_ids, now, report):
        if not set(used_ids).issubset(allowed_ids):
            raise ValueError("实际回忆 ID 不在本轮允许范围")
        nodes, states = self.repo.nodes(), self.repo.retentions()
        for key in dict.fromkeys(used_ids):
            if not self.eligible(nodes[key], nodes, now):
                continue
            before = states[key]
            after = self.engine.reinforce(before, now)
            self.repo.save_retention(key, after)
            report("reinforcement", "实际采用的记忆已强化", {
                "memory_id": key, "before": before.model_dump(mode="json"),
                "after": after.model_dump(mode="json")})

    def remember(self, conversation_id, users, assistant, attention, impact, recalled, now, report):
        source_ids = [user["message_id"] for user in users]
        user_text = "\n".join(user["content"] for user in users)
        chat = MemoryNode(
            node_id=new_id("chat"), character_id=self.repo.character_id,
            conversation_id=conversation_id, type="chat", description="交流：" + user_text[:100],
            created_at=now, source_message_ids=source_ids + ([assistant["message_id"]] if assistant else []),
            index_state="none")
        self.repo.add_memory(chat, self.engine.initialize(1, 0, 10, now))
        report("chat_saved", "原话已通过消息 ID 关联到 chat 节点", {"memory": chat.model_dump(mode="json")})
        neighbors = {item["node_id"]: item for item in recalled}
        formation = self.model.ask(
            Formation,
            "从真实交流提炼最多3条值得长期保存的新事件，允许 events 为空。"
            "events 数组中直接放事件对象，neighbor_updates 数组中直接放邻居更新对象。"
            '没有新事件且无需更新邻居时返回 {"events":[],"neighbor_updates":[]}。'
            "先区分用户与角色，保留人称、时间条件、不确定性；计划不能写成已发生。"
            "只询问旧事不是新事实；角色猜测或建议不能证明用户事实。"
            "实际角色回复为null表示本批没有发言，不可补造角色回复。"
            "注意力较低时保留主线和有用细节，不编造原话里没有的信息。"
            "同时借鉴笔记关联方式，给新事件生成 context、tags、keywords、category，"
            "related_memory_ids 只能来自候选邻居。必要时更新邻居context/tags，不能改事实正文。"
            "supersedes_id 只在用户明确纠正错误认识时填写；正常随时间变化不意味着旧事实错误。",
            {"观察时间": now.isoformat(), "当前时区": "Asia/Shanghai（北京时间）",
             "实际用户原话": user_text, "实际角色回复": assistant["content"] if assistant else None,
             "原话来源": [{"message_id": user["message_id"], "created_at": user["created_at"]} for user in users],
             "形成时注意力": attention.model_dump(), "本次情感冲击": impact,
             "候选邻居": list(neighbors.values())}, purpose="memory_formation",
        )
        targets = [update.node_id for update in formation.neighbor_updates]
        if len(set(targets)) != len(targets) or not set(targets).issubset(neighbors):
            raise ValueError("关联维护引用了无效或重复邻居")
        corrected = set()
        for draft in formation.events:
            if not set(draft.related_memory_ids).issubset(neighbors):
                raise ValueError("新记忆引用了未提供的关联目标")
            if draft.supersedes_id:
                if draft.supersedes_id not in neighbors or draft.supersedes_id in corrected:
                    raise ValueError("纠正引用无效或重复")
                corrected.add(draft.supersedes_id)
        created = []
        for draft in formation.events:
            value = draft.model_dump()
            node = MemoryNode(node_id=new_id("event"), character_id=self.repo.character_id,
                              conversation_id=conversation_id, type="event", created_at=now,
                              source_message_ids=source_ids, **value)
            retention = self.engine.initialize(attention.attention, impact, node.importance, now)
            self.repo.add_memory(node, retention)
            self.repo.mark_processed([node.node_id], "association_ready")
            created.append(node)
            report("memory_created", "事件记忆已保存；关联与证据分别记录", {
                "memory": node.model_dump(mode="json"),
                "retention": retention.model_dump(mode="json")})
        changed = []
        for update in formation.neighbor_updates:
            before = neighbors[update.node_id]
            self.repo.update_semantics(update.node_id, update.context, update.tags)
            report("association_updated", "旧记忆的背景和标签已更新，正文保留", {
                "memory_id": update.node_id,
                "before": {"context": before["context"], "tags": before["tags"]},
                "after": {"context": update.context, "tags": update.tags}})
            changed.append(update.node_id)
        current = self.repo.nodes()
        self.index_nodes([*created, *(current[key] for key in changed)], report)
        self.reflect(conversation_id, created, attention.attention, impact, now, report)
        if not created:
            report("formation_empty", "本轮没有形成新的事件记忆", {})

    def reflect(self, conversation_id, new_nodes, attention, impact, now, report):
        nodes, processing = self.repo.nodes(), self.repo.processing()
        pending = [node for node in nodes.values() if node.type == "event"
                   and not processing[node.node_id]["reflected"] and self.eligible(node, nodes, now)][:12]
        observations = {key for node in pending for key in node.source_message_ids}
        importance = sum(node.importance for node in pending)
        if not new_nodes or len(observations) < 2 or (len(pending) < 3 and importance < 15):
            report("reflection_waiting", "反思继续积累，尚未达到触发条件", {
                "pending_events": len(pending), "importance": importance,
                "distinct_observations": len(observations),
                "rule": "本轮有新事件，至少两次观察，且事件>=3或重要性>=15"})
            return
        candidates = {node.node_id: node for node in pending}
        result = self.model.ask(
            Reflection,
            "结合候选经历形成最多2条有价值的新认识，可返回空 thoughts。"
            "每条至少引用两个不同的真实候选记忆ID，不填消息ID。"
            "不能仅复述一条事实，不臆测未提供的隐私或动机，推测要保留可能性。"
            "不要重复已有认识，不把角色推断当成用户确认。",
            {"当前时间": now.isoformat(), "当前时区": "Asia/Shanghai（北京时间）",
             "候选经历": [node.model_dump(mode="json") for node in pending],
             "已有认识": [node.description for node in nodes.values() if node.type == "thought"][-10:]},
            purpose="reflection",
        )
        for insight in result.thoughts:
            refs = list(dict.fromkeys(insight.evidence_memory_ids))
            if len(refs) < 2 or not set(refs).issubset(candidates):
                raise ValueError("反思缺少两个不同的有效证据 ID")
        saved = []
        for insight in result.thoughts:
            if any(node.type == "thought" and node.description == insight.description for node in nodes.values()):
                continue
            refs = list(dict.fromkeys(insight.evidence_memory_ids))
            source_ids = list(dict.fromkeys(key for ref in refs for key in candidates[ref].source_message_ids))
            node = MemoryNode(node_id=new_id("thought"), character_id=self.repo.character_id,
                              conversation_id=conversation_id, type="thought", created_at=now,
                              description=insight.description, importance=insight.importance,
                              keywords=insight.keywords, context="根据多次交流归纳的新认识",
                              category="反思", subject="小忆", predicate="认为", object="基于经历的理解",
                              evidence_memory_ids=refs, source_message_ids=source_ids,
                              depth=1 + max(candidates[key].depth for key in refs))
            self.repo.add_memory(node, self.engine.initialize(attention, impact, node.importance, now))
            self.repo.mark_processed([node.node_id], "reflected")
            saved.append(node)
            report("thought_created", "反思形成新认识，并保存有向证据", {"memory": node.model_dump(mode="json")})
        self.index_nodes(saved, report)
        self.repo.mark_processed(list(candidates), "reflected")
        report("reflection_complete", f"本轮反思完成，新增 {len(saved)} 条认识",
               {"memory_ids": [node.node_id for node in saved]})
