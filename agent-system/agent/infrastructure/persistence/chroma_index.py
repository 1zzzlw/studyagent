"""Chroma 只保存可检索正文与 ID；强度和证据来自 SQLite。"""
from threading import RLock

class ChromaIndex:
    def __init__(self, path, embeddings, signature):
        import chromadb
        from chromadb.config import Settings
        self.path, self.embeddings = path, embeddings
        self.lock = RLock()
        self.client = chromadb.PersistentClient(path=str(path), settings=Settings(anonymized_telemetry=False))
        self.collection = self.client.get_or_create_collection(
            "agent_system_memories", embedding_function=None,
            metadata={"hnsw:space": "cosine", "embedding_signature": signature})
        if self.collection.metadata.get("embedding_signature") != signature:
            raise ValueError("向量模型配置已变化，不能混用旧向量；请使用新的 Chroma 存储目录。")

    @staticmethod
    def text(node):
        return node.description + "\n背景：" + node.context + "\n关键词：" + "、".join(node.keywords)

    def upsert(self, nodes):
        if not nodes:
            return
        vectors = self.embeddings.embed_documents([self.text(node) for node in nodes])
        with self.lock:
            self.collection.upsert(
                ids=[node.node_id for node in nodes], embeddings=vectors,
                documents=[self.text(node) for node in nodes],
                metadatas=[{"character_id": node.character_id, "conversation_id": node.conversation_id,
                            "type": node.type} for node in nodes])

    def search(self, query, character_id, limit=20):
        with self.lock:
            count = self.collection.count()
        if not count:
            return []
        vector = self.embeddings.embed_query(query)
        with self.lock:
            result = self.collection.query(query_embeddings=[vector], n_results=min(limit, count),
                                           where={"character_id": character_id}, include=["distances"])
        return [(key, max(-1.0, min(1.0, 1 - distance)))
                for key, distance in zip(result["ids"][0], result["distances"][0], strict=True)]

    def info(self):
        with self.lock:
            data = self.collection.get(limit=30, include=["metadatas", "documents", "embeddings"])
            vectors = data.pop("embeddings", None)
            # 展示维度与少量分量，避免几千维浮点数淹没检查页面。
            previews = [] if vectors is None else [
                {"node_id": key, "dimensions": len(vector), "first_8_values": vector[:8].tolist()}
                for key, vector in zip(data["ids"][:3], vectors[:3], strict=True)]
            return {"path": str(self.path), "collection": self.collection.name,
                    "count": self.collection.count(), "sample": data, "vector_previews": previews,
                    "embedding_signature": self.collection.metadata["embedding_signature"]}
