"""线程安全的独立Chroma存档；网络向量请求不占写锁，读取使用完整快照。"""
from datetime import datetime
from pathlib import Path
from threading import RLock

from .models import Candidate, ConceptNode, eligible


class ReadView:
    def __init__(self, store, nodes):
        self.store, self.nodes = store, nodes

    def search(self, query, now, limit=30, exclude=()):
        return self.store.search(query, now, limit, exclude, snapshot=self.nodes)


class ChromaStore:
    def __init__(self, path: Path, version: str, embeddings, signature: str, client=None):
        if client is None:
            import chromadb
            client = chromadb.PersistentClient(path=str(path))
        self.client, self.embeddings, self.signature = client, embeddings, signature
        self.lock = RLock()
        self.name = f"contrast_{version}"
        names = [getattr(item, "name", item) for item in client.list_collections()]
        if self.name in names:
            self.collection = client.get_collection(name=self.name, embedding_function=None)
        else:
            self.collection = client.get_or_create_collection(
                name=self.name, embedding_function=None,
                metadata={"hnsw:space": "cosine", "embedding_signature": signature},
            )
        if self.collection.metadata.get("embedding_signature") != signature:
            raise ValueError("该版本的向量模型配置已变化；请使用新的实验目录，不混用已有向量。")
        self._nodes = {}
        self.reload()

    @property
    def nodes(self):
        # 调用方拿到副本，不能在写回之前修改其他线程可见的对象。
        with self.lock:
            return {key: node.model_copy(deep=True) for key, node in self._nodes.items()}

    def view(self):
        return ReadView(self, self.nodes)

    def reload(self):
        with self.lock:
            records = self.collection.get(include=["metadatas"])
            nodes = {}
            for key, metadata in zip(records["ids"], records["metadatas"], strict=True):
                node = ConceptNode.model_validate_json(metadata["payload"])
                if key != node.node_id:
                    raise ValueError("Chroma ID 与记忆节点 ID 不一致")
                nodes[key] = node
            self._nodes = nodes

    @staticmethod
    def metadata(node):
        return {"node_type": node.type, "status": node.status, "payload": node.model_dump_json()}

    def add(self, nodes: list[ConceptNode], vectors=None):
        if not nodes:
            return
        ids = [node.node_id for node in nodes]
        if len(set(ids)) != len(ids):
            raise ValueError("新节点 ID 重复")
        # 向量网络请求放在锁外，等待 API 时，网页仍能读取已提交记忆。
        if vectors is None:
            vectors = self.embeddings.embed_documents([node.description for node in nodes])
        if len(vectors) != len(nodes):
            raise ValueError("向量数量与记忆数量不一致")
        with self.lock:
            if any(key in self._nodes for key in ids):
                raise ValueError("新节点 ID 重复")
            for node in nodes:
                if node.type != "chat" and not set(node.filling).issubset(self._nodes):
                    raise ValueError("来源/证据必须是已存在的记忆 ID")
            self.collection.add(ids=ids, documents=[node.description for node in nodes],
                                embeddings=vectors, metadatas=[self.metadata(node) for node in nodes])
            self._nodes.update({node.node_id: node.model_copy(deep=True) for node in nodes})

    def update(self, nodes):
        nodes = list({node.node_id: node for node in nodes}.values())
        if not nodes:
            return
        with self.lock:
            for node in nodes:
                if node.node_id not in self._nodes:
                    raise ValueError("待更新节点已不存在")
                if node.description != self._nodes[node.node_id].description:
                    raise ValueError("metadata更新不能替换正文")
            self.collection.update(ids=[node.node_id for node in nodes],
                                   metadatas=[self.metadata(node) for node in nodes])
            self._nodes.update({node.node_id: node.model_copy(deep=True) for node in nodes})

    def patch(self, node_id, **fields):
        """更新少数字段时从最新记录合并，避免旧快照覆盖已完成的关联更新。"""
        with self.lock:
            data = self._nodes[node_id].model_dump()
            data.update(fields)
            node = ConceptNode.model_validate(data)
            self.update([node])
            return node

    def search(self, query: str, now: datetime, limit=30, exclude=(), snapshot=None):
        nodes = self.nodes if snapshot is None else snapshot
        candidates = [node for node in nodes.values()
                      if node.type != "chat" and eligible(node, nodes, now)]
        if not candidates:
            return []
        vector = self.embeddings.embed_query(query)
        with self.lock:
            count = sum(node.type != "chat" for node in self._nodes.values())
            if not count:
                return []
            result = self.collection.query(
                query_embeddings=[vector], n_results=count, include=["distances"],
                where={"node_type": {"$in": ["event", "thought"]}},
            )
        allowed = {node.node_id for node in candidates} - set(exclude)
        found = [Candidate(node_id=key, similarity=max(-1.0, min(1.0, 1 - distance)),
                           score=max(-1.0, min(1.0, 1 - distance)))
                 for key, distance in zip(result["ids"][0], result["distances"][0], strict=True)
                 if key in allowed]
        return sorted(found, key=lambda item: (-item.score, item.node_id))[:limit]

    def next_fields(self, node_type):
        with self.lock:
            return {"node_count": max((n.node_count for n in self._nodes.values()), default=0) + 1,
                    "type_count": 1 + sum(n.type == node_type for n in self._nodes.values())}

    def reset(self):
        with self.lock:
            self.client.delete_collection(self.name)
            self.collection = self.client.get_or_create_collection(
                name=self.name, embedding_function=None,
                metadata={"hnsw:space": "cosine", "embedding_signature": self.signature},
            )
            self._nodes = {}
