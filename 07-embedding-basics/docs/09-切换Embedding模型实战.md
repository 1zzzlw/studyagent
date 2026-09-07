# 第 9 章：切换 Embedding 模型实战

> 本章中的 `EMBEDDING__*`、`RAG__*` 是 WildAgent 生产项目的配置名，只用于只读对照。studyAgent 自己使用 `EMBEDDING_MODEL`、`EMBEDDING_BASE_URL`、`EMBEDDING_API_KEY`，详见第 10 章。不要把两套命名混写。

## 本章目标

把“修改一个模型名”升级为一次可验证、可回滚的索引迁移。正确流程不是直接覆盖旧向量，而是：

```text
旧模型 + 旧 collection 保持可用
        ↓
验证新模型的最小请求
        ↓
新模型全量构建新 collection
        ↓
用同一套问题评测新旧召回
        ↓
切换配置并重启
        ↓
保留旧配置用于回滚
```

## 1. 哪些变化必须重建

| 变化 | 是否重建 | 原因 |
|---|---|---|
| 更换 Embedding 模型 | 必须 | 向量坐标系改变 |
| 模型名相同，但实际部署或版本改变 | 建议按新模型处理 | 服务端可能已换权重或向量空间 |
| 向量维度改变 | 必须 | 数据库无法比较不同维度 |
| `chunk_size` / `chunk_overlap` 改变 | 必须 | 文本块边界和 ID 改变 |
| 只更换 API Key，仍访问同一模型 | 通常不用 | Key 不改变向量空间 |
| 只修改 Top-K | 不用 | 只影响查询保留数量 |
| 修改距离门禁阈值 | 不用重建，但必须重新校准 | 不同模型的距离分布不同 |
| 更换聊天模型 | 不用 | 聊天模型不生成检索向量 |

不要用“维度相同”判断两个模型兼容。维度相同只说明向量长度相同，不说明坐标含义相同。

## 2. 为什么不建议原地删除旧集合

假设正式集合一直叫：

```text
wild_knowledge_base
```

修改模型后若程序立即删除它并开始重建，会出现一个危险窗口：

- 新模型接口超时；
- 只写入了一部分文档；
- 旧索引已经不存在；
- 服务既不能完成新检索，也无法快速回滚。

更安全的命名方式：

```text
wild_knowledge_base_text_embedding_v4_v1
wild_knowledge_base_qwen37_embedding_v1
```

模型配置与 collection 名要作为一对配置保存。回滚时两者必须一起恢复。

## 3. 第一步：保存旧基线

切换前记录：

```dotenv
EMBEDDING__NAME=旧模型
EMBEDDING__BASE_URL=旧地址
RAG__COLLECTION_NAME=旧集合
RAG__CHUNK_SIZE=900
RAG__CHUNK_OVERLAP=150
```

再用当前索引运行固定评测：

```powershell
cd E:\AgentProject\WildAgent\wild-server
$env:PYTHONPATH="."

.\.venv\Scripts\python.exe scripts\rag\eval_retrieval.py
```

保存 Hit@K、Recall@K、MRR、逐题来源和距离分布。没有旧基线，就无法证明新模型是否真的更好。

## 4. 第二步：只测试新模型连接

先在 `.env` 填写候选模型的三个字段，但暂时不要修改正式 collection：

```dotenv
EMBEDDING__NAME=候选模型名
EMBEDDING__API_KEY=候选密钥
EMBEDDING__BASE_URL=https://候选服务/v1
```

运行 WildAgent 的独立探针：

```powershell
.\.venv\Scripts\python.exe -m scripts.rag.migrate_embedding_index probe
```

它只执行标准协议请求：

```http
POST /embeddings

{
  "model": "候选模型",
  "input": ["WildAgent Embedding model migration probe"],
  "encoding_format": "float"
}
```

它不导入 Agent、不打开 Chroma、不扫描知识库，也不会启动全量同步。成功时记录：

- 返回维度；
- 单条请求耗时；
- 实际模型名与服务地址。

只有这一步成功，才进入全量建库。

如果后端无法启动，但需要先检查磁盘索引，可以运行完全离线的审计：

```powershell
.\.venv\Scripts\python.exe -m scripts.rag.migrate_embedding_index status
```

它直接只读打开 `chroma.sqlite3`，不会导入 OpenAI、LangChain、Chroma 或 Agent，也不会发起同步。
签名不一致、存在缺失文件或失效文件时，它会输出 `完整性结论: incomplete` 并返回非零退出码。

## 5. 第三步：构建独立新集合

```powershell
.\.venv\Scripts\python.exe -m scripts.rag.migrate_embedding_index build `
  --collection-name wild_knowledge_base_qwen37_v1
