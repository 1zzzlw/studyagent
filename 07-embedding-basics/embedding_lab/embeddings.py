"""OpenAI-compatible Embedding 客户端。"""

from __future__ import annotations

from typing import Any


class OpenAICompatibleEmbeddings:
    """把 SDK 的返回值整理成教学代码需要的 list[list[float]]。

    WildAgent 也把文档分成至多 10 条一批，以兼容上游服务的批量限制。
    """

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        batch_size: int = 10,
        timeout: float = 60.0,
    ):
        self.api_key = api_key
        self.base_url = base_url
        self.model = model
        self.batch_size = max(1, min(batch_size, 10))
        self.timeout = timeout
        self._client: Any | None = None

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        vectors = []
        # 批量把一批文本`texts`调用 Embedding 接口，输出对应的浮点向量列表 list[list[float]]
        for start in range(0, len(texts), self.batch_size):
            batch = texts[start:start + self.batch_size]
            response = self._get_client().embeddings.create(
                model=self.model,
                input=batch,
                encoding_format="float",
            )
            # OpenAI-compatible 服务不一定保证 data 已按输入顺序排列。
            # 对接口返回乱序的 embedding 结果，按 index 矫正顺序，转为普通列表，批量合并到总 vectors
            vectors.extend(
                list(item.embedding)
                for item in sorted(response.data, key=lambda item: item.index)
            )
        return vectors

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]

    def _get_client(self):
        if self._client is None:
            from openai import OpenAI

            # 创建通用 SDK 客户端
            self._client = OpenAI(
                api_key=self.api_key,
                base_url=self.base_url,
                timeout=self.timeout,
                max_retries=1,
            )
        return self._client
