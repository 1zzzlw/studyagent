# 第 9 章：切换 Embedding 模型实战

## 本章边界

本章的所有动手操作都在 `studyAgent/07-embedding-basics` 中完成：

- 代码由你亲手写入自己的 `01.basic.ipynb`；
- 练习数据使用两条最小 Chunk；
- Chroma 写入系统临时目录，不碰当前正式学习索引；
- 不运行、不修改 WildAgent；
- WildAgent 只在最后作为生产设计的只读对照。

## 本章目标

把“修改一个模型名”升级为一次可验证、可回滚的索引迁移：

```text
旧模型 + 旧 Collection 保持可用
        ↓
验证新模型能生成向量
        ↓
新模型写入独立的新 Collection
        ↓
验证数量、维度和查询结果
        ↓
切换为新模型 + 新 Collection
        ↓
出现问题时成对恢复旧模型 + 旧 Collection
```

## 1. 哪些变化必须重建

| 变化 | 是否重建 | 原因 |
|---|---|---|
| 更换 Embedding 模型 | 必须 | 向量坐标系改变 |
| 模型名相同，但服务端版本或权重改变 | 建议按新模型处理 | 向量空间可能已经改变 |
| 向量维度改变 | 必须 | 数据库不能比较不同长度的向量 |
| `chunk_size` / `chunk_overlap` 改变 | 必须 | Chunk 边界和 ID 改变 |
| 只更换 API Key，模型和服务不变 | 通常不用 | Key 只负责鉴权 |
| 只修改 Top-K | 不用 | 只影响查询保留数量 |
| 更换聊天模型 | 不用 | 聊天模型不生成检索向量 |

两个模型都是1024维，也不能证明它们兼容。维度相同只代表向量长度相同，不代表每个坐标表达相同语义。

## 2. studyAgent 当前参考实现的策略

当前 [config.py](../embedding_lab/config.py) 中的 Collection 名固定为：

```python
collection_name = "studyagent_wild_knowledge_v1"
```

模型、Base URL 或切片参数变化时，`index_signature` 会变化。参考实现会阻止继续使用旧集合，并要求你明确执行：

```powershell
uv run python 07-embedding-basics\run.py sync --rebuild
```

这属于“删除同名旧集合，再原地重建”的简单学习策略。它适合你已经确定不要旧索引的情况，但不适合演练安全切换与回滚。

因此，本章先在 Notebook 中建立两个独立 Collection：

```text
knowledge_old_model_v1
knowledge_new_model_v1
```

旧集合不会在新集合构建过程中被删除。

## 3. Notebook 分单元格练习：双 Collection 迁移

在 `01.basic.ipynb` 中建立一级 Markdown 标题：

```markdown
# 第 9 章：模型迁移
```

如果 Kernel 重启，先重新运行模块 README 中的公共初始化 Cell。

### Cell 1：准备独立临时数据库

- 依赖：公共初始化 Cell；
- 是否联网：否；
- 输入：无；
- 预期：打印一个系统临时目录，不是模块当前的 `storage/chroma`。

```python
from pathlib import Path
import tempfile

from embedding_lab.chunking import Chunk
from embedding_lab.vector_store import ChromaVectorStore

temp_handle = tempfile.TemporaryDirectory(
    prefix="studyagent-embedding-migration-",
    ignore_cleanup_errors=True,
)
migration_persist_dir = Path(temp_handle.name)

print("迁移实验目录：", migration_persist_dir)
print("当前正式学习索引：", MODULE_ROOT / "storage" / "chroma")
assert migration_persist_dir != MODULE_ROOT / "storage" / "chroma"
```

观察点：两个路径必须不同。本章发生错误也不能影响你已有的学习索引。

### Cell 2：定义旧模型和新模型

- 依赖：Cell 1；
- 是否联网：否；
- 输入：文本列表或单条问题；
- 预期：旧模型返回二维向量，新模型返回三维向量。

```python
class OldTeachingEmbeddings:
    model_name = "old-teaching-2d"

    def _embed(self, text: str) -> list[float]:
        if "幕墙" in text:
            return [1.0, 0.0]
        return [0.0, 1.0]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)


class NewTeachingEmbeddings:
    model_name = "new-teaching-3d"

    def _embed(self, text: str) -> list[float]:
        if "幕墙" in text:
            return [1.0, 0.0, 0.0]
        return [0.0, 1.0, 0.0]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)


old_embeddings = OldTeachingEmbeddings()
new_embeddings = NewTeachingEmbeddings()

print("旧模型维度：", len(old_embeddings.embed_query("幕墙")))
print("新模型维度：", len(new_embeddings.embed_query("幕墙")))
```

