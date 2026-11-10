"""记忆管理：节点写入、索引、关联、JSON 存档；衰减计算交给可选插件。"""

import json
from datetime import datetime, timedelta
from pathlib import Path

from engines import EbbinghausMemoryEngine
from memory_structures import ConceptNode


class AssociativeMemory:
    def __init__(self, engine: EbbinghausMemoryEngine | None = None):
        self.engine = engine
        self.id_to_node: dict[str, ConceptNode] = {}
        self.seq_event: list[ConceptNode] = []
        self.seq_thought: list[ConceptNode] = []
        self.seq_chat: list[ConceptNode] = []
        self.kw_to_event: dict[str, list[ConceptNode]] = {}
        self.kw_to_thought: dict[str, list[ConceptNode]] = {}
        self.kw_to_chat: dict[str, list[ConceptNode]] = {}
        self.kw_strength_event: dict[str, int] = {}
        self.kw_strength_thought: dict[str, int] = {}

    def add_event(self, **fields) -> ConceptNode:
        """加入事件；参数名对应 ConceptNode，ID、序号、深度由程序分配。"""
        return self._add_node("event", **fields)

    def add_thought(self, **fields) -> ConceptNode:
        """加入认识或想法；filling 中保存支持该想法的已有节点 ID。"""
        return self._add_node("thought", **fields)

    def add_chat(self, **fields) -> ConceptNode:
        """加入真实对话；filling 是 [(说话人, 原话), ...]。"""
        return self._add_node("chat", **fields)

    def _add_node(self, node_type: str, **fields) -> ConceptNode:
        filling = fields.get("filling", [])
        # 必须指向已存在的节点。新节点只引用旧节点，关联不会形成循环。
        if node_type != "chat":
            for node_id in filling:
                if node_id not in self.id_to_node:
                    raise ValueError(f"关联记忆不存在：{node_id}")
        old_id = fields.get("supersedes_id")
        if old_id:
            if old_id not in self.id_to_node:
                raise ValueError(f"被纠正的记忆不存在：{old_id}")
            old = self.id_to_node[old_id]
            if old.type == "chat" or old.status == "superseded":
                raise ValueError("只能纠正尚未被替代的事件或想法；历史对话原话保留")
        count = max((node.node_count for node in self.id_to_node.values()), default=0) + 1
        depth = 0
        if node_type == "thought":
            depth = 1 + max((self.id_to_node[key].depth for key in filling), default=0)
        node = ConceptNode(
            node_id=f"node_{count}", node_count=count,
            type_count=len(getattr(self, f"seq_{node_type}")) + 1,
            type=node_type, depth=depth, last_accessed=fields["created"], **fields,
        )
        if self.engine:
            self.engine.register(node)
        self._index(node)
        if old_id:
            self.id_to_node[old_id].status = "superseded"
        return node

    def _index(self, node: ConceptNode) -> None:
        """多个索引引用同一个节点对象；不会复制成几份独立记忆。"""
        self.id_to_node[node.node_id] = node
        getattr(self, f"seq_{node.type}").insert(0, node)
        keyword_index = getattr(self, f"kw_to_{node.type}")
        for keyword in {value.strip().lower() for value in node.keywords if value.strip()}:
            keyword_index.setdefault(keyword, []).insert(0, node)
            if node.type != "chat" and f"{node.predicate} {node.object}" != "is idle":
                counts = getattr(self, f"kw_strength_{node.type}")
                counts[keyword] = counts.get(keyword, 0) + 1

    def retrieve_relevant_events(self, *keywords: str) -> list[ConceptNode]:
        return self._by_keywords(self.kw_to_event, keywords)

    def retrieve_relevant_thoughts(self, *keywords: str) -> list[ConceptNode]:
        return self._by_keywords(self.kw_to_thought, keywords)

    def _by_keywords(self, index, keywords) -> list[ConceptNode]:
        nodes = {node.node_id: node for keyword in keywords
                 for node in index.get(keyword.strip().lower(), [])}
        return sorted(nodes.values(), key=lambda node: node.node_count, reverse=True)

    def get_last_chat(self, person_name: str) -> ConceptNode | None:
        nodes = self.kw_to_chat.get(person_name.strip().lower(), [])
        return nodes[0] if nodes else None

    def recent_nodes(self, now: datetime, limit: int = 8) -> list[ConceptNode]:
        """本版只按写入顺序取最近几条上下文；不做向量检索，也不按强度排序。"""
        self.refresh(now)
        nodes = [node for node in self.id_to_node.values()
                 if node.status != "superseded"
                 and (node.expiration is None or node.expiration > now)]
        return sorted(nodes, key=lambda node: node.node_count, reverse=True)[:limit]

    def refresh(self, now: datetime) -> None:
        if self.engine:
            for node in self.id_to_node.values():
                self.engine.step(node, now)

    def recall(self, node_ids: list[str], now: datetime) -> None:
        # 一轮使用同一节点多次，只计一次；取候选和查看记忆不走此方法。
        nodes = [self.id_to_node[key] for key in dict.fromkeys(node_ids)]
        if any(node.status == "superseded" or
               (node.expiration is not None and node.expiration <= now) for node in nodes):
            raise ValueError("不能回忆强化已被纠正或已到期的记忆")
        for node in nodes:
            if self.engine:
                self.engine.recall(node, now)
            else:
                node.last_accessed = now
                node.recall_count += 1

    def elapse(self, days: float, now: datetime) -> None:
        """沿用旧 Demo：将已有记忆的时间一起前移，实际时钟不变。"""
        delta = timedelta(days=days)
        if delta.total_seconds() <= 0:
            raise ValueError("经过天数必须大于 0")
        # 先算完，时间越界时不留下只移动了一部分节点的存档。
        shifted = [(node, node.created - delta, node.last_accessed - delta,
                    node.expiration - delta if node.expiration is not None else None)
                   for node in self.id_to_node.values()]
        for node, created, accessed, expiration in shifted:
            node.created = created
            node.last_accessed = accessed
            node.expiration = expiration
        self.refresh(now)

    def save(self, path: Path) -> None:
        """独立 nodes.json 存档；其余索引可以从节点重建，不重复持久化。"""
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(
            {key: node.model_dump(mode="json") for key, node in self.id_to_node.items()},
            ensure_ascii=False, indent=2,
        ), encoding="utf-8")
        temporary.replace(path)

    def load(self, path: Path) -> None:
        """只加载本版存档；加载时不调用 register，保留已有强度与回忆次数。"""
        if not path.exists():
            return
        if self.id_to_node:
            raise ValueError("请在空记忆库上加载存档，避免重复建立索引")
        records = json.loads(path.read_text(encoding="utf-8"))
        nodes = [ConceptNode.model_validate(record) for record in records.values()]
        for key, node in zip(records, nodes, strict=True):
            if key != node.node_id:
                raise ValueError("存档键与节点 ID 不一致")
        for node in sorted(nodes, key=lambda value: value.node_count):
            self._index(node)