```

脚本会：

1. 再做一次单条探针；
2. 扫描正式知识库；
3. 使用生产 `MarkdownChunker` 分块；
4. 用新模型分批计算所有向量；
5. 写入新 collection；
6. 检查待同步数必须为 0；
7. 检查实际索引数量必须等于当前分片总数；
8. 输出新的索引签名与切换配置。

目标 collection 与当前正式 collection 相同时，脚本会拒绝执行。这个限制用于保护旧索引。

## 6. 第四步：验证新索引

至少验证三层：

### 数量完整性

`build` 命令结束前已经强制校验“当前分片总数 = 新集合实际索引数”，数量不一致会返回失败，不会提示你切换 `.env`。

切换 `RAG__COLLECTION_NAME` 并重启服务后，再运行：

```powershell
.\.venv\Scripts\python.exe -m scripts.rag.check_sync_status --wait-seconds 120
```

必须看到：

```text
同步阶段: ok
仍待同步分片: 0
```

“数据库里已经有几百条”不能证明完整，必须把当前切块总数和实际索引数进行比较。

### 检索质量

把 `RAG__COLLECTION_NAME` 临时指向新集合后，用相同评测集运行：

```powershell
.\.venv\Scripts\python.exe scripts\rag\eval_retrieval.py
```

对比新旧：

- Hit@K；
- Recall@K；
- MRR；
- 关键问题的 Top-K 来源；
- 正例和反例距离分布。

不同模型的距离绝对值不能直接横向比较。需要分别校准门禁：

```powershell
.\.venv\Scripts\python.exe scripts\rag\calibrate_retrieval_gate.py
```

### Agent 使用效果

最后再验证真实建筑生成节点是否把正确片段放进 Prompt，并正确使用。检索指标提高不等于最终建筑质量自动提高。

## 7. 第五步：切换和回滚

验证通过后，把新模型和新集合同时写入 `.env`：

```dotenv
EMBEDDING__NAME=新模型
EMBEDDING__API_KEY=新密钥
EMBEDDING__BASE_URL=https://新地址/v1
RAG__COLLECTION_NAME=wild_knowledge_base_qwen37_v1
```

重启服务后查看状态和代表性查询。

若出现回归，恢复这一整组：

```dotenv
EMBEDDING__NAME=旧模型
EMBEDDING__API_KEY=旧密钥
EMBEDDING__BASE_URL=https://旧地址/v1
RAG__COLLECTION_NAME=旧集合
```

不要只恢复模型名而继续查询新集合，也不要只恢复旧集合却仍用新模型查询。

## 8. “卡住不动”时怎样定位

按阶段判断，不要直接反复重启：

| 最后可见位置 | 说明 | 下一步 |
|---|---|---|
| 探针都失败 | 尚未到 Chroma | 看 HTTP 状态、鉴权、模型 ID、进程网络环境 |
| 探针成功，扫描失败 | 文档或切块层 | 先运行分片预览 |
| 显示“请求 Embedding”后长时间等待 | 上游延迟或批量限制 | 查看超时心跳、单批数量和请求耗时 |
| 已写入部分向量，状态仍为 degraded | 部分同步 | 查看 `pending_chunks`，修复后继续增量同步 |
| 签名不一致 | 模型/地址/切块参数变化 | 换新 collection，不要把新旧向量混在一起 |
| 索引完整但查询报维度错 | 查询模型与建库模型不一致 | 成对检查模型配置和 collection |
| Top-K 有结果但来源错误 | 语义检索质量问题 | 看切块、metadata、评测集和新模型召回 |

WildAgent 修复后的后台同步不会再把“仍有待同步块”的部分索引标成 `ok`。它会保持 `degraded` 并继续有限重试，状态命令会明确显示剩余数量。

## 9. Notebook 分单元格练习：双集合迁移

在 `01.basic.ipynb` 中建立 `# 第 9 章：模型迁移`。真实模型迁移费用高、耗时长，先用二维旧模型和三维新模型证明“模型与 Collection 必须成对切换”。

### Cell 1：定义新旧两个假模型

依赖：公共初始化 Cell。

```python
from pathlib import Path
import tempfile

from embedding_lab.chunking import Chunk
from embedding_lab.vector_store import ChromaVectorStore


class OldModel:
    name = "old-model-2d"

    def _vector(self, text: str) -> list[float]:
        return [1.0, 0.0] if "幕墙" in text else [0.0, 1.0]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vector(text)


class NewModel:
    name = "new-model-3d"

    def _vector(self, text: str) -> list[float]:
        return [1.0, 0.0, 0.0] if "幕墙" in text else [0.0, 1.0, 0.0]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vector(text)
```

### Cell 2：准备同一份知识 Chunk

依赖：Cell 1。