这些是假向量，只用于验证迁移流程，不能评价真实语义检索质量。

### Cell 3：准备同一份最小知识

- 依赖：Cell 1；
- 是否联网：否；
- 输入：两条 Chunk；
- 预期：两个模型将处理完全相同的文本和 metadata。

```python
migration_chunks = [
    Chunk(
        id="wall-001",
        text="幕墙需要通过 parentWall 挂接到主体墙",
        metadata={
            "namespace": "migration_test",
            "source": "walls.md",
            "heading": "幕墙",
            "doc_scope": "generation",
        },
    ),
    Chunk(
        id="stair-001",
        text="楼梯用于连接上下楼层",
        metadata={
            "namespace": "migration_test",
            "source": "stairs.md",
            "heading": "楼梯",
            "doc_scope": "generation",
        },
    ),
]

print("实验 Chunk 数量：", len(migration_chunks))
for chunk in migration_chunks:
    print(chunk.id, chunk.text)
```

### Cell 4：使用旧模型建立旧 Collection

- 依赖：Cell 2、Cell 3；
- 是否联网：否；
- 状态变化：临时 Chroma 中新增旧 Collection 和两条二维向量；
- 预期：查询“幕墙”返回 `wall-001`。

```python
old_store = ChromaVectorStore(
    persist_dir=migration_persist_dir,
    collection_name="knowledge_old_model_v1",
    namespace="migration_test",
    index_signature="old-teaching-2d-chunk-v1",
)

old_stats = old_store.sync(
    migration_chunks,
    old_embeddings,
    progress=print,
)
old_hits = old_store.query("幕墙怎样挂接？", old_embeddings, k=1)

print("旧集合同步结果：", old_stats)
print("旧集合数量：", old_store.status()["count"])
print("旧模型 Top-1：", old_hits[0].id)

assert old_store.status()["count"] == 2
assert old_hits[0].id == "wall-001"
```

### Cell 5：使用新模型建立独立新 Collection

- 依赖：Cell 2、Cell 3、Cell 4；
- 是否联网：否；
- 状态变化：同一临时数据库新增一个三维向量 Collection；
- 预期：新集合创建成功，旧集合仍保留两条记录。

```python
new_store = ChromaVectorStore(
    persist_dir=migration_persist_dir,
    collection_name="knowledge_new_model_v1",
    namespace="migration_test",
    index_signature="new-teaching-3d-chunk-v1",
)

new_stats = new_store.sync(
    migration_chunks,
    new_embeddings,
    progress=print,
)
new_hits = new_store.query("幕墙怎样挂接？", new_embeddings, k=1)

print("新集合同步结果：", new_stats)
print("新集合数量：", new_store.status()["count"])
print("新模型 Top-1：", new_hits[0].id)
print("旧集合仍有：", old_store.status()["count"], "条")

assert new_store.status()["count"] == 2
assert old_store.status()["count"] == 2
assert new_hits[0].id == "wall-001"
```

此时不是“新模型覆盖旧模型”，而是两个模型各自拥有一个独立向量空间。

### Cell 6：比较切换前后的结果

- 依赖：Cell 4、Cell 5；
- 是否联网：否；
- 输入：相同问题；
- 预期：新旧模型在各自 Collection 中都能召回正确块。

```python
question = "幕墙怎样连接主体墙？"

comparison = {
    "old": old_store.query(question, old_embeddings, k=1)[0],
    "new": new_store.query(question, new_embeddings, k=1)[0],
}

for version, hit in comparison.items():
    print(
        version,
        "chunk_id=", hit.id,
        "distance=", hit.distance,
        "source=", hit.metadata.get("source"),
    )

assert comparison["old"].id == "wall-001"
assert comparison["new"].id == "wall-001"
```

不要直接比较两个模型的 distance 数值大小。不同模型的距离分布不一定处于同一尺度。

### Cell 7：主动制造错误组合

