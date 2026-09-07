"""先按 Markdown 标题切分，再对过长章节做长度兜底。"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from .documents import SourceDocument


@dataclass(frozen=True)
class Chunk:
    id: str
    text: str
    metadata: dict[str, str | int]


class MarkdownChunker:
    _heading_pattern = re.compile(r"^(#{1,5})\s+(.+?)\s*#*\s*$")
    _fence_pattern = re.compile(r"^\s*(```+|~~~+)")

    def __init__(self, chunk_size: int = 900, chunk_overlap: int = 150):
        if chunk_size < 200:
            raise ValueError("chunk_size 至少为 200")
        if not 0 <= chunk_overlap < chunk_size:
            raise ValueError("chunk_overlap 必须大于等于 0 且小于 chunk_size")

        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def split_documents(
        self,
        documents: list[SourceDocument],
        namespace: str,
    ) -> list[Chunk]:
        chunks = []
        for document in documents:
            # extend() 是列表对象的内置方法，把传入的序列里面每一个元素，逐个追加到原列表末尾
            chunks.extend(self.split_document(document, namespace))
        return chunks

    def split_document(self, document: SourceDocument, namespace: str) -> list[Chunk]:
        chunks = []
        chunk_index = 0

        for heading_parts, section_text in self._split_markdown_sections(document.text):
            heading = " > ".join(heading_parts) or document.path.stem
            context_line = f"> 知识路径：{heading}"

            # 每个长度子块都重复标题路径。这样块被单独召回时仍知道自己属于哪里。
            section_parts = self._split_long_text(section_text)
            for part_index, part in enumerate(section_parts):
                text = f"{context_line}\n\n{part.strip()}".strip()
                if not part.strip():
                    continue

                content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
                id_payload = (
                    f"{namespace}:{document.source}:{chunk_index}:{part_index}:{content_hash}"
                )
                chunk_id = hashlib.sha256(id_payload.encode("utf-8")).hexdigest()
                chunks.append(
                    Chunk(
                        id=chunk_id,
                        text=text,
                        metadata={
                            "namespace": namespace,
                            "source": document.source,
                            "heading": heading,
                            "doc_scope": document.doc_scope,
                            "chunk_index": chunk_index,
                            "part_index": part_index,
                            "content_hash": content_hash,
                        },
                    )
                )
                chunk_index += 1

        return chunks

    def _split_markdown_sections(self, text: str) -> list[tuple[list[str], str]]:
        """按标题边界切分；围栏代码中的 # 不作为标题。"""
        sections: list[tuple[list[str], str]] = []
        heading_stack: list[str] = []
        current_heading: list[str] = []
        current_lines: list[str] = []
        active_fence: str | None = None

        def flush() -> None:
            body = "\n".join(current_lines).strip()
            if body:
                sections.append((list(current_heading), body))

        for line in text.splitlines():
            fence_match = self._fence_pattern.match(line)
            if fence_match:
                fence_char = fence_match.group(1)[0]
                if active_fence is None:
                    active_fence = fence_char
                elif active_fence == fence_char:
                    active_fence = None
                current_lines.append(line)
                continue

            heading_match = self._heading_pattern.match(line) if active_fence is None else None
            if heading_match:
                flush()
                current_lines = [line]
                level = len(heading_match.group(1))
                heading_stack = heading_stack[:level - 1]
                heading_stack.append(heading_match.group(2).strip())
                current_heading = list(heading_stack)
                continue

            current_lines.append(line)

        flush()
        return sections

    def _split_long_text(self, text: str) -> list[str]:
        """按段落优先的滑动窗口切分，保留有限重叠。"""
        if len(text) <= self.chunk_size:
            return [text]

        parts = []
        start = 0
        separators = ("\n\n", "\n", "。", "！", "？", "；", " ")
        while start < len(text):
            end = min(start + self.chunk_size, len(text))
            if end < len(text):
                minimum_break = start + self.chunk_size // 2
                candidates = [
                    text.rfind(separator, minimum_break, end)
                    for separator in separators
                ]
                best_break = max(candidates)
                if best_break > start:
                    end = best_break + 1

            part = text[start:end].strip()
            if part:
                parts.append(part)
            if end >= len(text):
                break
            next_start = max(start + 1, end - self.chunk_overlap)
            start = next_start

        return parts
