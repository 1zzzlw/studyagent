"""递归扫描和读取 Markdown 知识文档。"""

from __future__ import annotations

# 正则表达式模块
import re
from dataclasses import dataclass
from pathlib import Path

@dataclass(frozen=True)
class SourceDocument:
    path: Path
    source: str
    text: str
    doc_scope: str


_FRONTMATTER_PATTERN = re.compile(
    r"\A---[ \t]*\r?\n.*?\r?\n---[ \t]*(?:\r?\n|$)",
    re.DOTALL,
)


def collect_markdown_paths(root: Path) -> list[Path]:
    """收集参与向量检索的 Markdown，并保持稳定顺序。

    BLUEPRINT-SPEC-MINIMAL.md 在 WildAgent 中属于每次都直接注入 Prompt 的基础
    规范，因此这里也把它排除，避免同一内容既直接注入又参与向量召回。
    """
    if not root.exists():
        raise FileNotFoundError(f"知识库目录不存在：{root}")

    paths = [
        path
        for path in root.rglob("*.md")
        if path.is_file() and path.name != "BLUEPRINT-SPEC-MINIMAL.md"
    ]

    # 对可迭代对象排序，返回新列表，原数据不变
    # iterable：可迭代对象（列表、元组、集合、字典、生成器等）
    # key：排序规则函数，用来指定按什么来排序
    # reverse=False：默认升序；reverse=True 降序

    # path.relative_to(root) path 是 Path 对象，代表某一个文件路径，把完整路径，转成相对于 root 的相对路径
    # as_posix() 把 Windows 反斜杠路径 `c\d\e` 统一转成 Unix 风格斜杠 `c/d/e` 和 消除操作系统路径分隔符差异，保证跨平台排序行为一致。
    # casefold() 字符串彻底小写化，比 `.lower()` 更强，专门用于忽略大小写比较
    return sorted(paths, key=lambda path: path.relative_to(root).as_posix().casefold())


def load_documents(root: Path) -> list[SourceDocument]:
    documents = []
    for path in collect_markdown_paths(root):
        # 获得所有文档的绝对值路径
        relative_source = path.relative_to(root).as_posix()
        text = path.read_text(encoding="utf-8")
        # 教学版先移除 YAML frontmatter，避免把 metadata 自己当成正文向量化。
        # 调用正则表达式
        text = _FRONTMATTER_PATTERN.sub("", text, count=1)
        documents.append(
            SourceDocument(
                path=path,
                source=relative_source,
                text=text,
                # README 通常是目录导航，不应挤占普通生成查询的 Top-K。
                doc_scope="index" if path.name.casefold() == "readme.md" else "generation",
            )
        )
    return documents
