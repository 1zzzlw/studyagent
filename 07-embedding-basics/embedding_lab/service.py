"""把扫描、切块、向量化和 Chroma 串成一条可观察的教学链路。"""

from __future__ import annotations

from .chunking import MarkdownChunker
from .config import Settings
from .documents import load_documents
from .embeddings import OpenAICompatibleEmbeddings
from .vector_store import ChromaVectorStore


class EmbeddingLabService:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or Settings()
        self.chunker = MarkdownChunker(
            chunk_size=self.settings.chunk_size,
            chunk_overlap=self.settings.chunk_overlap,
        )
        self.store = ChromaVectorStore(
            persist_dir=self.settings.persist_dir,
            collection_name=self.settings.collection_name,
            namespace=self.settings.namespace,
            index_signature=self.settings.index_signature(),
        )

    def build_chunks(self):
        documents = load_documents(self.settings.knowledge_dir)
        chunks = self.chunker.split_documents(documents, self.settings.namespace)
        return documents, chunks

    def create_embeddings(self):
        self.settings.require_embedding_config()
        return OpenAICompatibleEmbeddings(
            api_key=self.settings.embedding_api_key,
            base_url=self.settings.embedding_base_url,
            model=self.settings.embedding_model,
            batch_size=self.settings.embedding_batch_size,
        )

