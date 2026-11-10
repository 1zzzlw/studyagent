# 记忆结构实验 v2

借鉴 Generative Agents 的 `ConceptNode` 和 `AssociativeMemory`，补充 `05.chroma.py` 的衰减强化字段与算法。独立实现，不改动两个参考项目，也不迁移旧 Chroma 数据。

## 启动

这是交互式 Python 脚本，不需要启动服务。在 PowerShell 中运行：

```powershell
cd E:\AgentProject\studyAgent
.\.venv\Scripts\python.exe .\12-memory\v2\main.py
```

沿用项目根目录 `.env` 的 `LLM_MODEL`、`LLM_API_KEY`、`LLM_BASE_URL`。本版使用与 05 一致的 OpenAI 兼容文字接口，不需要任何 `EMBEDDING_*` 配置。

`LLM_MAX_TOKENS` 可选，默认 8192。`LLM_REASONING_EFFORT` 仅在当前模型支持时填写，例如 `low`，否则留空。使用文本 JSON 和 Pydantic 解析，不强制依赖 function calling。

首次启动记忆为空。菜单支持对话、时间流逝、记忆概览和保存退出。只在输入自己的对话后调用真实模型；没有预置对话或测试数据。运行数据自动保存在本目录 `storage/nodes.json`，重启后加载。

## 文件职责与阅读顺序

```text
main.py                              固定人物状态、插件接入、交互菜单
memory_structures/concept_node.py    记忆字段，不包含算法
associative_memory.py                add_event / add_thought / add_chat、索引和存档
engines/ebbinghaus.py                初始强度、时间衰减、回忆强化、清晰状态
llm.py                              回答和记忆整理的提示词、输出结构与模型调用
storage/nodes.json                  首次运行后产生的独立存档
```

## 字段如何合并

冲突的名称优先采用 Generative Agents：

| 05 原字段 | v2 字段 | 说明 |
| --- | --- | --- |
| `memory_id` | `node_id` | 唯一编号 |
| `content` | `description` | 记忆正文 |
| `created_at` | `created` | 形成时间 |
| `last_recalled_at` | `last_accessed` | 创建时为 created，此后仅在确认采用旧记忆时更新 |
| 草稿的 `importance` | `poignancy` | 沿用 1～10 分；初始化强度时除以 10 |

原项目其余节点字段继续保留：`node_count`、`type_count`、`type`、`depth`、`expiration`、`subject`、`predicate`、`object`、`keywords`、`filling`、`embedding_key`。本版不用向量，所以 `embedding_key` 为 None，没有创建向量客户端或向量缓存。

补充字段：`source_observation_id`、`attention`、`emotional_impact`、`initial_strength`、`strength_after_recall`、`stability_days`、`recall_count`、`status`、`supersedes_id`。两个写入序号不是回忆次数；`depth` 不是强度；关键词计数不是强度。

所有时间使用带时区的 UTC 时间；本版存档是独立格式，不直接加载旧项目的 JSON。

## 记忆管理与关联

- 事件 `event`：经历或用户明确表述，`filling` 记录相关节点 ID。
- 想法 `thought`：有来源的主观认识，`filling` 记录证据 ID，深度比证据最高层多 1。
- 聊天 `chat`：程序原样保存实际的双方发言，`filling` 是 `(说话人, 原话)` 列表。

每轮先生成回答，只对回答实际采用的旧记忆登记回忆，再保存真实聊天。随后模型可以提炼事件和想法，也可以不提炼；新节点会关联本轮聊天节点。模型不能编造节点 ID，程序会检查关联和纠正目标。

只有明确纠正旧认识才使用 `supersedes_id`。以前真实、后来变化的状态不等于当初错误；历史聊天原话不被纠正覆盖。原节点始终保留，失效认识不作为当前回答上下文。

本版没有语义召回：每轮只提供最近 8 条未到期、未被纠正的记忆。淡忘记忆仍可提供，强度主要用于提示回答的清晰程度，不与相似度混合评分。关键词索引的方法也保留，供后续扩展使用。

## 插件如何启停

`main.py` 默认启用：

```python
memory = AssociativeMemory(engine=EbbinghausMemoryEngine())
```

停用只需改为：

```python
memory = AssociativeMemory()
```

记忆结构、写入、关联和存档仍可使用。停用时不计算或更新衰减清晰状态，仍记录真实回忆次数和时间；保留存档中的引擎字段，方便之后重新启用。该开关不会抹去过去的时间，重新启用后仍按最后回忆时间计算。

引擎不拥有独立仓库，不调用模型或数据库，只操作同一条 `ConceptNode`：

```text
新节点 → register：初始化强度和稳定性
取上下文/查看/时间流逝 → step：刷新清晰状态，不增加次数
回答确认采用旧节点 → recall：增加次数，更新稳定性与基准时间
```

衰减和强化沿用 05：`强度 = 上次基准强度 × exp(-经过天数 / 稳定性天数)`。强化使用间隔系数 `1 - exp(-经过天数 / 稳定性天数)`，间隔越短，单次增益越小。只在新节点上初始化；读取存档不会重置强度。

时间流逝沿用旧菜单的操作方式：把已有节点的 `created`、`last_accessed` 和可选 `expiration` 一起前移，不修改系统时钟。低强度只标为 `forgotten`，不删除正文或关联；`expiration` 到期与淡忘不同，到期记忆不进入回答上下文。

## 初版范围

本版关注结构、关联和可选衰减插件。想法在交流整理时形成，尚未实现独立的异步反思 Agent、关系图遍历检索或自动状态变化。没有自动重试；模型输出或解析失败会显示错误，已经记录的真实交流会保存。