- 依赖：Cell 5；
- 是否联网：否；
- 主动错误：使用三维新模型查询二维旧 Collection；
- 预期：Chroma 报告查询向量维度不一致。

```python
try:
    old_store.query(
        "幕墙怎样挂接？",
        new_embeddings,
        k=1,
    )
except Exception as exc:
    print("预期错误类型：", type(exc).__name__)
    print("预期错误信息：", exc)
else:
    raise AssertionError("新模型不应该直接查询旧模型的 Collection")
```

排错顺序：先检查 Collection 名，再检查查询模型，最后检查向量维度。不要因为数据库中“有数据”就认为数据一定兼容。

### Cell 8：模拟切换和回滚

- 依赖：Cell 4、Cell 5；
- 是否联网：否；
- 输入：版本配置字典；
- 预期：切换和回滚都必须同时选择模型对象与 Collection 对象。

```python
versions = {
    "old": {
        "embeddings": old_embeddings,
        "store": old_store,
    },
    "new": {
        "embeddings": new_embeddings,
        "store": new_store,
    },
}


def query_version(version: str, question: str):
    selected = versions[version]
    return selected["store"].query(
        question,
        selected["embeddings"],
        k=1,
    )[0]


active_version = "new"
switched_hit = query_version(active_version, "幕墙怎样挂接？")
print("切换后的版本：", active_version, switched_hit.id)

active_version = "old"
rollback_hit = query_version(active_version, "幕墙怎样挂接？")
print("回滚后的版本：", active_version, rollback_hit.id)

assert switched_hit.id == "wall-001"
assert rollback_hit.id == "wall-001"
```

这里最重要的不是字典，而是“模型和 Collection 必须成对选择”。

### Cell 9：模拟 Kernel 重启后重新打开新集合

- 依赖：Cell 5；
- 是否联网：否；
- 状态变化：创建新的 Store 对象，但复用同一个持久化目录和 Collection；
- 预期：不用重新写入，也能查询已有两条向量。

```python
reopened_new_store = ChromaVectorStore(
    persist_dir=migration_persist_dir,
    collection_name="knowledge_new_model_v1",
    namespace="migration_test",
    index_signature="new-teaching-3d-chunk-v1",
)

reopened_status = reopened_new_store.status()
reopened_hits = reopened_new_store.query(
    "幕墙怎样挂接？",
    new_embeddings,
    k=1,
)

print("重新打开后的数量：", reopened_status["count"])
print("重新打开后的 Top-1：", reopened_hits[0].id)

assert reopened_status["count"] == 2
assert reopened_hits[0].id == "wall-001"
```

这证明切换配置的本质是“让应用重新打开已经验证的新 Collection”，不是每次启动都重新生成向量。

### Cell 10：清理临时实验目录

- 依赖：前面所有需要观察数据库的 Cell；
- 是否联网：否；
- 预期：释放本章的临时目录；
- 注意：清理后不能再运行 Cell 4～9，除非从 Cell 1 重新开始。

```python
old_store = None
new_store = None
reopened_new_store = None

temp_handle.cleanup()
print("已申请清理临时迁移目录：", migration_persist_dir)
```

Windows 若仍有 Chroma 文件句柄，临时目录可能延迟到 Kernel 结束后才完全释放，这不影响模块正式索引。

## 4. 使用真实腾讯模型做最小迁移前验证

完成离线双 Collection 实验后，再验证真实模型。先在根目录 `.env` 配置：

```dotenv
EMBEDDING_MODEL=kinfra-text-embedding-0.6b
EMBEDDING_BASE_URL=https://tokenhub.tencentmaas.com/v1
EMBEDDING_API_KEY=你的_TokenHub_API_Key
```

先执行：

```powershell
uv run python 07-embedding-basics\run.py probe
```

它只发送一条测试文本，不打开、不删除 Chroma。你需要记录：

- 模型名；
- Base URL；
- 返回维度；
- 是否收到 HTTP 响应；
- 失败发生在网络、鉴权、模型还是参数层。

如果 `probe` 失败，不要执行 `sync --rebuild`。

## 5. 你决定放弃旧学习索引后再重建

studyAgent 当前命令行参考实现没有提供 Collection 切换参数。如果你已经决定不要旧索引，可以执行：

```powershell
uv run python 07-embedding-basics\run.py sync --rebuild
```

