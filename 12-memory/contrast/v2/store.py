"""独立的 A-Mem 笔记存档：Chroma 正文向量 + 完整笔记 metadata。"""
from pathlib import Path
from threading import RLock

from .models import Candidate, MemoryNote


class ChromaStore:
    def __init__(self, path: Path, version: str, embeddings, signature: str, client=None):
        if client is None:
            import chromadb
            client = chromadb.PersistentClient(path=str(path))
        self.client, self.embeddings, self.signature = client, embeddings, signature
        self.name, self.lock = f"contrast_{version}", RLock()
        names = [getattr(item, "name", item) for item in client.list_collections()]
        if self.name in names:
            self.collection = client.get_collection(name=self.name, embedding_function=None)
        else:
            self.collection = client.get_or_create_collection(
                name=self.name, embedding_function=None,
                metadata={"hnsw:space": "cosine", "embedding_signature": signature, "memory_schema": "amem_note"},
            )
        if self.collection.metadata.get("embedding_signature") != signature:
            raise ValueError("向量模型配置已变化，请使用空实验目录，不混用旧向量。")
        if self.collection.metadata.get("memory_schema") != "amem_note":
            raise ValueError("v2 已改为纯 A-Mem 笔记。请先清空旧版 v2 数据目录再启动。")
        self._nodes = {}
        self.reload()

    @property
    def nodes(self):
        with self.lock:
            return {key: note.model_copy(deep=True) for key, note in self._nodes.items()}

    def reload(self):
        with self.lock:
            records = self.collection.get(include=["metadatas"])
            notes = {}
            for key, metadata in zip(records["ids"], records["metadatas"], strict=True):
                note = MemoryNote.model_validate_json(metadata["payload"])
                if key != note.id:
                    raise ValueError("Chroma ID 与笔记 ID 不一致")
                notes[key] = note
            self._nodes = notes

    @staticmethod
    def metadata(note):
        return {"payload": note.model_dump_json()}

    def add(self, notes):
        if not notes:
            return
        ids = [note.id for note in notes]
        if len(set(ids)) != len(ids):
            raise ValueError("笔记 ID 重复")
        vectors = self.embeddings.embed_documents([note.content for note in notes])
        if len(vectors) != len(notes):
            raise ValueError("向量数量与笔记数量不一致")
        with self.lock:
            if any(key in self._nodes for key in ids):
                raise ValueError("笔记 ID 已存在")
            self.collection.add(ids=ids, documents=[note.content for note in notes],
                                embeddings=vectors, metadatas=[self.metadata(note) for note in notes])
            self._nodes.update({note.id: note.model_copy(deep=True) for note in notes})

    def update(self, notes):
        notes = list({note.id: note for note in notes}.values())
        if not notes:
            return
        with self.lock:
            for note in notes:
                if note.content != self._nodes[note.id].content:
                    raise ValueError("语义维护不能替换笔记正文")
            # 正文没有变化；关键词、背景、链接和访问统计只更新 metadata。
            self.collection.update(ids=[note.id for note in notes],
                                   metadatas=[self.metadata(note) for note in notes])
            self._nodes.update({note.id: note.model_copy(deep=True) for note in notes})

    def search(self, query, limit=5):
        with self.lock:
            count = len(self._nodes)
        if not count:
            return []
        vector = self.embeddings.embed_query(query)
        with self.lock:
            result = self.collection.query(query_embeddings=[vector],
                                           n_results=min(count, limit), include=["distances"])
        return [Candidate(id=key, score=1 - distance)
                for key, distance in zip(result["ids"][0], result["distances"][0], strict=True)]

    def reset(self):
        with self.lock:
            self.client.delete_collection(self.name)
            self.collection = self.client.get_or_create_collection(
                name=self.name, embedding_function=None,
                metadata={"hnsw:space": "cosine", "embedding_signature": self.signature, "memory_schema": "amem_note"},
            )
            self._nodes = {}
