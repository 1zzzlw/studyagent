# 第 7 章：回到 WildAgent 看生产链路

## 本章目标

把教学模块中的每个概念映射回 WildAgent 当前真实代码，知道哪些是核心流程，哪些是生产增强。

## 1. 主链路

WildAgent 当前主链路可以压缩为：

```text
storage/knowledge_base/**/*.md
  → collect_markdown_paths
  → MarkdownChunker
  → OpenAICompatibleEmbeddingFunction
  → RAGSpecLoader.sync_index
  → Chroma PersistentClient
  → retrieve / retrieve_many / load_many
  → Agent 节点 Prompt
  → Chat Model
```

核心实现位于：

```text
WildAgent/wild-server/app/spec/loader.py
WildAgent/wild-server/app/services/agent_service.py
```

## 2. 一一对应关系

| 学习模块 | WildAgent | 职责 |
|---|---|---|
| `documents.py` | `collect_markdown_paths()` | 递归扫描知识库 |
| `chunking.py` | `MarkdownChunker` | 标题、实体与长度分块 |
| `embeddings.py` | `OpenAICompatibleEmbeddingFunction` | 批量请求向量 |
| `vector_store.py::sync()` | `RAGSpecLoader.sync_index()` | 增量新增、删除和写入 |
| `vector_store.py::query()` | `retrieve()` / `retrieve_many()` | 单意图或多意图召回 |
| `service.py` | `AgentService._create_spec_loader()` | 按配置组装依赖 |

## 3. WildAgent 的初始化与启动

`AgentService` 构造时先调用 `_create_spec_loader()`：

1. 读取 `RAG` 与 `EMBEDDING` 配置；
2. 创建真实 Embedding，缺少配置时可按策略使用 Hash fallback；
3. 创建 `RAGSpecLoader(auto_sync=False)`；
4. 服务不等待远程 Embedding；
5. `RAG__AUTO_SYNC=true` 时启动后台增量同步；
6. RAG 初始化失败时退回 `FileSpecLoader`。

因此 WildAgent 的“后端能启动”与“完整向量索引已同步”不是同一状态。后台同步未完成时，可以保留基础规范兜底。

## 4. WildAgent 的首次与增量写入

`sync_index()` 会：

- 读取并切分当前知识库；
- 读取当前 namespace 已有 ID；
- 删除失效 ID；
- 只对新增块调用 Embedding；
- 每 10 块一批写入；
- metadata 单独变化时只更新 metadata，不重复算向量；
- 同步结束后清理检索缓存。

生产实现还记录批次进度、超时、重试和部分可用状态。教学模块只保留最容易看懂的增量集合差。

## 5. WildAgent 的查询调用

不同 Agent 节点会根据自己的任务发起多个查询。例如总体建筑方案节点会分别查询：

- 建筑类型知识；
- 组合配方；
- 体量、结构轴网与立面细节模式。

这些查询通过 metadata 限定不同 `doc_type`，再由 `load_many()` 合并、去重、裁剪，并拼进该节点 Prompt。

所以真实调用不是：

```text
用户一句话 → 全知识库模糊查一次
```

而更接近：

```text
用户需求
  → 拆成多个检索意图
  → 每个意图带业务过滤
  → 合并唯一片段
  → 交给负责当前阶段的 Agent 节点
```

## 6. 生产代码多出来的能力

教学模块没有复制以下内容：

- frontmatter / `rag-meta` 业务元数据继承；
- JSON、表格等原子内容保护；
- 父分片与相邻片段扩展；
- 内容哈希去重、成熟度惩罚和规则重排；
- namespace 与访问权限过滤；
- 检索门禁、RAG Trace、缓存；
- 后台线程、超时心跳、有限重试和降级。

它们都是重要的生产能力，但都建立在前六章那条基本链路之上。

## 7. 不要误解 HybridRetriever

