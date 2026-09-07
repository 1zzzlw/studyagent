# 第 4 章：初始化 Chroma 并首次建库

## 本章目标

亲手完成第一次持久化建库，并知道每一步是否调用外部接口。

## 1. 建库前检查

确认 `studyAgent/.env` 包含：

```dotenv
EMBEDDING_MODEL=kinfra-text-embedding-0.6b
EMBEDDING_BASE_URL=https://tokenhub.tencentmaas.com/v1
EMBEDDING_API_KEY=你的_TokenHub_API_Key
```

代码不会打印或写入 API Key。`index_signature` 只包含模型名、接口地址和切块参数。

先执行不会读写 Chroma 的连接探针：

```powershell
uv run python 07-embedding-basics\run.py probe
```

只有看到模型名、接口地址、向量维度和“连接测试成功”，才继续建库。这样能避免把 Rerank 模型、错误地址或错误密钥带进 `sync --rebuild`。

## 2. 执行首次同步

在项目根目录运行：

```powershell
uv run python 07-embedding-basics\run.py sync
```

这条命令会执行：

```text
load_documents()
  → MarkdownChunker.split_documents()
  → Chroma PersistentClient
  → get_or_create_collection()
  → 找出尚未存在的 chunk ID
  → 每 10 块调用一次 embed_documents()
  → collection.upsert()
```

终端会逐批显示：

```text
Embedding 第 1/N 批：10 个文本块
```

这意味着程序正在进行真实接口调用。若文档很多，首次同步需要等待，也可能产生供应商费用。

## 3. `PersistentClient` 与 collection

Chroma 有两层概念：

- `PersistentClient(path=...)`：指定数据库文件存放目录；
- collection：同一数据库里的逻辑集合，类似一张专门用于向量检索的表。

本教程使用：

```text
目录：07-embedding-basics/storage/chroma
集合：studyagent_wild_knowledge_v1
```

它不会读取或修改 WildAgent 的 `wild-server/storage/chroma`。

## 4. 为什么使用 `upsert`

`add` 遇到重复 ID 容易失败；`upsert` 表示：

- ID 不存在则新增；
- ID 已存在则更新。

不过本教程不会无脑把全部块重新 `upsert`。它先比较现有 ID，只对新增块调用 Embedding。这样第二次同步才能真正节省时间和费用。

## 5. 建库后检查

```powershell
uv run python 07-embedding-basics\run.py status
```

应该看到：

- `persist_dir`；
- 集合名；
- `count`；
- `index_signature`；
- 距离类型 `cosine`。

`status` 不调用 Embedding 模型，只读取本地数据库。

## 6. 何时使用 `--rebuild`

以下情况需要重建：

- 更换 Embedding 模型；
- 更换接口地址且它代表另一套模型服务；
- 修改 `chunk_size` 或 `chunk_overlap`；
- 明确想从零验证首次建库。

执行：

```powershell
uv run python 07-embedding-basics\run.py sync --rebuild
```

这是有范围的删除操作：只删除本教学模块的指定 collection，再重新创建；不会清空整个 Chroma 目录。

## 7. Notebook 分单元格练习：用假向量完成第一次建库

在 `01.basic.ipynb` 中建立 `# 第 4 章：首次建库`。先用可预测的二维向量验证数据库写入链路，不调用真实模型。

### Cell 1：导入组件并定义假 Embedding

依赖：公共初始化 Cell。

```python
from pathlib import Path
import tempfile

from embedding_lab.chunking import Chunk
from embedding_lab.vector_store import ChromaVectorStore


class TeachingEmbeddings:
    """只验证存储流程，不代表真实语义模型。"""

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        vectors = []
        for text in texts:
            if "幕墙" in text:
                vectors.append([1.0, 0.0])
            else:
                vectors.append([0.0, 1.0])
        return vectors

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]
```

### Cell 2：准备两个 Chunk

依赖：Cell 1。

```python
chunks = [
    Chunk(
        id="wall-001",
        text="幕墙需要挂接到父墙体",
        metadata={
            "namespace": "first_sync_test",
            "source": "walls.md",
            "heading": "墙体 > 幕墙",
            "doc_scope": "generation",
        },
    ),
    Chunk(
        id="stair-001",
        text="楼梯连接上下两个楼层",
        metadata={
            "namespace": "first_sync_test",
            "source": "stairs.md",
            "heading": "楼梯 > 连接",
            "doc_scope": "generation",
        },
    ),
]

print("待写入 Chunk 数：", len(chunks))
```

### Cell 3：创建独立临时 Chroma

依赖：Cell 1。

```python
persist_dir = Path(tempfile.mkdtemp(prefix="studyagent-first-sync-"))
store = ChromaVectorStore(
    persist_dir=persist_dir,
    collection_name="first_sync_demo",
    namespace="first_sync_test",
    index_signature="teaching-model-v1-chunk-v1",
)

print("临时数据库：", persist_dir)
```

### Cell 4：执行首次同步并断言

依赖：Cell 2、Cell 3。

```python
messages: list[str] = []
stats = store.sync(
    chunks,
    TeachingEmbeddings(),
    batch_size=1,
    progress=messages.append,
)
status = store.status()

assert stats.total == 2
assert stats.added == 2
assert stats.deleted == 0
assert status["count"] == 2
assert len(messages) == 2

print("同步统计：", stats)
print("集合状态：", status)
print("批次日志：", messages)
```

重点观察：

- `batch_size=1` 让两个 Chunk 分成两批，便于看清调用次数；
- `sync()` 负责比较 ID、生成向量并 `upsert`；
- `status()` 只读取集合，不会调用 `TeachingEmbeddings`；
- 临时目录与正式 `storage/chroma` 完全隔离。

### 建库前后的数量断言

第一次执行前，数据库中没有集合；同步结束后应该同时满足：

```text
stats.total == 输入 Chunk 数量
stats.added == 本次新向量数量
status["count"] == 数据库实际记录数量
```

三者用途不同，不能只看“终端没有报错”就判断建库完整。

### Cell 5：主动制造一次错误

依赖：Cell 1。在另一个全新的临时目录里，只创建 Store 后立刻调用 `status()`：

```python
empty_store = ChromaVectorStore(
    persist_dir=Path(tempfile.mkdtemp(prefix="studyagent-empty-")),
    collection_name="not_built_yet",
    namespace="first_sync_test",
    index_signature="teaching-model-v1-chunk-v1",
)

try:
    empty_store.status()
except RuntimeError as exc:
    print("预期错误：", exc)
else:
    raise AssertionError("首次同步前不应该读取到集合状态")
```

这能证明“创建 Store 对象”不等于“集合已经建好”。

### Cell 6：用 Markdown 写总结

记录 Client、Collection、记录、`upsert`、同步统计与数据库实际数量之间的关系。

## 8. 完成检查

- [ ] 我能解释 Client、Collection 和记录三层概念
- [ ] 我能用假向量离线完成首次写入
- [ ] 我能解释 `upsert` 与 `add` 的区别
- [ ] 我会使用独立目录保护正式索引
- [ ] 我会同时验证输入数、新增数和数据库实际数量

参考：[Chroma Python Client](https://docs.trychroma.com/reference/python/client)、[Collection upsert](https://docs.trychroma.com/reference/python/collection)
