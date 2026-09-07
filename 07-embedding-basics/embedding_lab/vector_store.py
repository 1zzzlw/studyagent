"""Chroma 的创建、增量同步和向量查询。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
# Protocol 只要一个类实现了这两个方法，方法签名对得上，就算满足这个 `Embeddings` 协议，不需要显式写继承 `class MyEmb(Embeddings)`。
from typing import Callable, Protocol

from .chunking import Chunk


class Embeddings(Protocol):
    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...
    def embed_query(self, text: str) -> list[float]: ...


@dataclass(frozen=True)
class SyncStats:
    total: int
    added: int
    deleted: int


@dataclass(frozen=True)
class SearchHit:
    id: str
    text: str
    metadata: dict
    distance: float | None


class ChromaVectorStore:
    def __init__(
        self,
        *,
        persist_dir: Path,
        collection_name: str,
        namespace: str,
        index_signature: str,
    ):
        self.persist_dir = persist_dir
        self.collection_name = collection_name
        self.namespace = namespace
        self.index_signature = index_signature
        self._client = None

    def sync(
        self,
        chunks: list[Chunk],
        embeddings: Embeddings,
        *,
        rebuild: bool = False,
        batch_size: int = 10,
        progress: Callable[[str], None] | None = None,
    ) -> SyncStats:
        collection = self._open_collection(rebuild=rebuild)
        existing = collection.get(
            where={"namespace": self.namespace},
            include=["metadatas"],
        )
        existing_ids = set(existing.get("ids") or [])
        chunks_by_id = {chunk.id: chunk for chunk in chunks}
        current_ids = set(chunks_by_id)

        stale_ids = sorted(existing_ids - current_ids)
        pending_chunks = [chunk for chunk in chunks if chunk.id not in existing_ids]

        for start in range(0, len(stale_ids), batch_size):
            collection.delete(ids=stale_ids[start:start + batch_size])

        added = 0
        total_batches = (len(pending_chunks) + batch_size - 1) // batch_size
        for start in range(0, len(pending_chunks), batch_size):
            batch = pending_chunks[start:start + batch_size]
            batch_number = start // batch_size + 1
            if progress:
                progress(
                    f"Embedding 第 {batch_number}/{total_batches} 批：{len(batch)} 个文本块"
                )
            vectors = embeddings.embed_documents([chunk.text for chunk in batch])
            collection.upsert(
                ids=[chunk.id for chunk in batch],
                documents=[chunk.text for chunk in batch],
                embeddings=vectors,
                metadatas=[chunk.metadata for chunk in batch],
            )
            added += len(batch)

        return SyncStats(total=len(chunks), added=added, deleted=len(stale_ids))

    def query(self, text: str, embeddings: Embeddings, k: int = 3) -> list[SearchHit]:
        collection = self._open_existing_collection()
        query_vector = embeddings.embed_query(text)
        result = collection.query(
            query_embeddings=[query_vector],
            n_results=max(1, k),
            where={
                "$and": [
                    {"namespace": self.namespace},
                    {"doc_scope": "generation"},
                ]
            },
            include=["documents", "metadatas", "distances"],
        )

        ids = (result.get("ids") or [[]])[0]
        documents = (result.get("documents") or [[]])[0]
        metadatas = (result.get("metadatas") or [[]])[0]
        distances = (result.get("distances") or [[]])[0]
        hits = []
        for index, chunk_id in enumerate(ids):
            hits.append(
                SearchHit(
                    id=chunk_id,
                    text=documents[index],
                    metadata=metadatas[index] or {},
                    distance=distances[index] if index < len(distances) else None,
                )
            )
        return hits

    def status(self) -> dict:
        collection = self._open_existing_collection()
        return {
            "persist_dir": str(self.persist_dir),
            "collection": self.collection_name,
            "count": collection.count(),
            "metadata": collection.metadata or {},
        }

    def _get_client(self):
        if self._client is None:
            import chromadb

            self.persist_dir.mkdir(parents=True, exist_ok=True)
            self._client = chromadb.PersistentClient(path=str(self.persist_dir))
        return self._client

    def _open_collection(self, *, rebuild: bool):
        client = self._get_client()
        if rebuild:
            try:
                client.delete_collection(name=self.collection_name)
            except Exception as exc:
                # 只忽略“集合不存在”；其他数据库错误仍应暴露。
                if "does not exist" not in str(exc).lower() and "not found" not in str(exc).lower():
                    raise

        metadata = {
            "course": "studyAgent/07-embedding-basics",
            "namespace": self.namespace,
            "index_signature": self.index_signature,
            "hnsw:space": "cosine",
        }
        collection = client.get_or_create_collection(
            name=self.collection_name,
            metadata=metadata,
        )
        existing_signature = (collection.metadata or {}).get("index_signature")
        if existing_signature != self.index_signature:
            raise RuntimeError(
                "当前集合由另一套 Embedding 模型或切块参数创建。"
                "请确认后执行 sync --rebuild 重建本教学集合。"
            )
        return collection

    def _open_existing_collection(self):
        client = self._get_client()
        try:
            collection = client.get_collection(name=self.collection_name)
        except Exception as exc:
            raise RuntimeError("索引尚未建立，请先执行 sync。") from exc

        existing_signature = (collection.metadata or {}).get("index_signature")
        if existing_signature != self.index_signature:
            raise RuntimeError(
                "索引配置签名与当前配置不同，请执行 sync --rebuild。"
            )
        return collection