```python
chunks = [
    Chunk(
        id="wall-001",
        text="幕墙需要通过 parentWall 挂接",
        metadata={
            "namespace": "migration_test",
            "source": "walls.md",
            "heading": "幕墙",
            "doc_scope": "generation",
        },
    ),
    Chunk(
        id="stair-001",
        text="楼梯连接上下楼层",
        metadata={
            "namespace": "migration_test",
            "source": "stairs.md",
            "heading": "楼梯",
            "doc_scope": "generation",
        },
    ),
]
```

### Cell 3：建立旧模型基线

依赖：Cell 2。

```python
persist_dir = Path(tempfile.mkdtemp(prefix="studyagent-migration-"))
old_model = OldModel()
new_model = NewModel()

old_store = ChromaVectorStore(
    persist_dir=persist_dir,
    collection_name="knowledge_old_model_v1",
    namespace="migration_test",
    index_signature="old-model-2d-chunk-v1",
)
old_store.sync(chunks, old_model)
old_baseline = old_store.query("幕墙如何挂接？", old_model, k=1)
assert old_baseline[0].id == "wall-001"
print("旧模型基线：", old_baseline[0])
```

### Cell 4：用新模型构建独立集合

依赖：Cell 2、Cell 3。

```python
# 新模型写入独立集合，旧集合仍保留。
new_store = ChromaVectorStore(
    persist_dir=persist_dir,
    collection_name="knowledge_new_model_v1",
    namespace="migration_test",
    index_signature="new-model-3d-chunk-v1",
)
new_store.sync(chunks, new_model)
new_result = new_store.query("幕墙如何挂接？", new_model, k=1)
assert new_result[0].id == "wall-001"

assert old_store.status()["count"] == 2
assert new_store.status()["count"] == 2
print("新模型结果：", new_result[0])
```

### Cell 5：故意用新模型查询旧集合

依赖：Cell 4。

```python
# 故意用三维新模型查询二维旧集合，验证向量空间不兼容。
try:
    old_store.query("幕墙如何挂接？", new_model, k=1)
except Exception as exc:
    print("预期的维度或查询错误：", type(exc).__name__, exc)
else:
    raise AssertionError("新模型不应直接查询旧模型集合")
```

### Cell 6：执行回滚

依赖：Cell 5。

```python
# 回滚不是重建，而是把旧模型和旧集合一起恢复。
rollback_result = old_store.query("幕墙如何挂接？", old_model, k=1)
assert rollback_result[0].id == "wall-001"

print("回滚结果：", rollback_result[0])
print("旧集合仍有：", old_store.status()["count"], "条")
print("新集合已有：", new_store.status()["count"], "条")
```

这个练习需要你明确说出：

```text
旧模型 + 旧集合 = 可用
新模型 + 新集合 = 可用
新模型 + 旧集合 = 不兼容
回滚 = 同时恢复旧模型和旧集合
```

二维与三维只是为了让错误更明显。真实迁移中，即使新旧模型维度相同，也仍可能属于完全不同的向量空间，所以仍应重建独立集合并重新评测。

### 再替换成真实模型时

完成假模型演练后，再把迁移拆成三次人工验证：

1. 只发送一条文本，记录新模型维度和耗时；
2. 用新集合完成全量建库，验证分片数等于索引数；
3. 用同一套问题分别查询新旧集合，比较 Recall@K 和来源排名。

只有三步都通过，才切换正式配置。

### Cell 7：用 Markdown 写总结

记录旧模型与旧集合、新模型与新集合、错误组合和回滚组合，并说明为什么“维度相同”仍不能证明模型兼容。

## 10. 当前 WildAgent 的诊断快照（2026-09-06）

本次只读检查得到：

```text
Embedding 模型：qwen3.7-text-embedding-flash
集合：wild_knowledge_base
维度：1024
索引签名：与当前模型和切块配置一致
已写入向量：431
知识库候选文件：44
索引 metadata 覆盖文件：39
缺少文件：5
```

缺少的来源是：

- `components/structural-components.md`；
- `recipes/component-building-matrix.md`；
- `building_types/industrial/factories-and-warehouses.md`；
- `building_types/public/education-office-culture.md`；
- `building_types/residential/villas.md`。

这说明模型切换已经触发过重建，但当前集合存在部分同步迹象。不能因为集合已有 431 条记录就把迁移判定为完成。

当前 Codex 终端还存在 Windows `WinError 10106`，因此无法从新进程完成真实补齐和检索评测；这属于本轮运行时验证限制。修复主机网络栈或换到能正常启动 Python/OpenAI SDK 的终端后，应先运行 `probe`，再继续独立新集合迁移。

## 11. 完成检查

- [ ] 我能说明哪些配置变化必须重建索引
- [ ] 我能先做单条模型探针，再决定是否全量建库
- [ ] 我能使用独立新集合保护旧索引
- [ ] 我能验证新旧集合的数量完整性和检索质量
- [ ] 我知道模型与集合必须成对切换、成对回滚
- [ ] 我不会因为维度相同就判断两个模型兼容