WildAgent 仓库中存在 `HybridRetriever` 代码，但当前 Agent 主路径使用的核心仍是 `RAGSpecLoader` 的向量检索。阅读到某个类存在，不等于它已经接入线上主链路。判断功能是否生效，要继续追踪真实构造和调用位置。

## 8. Notebook 分单元格练习：只读定位生产源码

在 `01.basic.ipynb` 中建立 `# 第 7 章：生产链路对照`。下面的 Cell 只读取 WildAgent 源码并定位关键符号，不写入、不导入、更不会启动 WildAgent。

### Cell 1：确定只读源码路径

依赖：公共初始化 Cell。

```python
AGENT_PROJECT_ROOT = PROJECT_ROOT.parent
WILD_ROOT = AGENT_PROJECT_ROOT / "WildAgent"

loader_path = WILD_ROOT / "wild-server" / "app" / "spec" / "loader.py"
service_path = (
    WILD_ROOT
    / "wild-server"
    / "app"
    / "services"
    / "agent_service.py"
)

assert WILD_ROOT.exists(), f"没有找到 WildAgent：{WILD_ROOT}"
print("只读参考项目：", WILD_ROOT)
```

### Cell 2：准备要定位的符号

依赖：Cell 1。

```python
checks = {
    loader_path: [
        "class OpenAICompatibleEmbeddingFunction",
        "class MarkdownChunker",
        "class RAGSpecLoader",
        "def sync_index",
        "def retrieve(",
        "def retrieve_many",
        "def load_many",
    ],
    service_path: [
        "def _create_spec_loader",
        "RAGSpecLoader(",
        "start_background_sync()",
        "FileSpecLoader(",
    ],
}
```

### Cell 3：输出符号所在行

依赖：Cell 2。

```python
for path, symbols in checks.items():
    assert path.exists(), f"源码文件不存在：{path}"
    text = path.read_text(encoding="utf-8")
    print(f"\n文件：{path.relative_to(WILD_ROOT)}")

    for symbol in symbols:
        position = text.find(symbol)
        assert position >= 0, f"没有找到符号：{symbol}"
        line_number = text[:position].count("\n") + 1
        print(f"line {line_number:>4}: {symbol}")
```

运行后，不要停留在“找到了类”。请按下面顺序人工阅读：

1. `_create_spec_loader()` 怎样读取配置并创建 `RAGSpecLoader`；
2. `RAGSpecLoader.__init__()` 是否立即同步；
3. `start_background_sync()` 在什么条件下调用；
4. `sync_index()` 怎样计算新增、失效和 metadata 变化；
5. `retrieve()` 怎样生成问题向量并查询；
6. Agent Service 在哪里调用 `load_many()` 或 `retrieve_many()`。

### 用 `rg` 继续追调用方

在终端执行：

```powershell
rg -n "_create_spec_loader|start_background_sync|sync_index" E:\AgentProject\WildAgent\wild-server\app
rg -n "retrieve_many|load_many|\.retrieve\(" E:\AgentProject\WildAgent\wild-server\app
```

把结果记录成“定义位置 → 构造位置 → 调用位置”，不要因为类存在就判断它一定在主链路运行。

### Cell 4：主动制造定位错误

依赖：Cell 2。把 `checks` 中的一个符号临时改成 `"def method_not_exists"`，再重新运行 Cell 3。它应该触发 `AssertionError`，告诉你源码快照与文档假设不一致。观察错误后立即恢复 Cell 2 并重新运行。

这里的失败不是生产 RAG 失败，而是“源码导读文档需要重新核对”的信号。

### Cell 5：用 Markdown 写总结

记录每个符号的“定义位置、构造位置、真实调用位置”，并注明哪些结论来自源码、哪些只是你的推断。

## 9. 完成检查

- [ ] 我能只读定位 WildAgent 的 Embedding、Chunker 和 Loader
- [ ] 我能区分符号定义、对象构造和真实调用
- [ ] 我能解释前台初始化与后台同步的边界
- [ ] 我能指出查询结果进入 Agent Prompt 前经过哪些方法
- [ ] 我确认整个练习没有修改 WildAgent
