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

