"""教学模块的集中配置。"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path

from . import MODULE_ROOT


@dataclass(frozen=True)
class Settings:
    knowledge_dir: Path = MODULE_ROOT / "storage" / "knowledge_base"
    persist_dir: Path = MODULE_ROOT / "storage" / "chroma"
    collection_name: str = "studyagent_wild_knowledge_v1"
    namespace: str = "embedding_basics"
    chunk_size: int = 900
    chunk_overlap: int = 150
    embedding_batch_size: int = 10
    embedding_model: str = os.getenv("EMBEDDING_MODEL", "")
    embedding_base_url: str = os.getenv("EMBEDDING_BASE_URL", "")
    embedding_api_key: str = os.getenv("EMBEDDING_API_KEY", "")

    def require_embedding_config(self) -> None:
        missing = []
        if not self.embedding_model:
            missing.append("EMBEDDING_MODEL")
        if not self.embedding_base_url:
            missing.append("EMBEDDING_BASE_URL")
        if not self.embedding_api_key:
            missing.append("EMBEDDING_API_KEY")
        if missing:
            raise RuntimeError(
                f"缺少环境变量：{', '.join(missing)}。请在 studyAgent/.env 中配置。"
            )

    def index_signature(self) -> str:
        """标识所有会改变向量兼容性或切块边界的配置。"""
        payload = json.dumps(
            {
                "version": 1,
                "embedding_model": self.embedding_model,
                "embedding_base_url": self.embedding_base_url,
                "chunk_size": self.chunk_size,
                "chunk_overlap": self.chunk_overlap,
            },
            ensure_ascii=True,
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