它会删除并重建本模块固定的 `studyagent_wild_knowledge_v1` Collection。执行前确认：

1. `probe` 已成功；
2. 你接受旧索引被替换；
3. 当前模型不是 Rerank 或聊天模型；
4. 当前 Base URL、模型和 Key 属于同一个向量服务；
5. 你能接受全量向量化的时间和费用。

如果首次 `sync --rebuild` 中途被打断，下一次只运行不带 `--rebuild` 的 `sync`：

```powershell
uv run python 07-embedding-basics\run.py sync
```

程序会读取已存在的 chunk ID，只补充尚未写入的块。不要再次添加 `--rebuild`，否则会删除已经完成的部分并重新开始。

## 6. 重建后的验证顺序

```powershell
# 查看数量和索引签名
uv run python 07-embedding-basics\run.py status

# 运行代表性查询
uv run python 07-embedding-basics\run.py query "玻璃幕墙应该怎样挂接到墙体？" --k 3

# 文档未变化时再次同步，应看到 added=0
uv run python 07-embedding-basics\run.py sync
```

至少验证：

| 验证项 | 成功标准 |
|---|---|
| 数量完整性 | Collection count 等于当前 Chunk 总数 |
| 增量同步 | 第二次同步 `added=0` |
| 模型一致性 | 查询不出现签名或维度错误 |
| 正例召回 | 代表性问题的正确来源进入 Top-K |
| 反例召回 | 无关问题不会稳定命中同一份错误资料 |

“数据库里有几百条记录”只证明写入过数据，不证明检索质量合格。

## 7. 卡住或失败时怎样判断

| 最后现象 | 所属层 | 下一步 |
|---|---|---|
| `probe` 在 TLS/连接阶段超时 | 网络路径 | 检查当前进程代理、DNS和目标地址 |
| `probe` 返回401或403 | 鉴权 | 检查 `EMBEDDING_API_KEY` 和服务权限 |
| 服务端提示 `Rerank` | 模型类型 | 改用真正的 Embedding 模型 |
| `probe` 成功，`sync` 扫描为0 | 文档层 | 检查 `knowledge_dir` |
| 同步一半中断 | 同步层 | 重新执行 `sync`，通过 chunk ID 补齐缺失块 |
| 索引签名不一致 | 配置层 | 确认是否确实换了模型、地址或切片参数 |
| 查询维度错误 | 模型/集合组合 | 检查建库模型与查询模型是否成对 |
| Top-K 来源错误 | 检索质量 | 检查切片并建立固定问题集评测 |

## 8. WildAgent 只读对照

完成本章 Notebook 后，只需要理解 WildAgent 比教学实现多了一层生产保护：它会先建立独立的新 Collection，验证完成后再切换 Collection 配置，并保留旧集合用于回滚。

这里不要求你运行 WildAgent 的迁移脚本，也不要求修改 WildAgent。studyAgent 的离线双 Collection 实验已经覆盖了相同的核心思想：

```text
旧模型 + 旧 Collection
新模型 + 新 Collection
验证后成对切换
异常时成对回滚
```

## 9. 练习题

1. 把新模型从三维改成四维，重新运行 Cell 5～7，记录错误是否变化。
2. 保持向量维度相同，但改变新模型的语义映射，观察为什么“维度相同”仍不能复用旧集合。
3. 修改新 Store 的 `index_signature`，但保持 Collection 名不变，观察程序在哪一步阻止使用。
4. 向 `migration_chunks` 增加第三条知识，再次同步两个集合，比较新增数量。
5. 在 Markdown Cell 中解释：为什么 API Key 不应该参与索引兼容性判断。

不提供练习题完整答案。请记录输入、输出、异常类型和自己的解释。

## 10. 完成检查

- [ ] 我只在 studyAgent 的 Notebook 和临时 Chroma 中完成练习
- [ ] 我能说明哪些配置变化必须重建索引
- [ ] 我能先做单条模型探针，再决定是否全量建库
- [ ] 我能使用独立新 Collection 保护旧索引
- [ ] 我能验证新旧集合的数量和查询结果
- [ ] 我知道模型与 Collection 必须成对切换、成对回滚
- [ ] 我能解释为什么维度相同仍不代表模型兼容
- [ ] 我没有运行或修改 WildAgent
