# 记忆系统

负责形成、关联、提取、反思、有效性与衰减强化。人物当前状态和情绪由其他系统提供。

## 三层记忆的存储分工

1. **完整历史记录**：SQLite 保存用户与角色的实际发言，应用编排负责追加，作为可追溯来源。
2. **短期记忆**：通过历史仓库读取近期消息，组织成内存中的 Message 列表或 ShortTermContext；滑出窗口不删除原话。
3. **长期记忆**：保持本系统的事件、反思、证据和关联结构。建议 SQLite 保存主数据，Chroma 按 memory_id 建立候选检索索引。

短期记忆第一版可以复用 Message，只有窗口这一层的聚合结构；不需要复制长期记忆的整套字段。窗口条数之外，后续还应控制 token 预算。

初版 [初始化 SQL](../../../init.sql) 已包含长期记忆、证据、关联、保留状态和运行日志；实际用法见 [运行说明](../../../README.md)。

## 内部分层与规划文件

| 层 | 规划文件 | 职责 |
| --- | --- | --- |
| `domain` | `memory_node.py` | 正文、类型、时间、来源、重要性与有效性 |
| `domain` | `relations.py` | 来源消息、反思证据与普通语义关联 |
| `domain` | `retention_state.py` | 初始强度、强化基准、稳定性和回忆次数 |
| `domain` | `recall_view.py` | 本轮回忆内容、强度、清晰程度、可用细节 |
| `domain` | `short_term_context.py` | 复用 Message 组织本轮短期窗口 |
| `domain` | `processing_state.py` | 关联处理进度、反思待处理状态 |
| `application` | `service.py` | 对外提供 remember、recall、record_usage、consolidate |
| `application` | `formation.py` | 从真实观察形成值得保留的 event |
| `application` | `retrieval.py` | 候选检索、证据和关联扩展、范围过滤 |
| `application` | `short_term.py` | 从历史仓库选择近期窗口，限制范围并维持顺序 |
| `application` | `reflection.py` | 借鉴 GA，生成有证据的 thought |
| `application` | `association.py` | 借鉴 A-Mem，维护 context、tags 与普通关联 |
| `engines` | `ebbinghaus.py` | 初始化、时间衰减、实际回忆后的强化 |
| `ports` | `repository.py` | 正文、证据、生命周期与进度的存取需求 |
| `ports` | `vector_index.py` | 按查询返回候选记忆 ID 与相关性 |

初版将数据结构合并在 `domain/models.py`，用例合并在 `application/service.py`，衰减引擎在 `engines/ebbinghaus.py`。表中更细的文件划分仍是规划，不代表每个文件均已创建。

## 核心记忆数据

`MemoryNode` 规划保留：

- 唯一 ID、所属角色 ID。
- `event / thought / chat` 类型。
- 形成时间、可选事件时间与有效截止时间。
- 正文，以及需要时的主谓宾。
- 关键词、context、tags、category。
- 内容重要性。
- 来源观察、实际来源消息 ID。
- thought 的证据记忆 ID，以及反思层级。
- 普通相关记忆 ID。
- 明确纠正或失效的引用和有效性。

`chat` 类型主要作为一次真实交流的来源节点，引用原始消息。全量原话保存在对话档案中，避免在每条记忆里反复复制整段历史。

## 移出的字段

| 原字段 | 新归属 |
| --- | --- |
| `attention` | 人物状态系统的 AttentionAppraisal |
| `emotional_impact` | 情感系统的 EmotionAppraisal |
| 当前精力、活动、环境、情绪 | 对应系统的当前快照 |
| `initial_strength`、`strength_after_recall`、`stability_days`、`recall_count`、衰减基准时间 | 本系统 RetentionState |
| `association_ready`、`reflected` | 本系统 ProcessingState |
| `evolution_history` | 独立维护记录，保留变化依据 |

注意：把 `RetentionState` 从正文类中拆出，仍然是在记忆系统内部拆分，并未新增一个业务系统。

## 三类引用

| 引用 | 含义 | 方向 |
| --- | --- | --- |
| `source_message_ids` | 哪些实际发言产生了这条记忆 | 记忆指向原话 |
| `evidence_memory_ids` | 这条新认识根据哪些已有记忆推导 | thought 指向依据 |
| `related_memory_ids` | 哪些记忆可以联系起来查看 | 第一版普通关联按双向理解 |

不继续使用 `filling` 把聊天原话、证据 ID 和其他补充内容混在一个字段中。

任何生成的引用必须来自本次提供的真实候选集合；相似不意味着同一事件，相关也不自动意味着因果。

## 记忆形成

1. 根据观察和有限上下文提炼记忆草稿，保留人称方向、计划条件和不确定性。
2. 评价内容本身的重要性。
3. 使用外部提供的注意力与情感冲击，初始化 `RetentionState`。
4. 保存原文证据和记忆正文。
5. 为新记忆维护语义说明及关联。

注意力可以影响本次保留哪些细节，但不能改写用户原话档案。

## 衰减强化引擎

引擎按参数计算：

~~~text
initialize(attention, emotional_impact, importance) -> RetentionState
current_strength(retention, now) -> float
reinforce(retention, now) -> RetentionState
~~~

正文和算法分开，服务在初始化时接收引擎实例。第一版继续借鉴已有 Ebbinghaus 实验规则；这些是工程模拟参数，不称为统一心理学定律。

当前强度不与语义相似度直接加权成同一个分数。候选相关性与回忆清晰度分别输出。

过去形成时的情感影响初始编码；角色此刻的疲惫或情绪可以影响本轮回忆表现，不应无条件永久降低所有旧记忆的保留基准。

## 回忆视图

`RecallItem` 是本轮临时输出，包含记忆 ID、允许使用的内容、来源提示、当前强度与清晰程度。

低强度不等于低事实可信度，不允许把日期、人名随意改成另一个值。后续如需要真实省略细节，应完善回忆整理策略，而不是反复覆盖持久记忆正文。

被纠正或过期的依据不能通过 thought 绕回回答；依据的有效性与可回忆程度应在组织视图时检查。

## GA 反思与 A-Mem 关联

反思输入多条有来源的经历，输出保留不确定性的 thought，并保存证据。没有新认识时允许为空，不为了每轮产生内容而重复改写旧话。

关联维护查找候选邻居，生成语义说明、标签与普通关联；初版只允许维护邻居的描述性元数据，不随意改写正文和事实有效性。

反思按新增事件数量或重要性等条件触发。每次整理最多触发一轮反思，不因新 thought 继续无限反思。

## 对外接口草图

~~~text
recall(query, recent_messages, now) -> list[RecallItem]
remember(observation, attention_score, emotional_impact) -> list[memory_id]
record_usage(used_memory_ids, allowed_ids, now) -> None
consolidate(new_memory_ids, now) -> MaintenanceResult
~~~

实际采用信号来自对话输出，并由程序校验候选范围。该信号用于工程记账，不能仅靠模型自报就证明所有语义使用都完全准确。

参考来源与原文件链接见 [总体设计](../../README.md)。
