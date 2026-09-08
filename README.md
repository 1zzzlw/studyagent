# studyAgent

本项目是根据 WildAgent 项目整理的学习笔记和最小示例，目标不是复制 WildAgent，而是沿着它的真实调用链，逐步熟悉一个完整 Agent 项目的所有核心模块。

学习时遵循以下顺序：

```text
先运行最小示例
→ 理解输入、输出和状态变化
→ 对照 WildAgent 源码
→ 制造错误并练习排查
→ 最后补充测试和学习笔记
```

## 一、整体学习路线

WildAgent 的主要运行链路可以简化为：

```text
用户请求
→ WebSocket 接入
→ 会话与后台任务
→ AgentService
→ LangGraph 状态与路由
→ 节点执行
→ LLM / RAG / Tools
→ Blueprint 生成
→ 合并、校验、修复
→ 结果推送
→ 前端编译与 Three.js 重建
```

本项目按照这条链路拆分学习模块，不需要等遇到问题以后再决定学什么。

## 二、当前已有模块

| 模块 | 学习目标 | 当前状态 |
| --- | --- | --- |
| `01-tracing` | 使用 LangSmith 观测 Agent 调用，快速认识完整执行流程 | 已创建 |
| `02-rag` | 建立最小 RAG，理解检索结果为什么能进入模型上下文 | 已创建 |
| `03-evaluation` | 使用 Dataset 和 Experiment 评价 RAG/Agent 输出 | 已创建 |
| `04-langgraph-basics` | 理解节点、边、State 和条件路由 | 已创建 |
| `05-studio` | 使用本地 Agent Server 和 LangGraph Studio 调试 Graph | 已创建 |
| `06-chroma-basics` | 学习 Chroma 集合、CRUD、metadata、持久化、增量同步和检索 | 学习中 |
| `07-embedding-basics` | 学习文档/问题向量化、向量空间一致性和模型切换 | 已完成 |
| [`08-websocket-request-flow`](08-websocket-request-flow/README.md) | 从前端消息、WebSocket 接收、持久化任务一路跟踪到 LangGraph 节点和事件回传 | 已创建，待学习 |
| [`11-model-client`](11-model-client/README.md) | 学习聊天模型配置、客户端工厂、非流式/流式调用、统一响应和错误处理 | 已创建，学习顺序后移 |

Chroma 和 Embedding 是前后衔接的两个独立模块：

```text
06-chroma-basics：向量怎样保存、管理和查询
↓
07-embedding-basics：向量怎样生成，以及换模型时怎样迁移
```

聊天模型与向量模型也必须使用两套独立配置。它们可以来自不同供应商，项目不再让 Embedding 复用 `LLM_BASE_URL` 或 `LLM_API_KEY`：

| 用途 | 模型 | 接口地址 | 密钥 |
|---|---|---|---|
| 对话、Agent | `LLM_MODEL` | `LLM_BASE_URL` | `LLM_API_KEY` |
| 文档和问题向量化 | `EMBEDDING_MODEL` | `EMBEDDING_BASE_URL` | `EMBEDDING_API_KEY` |

腾讯云 TokenHub 的填写示例见根目录 `.env.example`。真实密钥只写入被 Git 忽略的 `.env`，不要写进 Notebook 或提交到仓库。

`07-embedding-basics` 已完成，WildAgent 也已能启动。当前不急着直接修改节点，而是先按一条真实请求纵向熟悉项目。近期顺序调整为：

```text
08-websocket-request-flow：先知道消息从哪里进入、怎样找到节点
↓
09-architecture-and-patterns：再看模块职责、依赖方向和已有设计模式
↓
10-langgraph-state-node-flow：深入节点之间怎样路由和传递状态
↓
11-model-client：最后进入节点内部的聊天模型调用细节
```

当前近期目标是完成08模块，能够独立跟踪下面这条主链：

```text
wild-web agentBridge
→ /ws/agent
→ agent_websocket() 接收并解析消息
→ generation_job_service.start_job()
→ 持久化任务 runner
→ _handle_with_langgraph()
→ graph.astream_events()
→ 具体 LangGraph 节点
→ DurableEventSink / publish_event()
→ WebSocket 事件返回前端
```

## 三、后续计划模块

以下目录属于规划，不代表已经实现。学习到对应阶段时再创建，避免提前堆积空模块。

| 编号 | 计划模块 | 学习重点 | WildAgent 对照代码 |
| --- | --- | --- | --- |
| 09 | `architecture-and-patterns` | 画模块边界和依赖方向，再从真实代码识别 Factory、Adapter、Registry、Facade、Event Sink 等模式 | `app/api/`、`app/services/`、`app/agent/`、`model_client.py`、`component_registry.py` |
| 10 | `langgraph-state-node-flow` | `GenerationState`、节点局部返回、状态合并、条件边、事件流和 Checkpoint | `graph_state.py`、`graph.py`、`classifier_node.py`、`chat_node.py` |
| 12 | `structured-output` | Prompt、JSON/Pydantic 输出、解析和格式恢复 | `prompts.py`、`format_recovery.py`、`schemas/` |
| 13 | `tools-and-protocol` | Tool 定义、参数校验、工具结果和事件协议 | `tools/`、`protocol.py` |
| 14 | `advanced-rag` | 查询改写、混合检索、过滤、引用、门禁和校准 | `agent/rag/`、`rag_gate.py` 等 |
| 15 | `service-session-jobs` | AgentService、Session、后台任务、Checkpoint、暂停和恢复怎样协作 | `agent_service.py`、`session_service.py`、`generation_job_service.py` |
| 16 | `websocket-reliability` | 在08主链基础上深入心跳、断线重连、事件持久化和补发 | `ws_agent.py`、`ws_heartbeat.py`、`generation_job_service.py` |
| 17 | `validation-repair` | 校验器、错误分类、确定性修复和回调重试 | `validators/`、`repair_tools.py`、`callback_node.py` |
| 18 | `blueprint-pipeline` | 建筑规划、楼层、构件、合并和最终校验 | `architecture_node.py`、`floor_*`、`merge_node.py` |
| 19 | `frontend-delivery` | Agent 事件如何进入前端并完成场景重建 | `agentBridge`、Store、`wild-compiler`、`wild-core` |
| 20 | `testing-and-deployment` | 单元测试、回归测试、配置检查、日志和部署排障 | `tests/`、配置模块和部署脚本 |

这个顺序有意把08和16拆开：08只解决“我怎样从入口找到节点”，16再学习心跳、重连和事件补发等可靠性细节。09也不是收集设计模式名词，而是先用真实导入关系判断职责和耦合，再决定哪些结构值得保留、合并或简化。

## 四、25 个学习日计划

建议每天投入 1.5～2 小时，每天只解决一个核心问题。

### 第一周：Chroma 与 Embedding

| 天数 | 学习任务 | 当天产出 |
| --- | --- | --- |
| Day 1 | 学习 Chroma client、collection 和基础 CRUD | 最小 collection 操作记录 |
| Day 2 | 学习 document、embedding、metadata、ID 和过滤查询 | Chroma 数据结构图 |
| Day 3 | 学习本地持久化、重复写入和增量同步 | `06-chroma-basics` 学习总结 |
| Day 4 | 学习文档向量、问题向量和相似度 | Embedding 最小实验 |
| Day 5 | 学习模型一致性、索引签名、迁移和回滚 | `07-embedding-basics` 学习总结 |

完成标准：能够区分“Embedding 负责生成向量”和“Chroma 负责保存、管理、检索向量”。

### 第二周：请求入口与架构地图

| 天数 | 学习任务 | 当天产出 |
| --- | --- | --- |
| Day 6 | 阅读前端 `agentBridge`、`/ws/agent` 和 `agent_websocket()` 接收循环 | WebSocket 消息类型与分发表 |
| Day 7 | 跟踪 `user_message → start_job → runner → _handle_with_langgraph` | 请求进入 Graph 前的调用链图 |
| Day 8 | 跟踪 `astream_events → 节点事件 → publish_event → 前端`，区分首次执行与恢复 | 一次请求往返的完整时序图 |
| Day 9 | 盘点 `api / services / agent / tools / spec` 的职责和主要导入方向 | WildAgent 包结构与依赖图 |
| Day 10 | 从真实代码识别设计模式与耦合点，只形成候选简化清单 | 模式证据表与首批优化候选 |

完成标准：能够从一条 `user_message` 找到实际运行节点，再找到节点产生的事件怎样返回前端；能够用源码证据说明主要模块职责，而不是依靠 AI 问题总结直接改代码。

### 第三周：LangGraph 信息传递与模型调用

| 天数 | 学习任务 | 当天产出 |
| --- | --- | --- |
| Day 11 | 阅读 `GenerationState`，区分初始状态、节点读取字段和局部返回 | 状态字段来源表 |
| Day 12 | 学习节点返回、Reducer、普通边、条件边和结束条件 | Notebook 状态合并与路由实验 |
| Day 13 | 跟踪 `classifier → chat/edit/generate` 分支和 `astream_events` 事件 | 可解释的节点路径图 |
| Day 14 | 完成11模块第1～3章：模型配置、工厂、消息和非流式调用 | Notebook 非流式调用记录 |
| Day 15 | 完成11模块第4～5章：流式响应和统一结果 | Notebook 流式拼接与 `ModelResult` 实验 |

学习 LangGraph 时先用 `classifier_node` 和 `chat_node` 跑通最短分支，不要一开始就进入建筑生成的所有节点。此时重点是“字段由谁写入、下一个节点为什么被选择”，不是研究建筑算法。

### 第四周：模型输出、工具与高级 RAG

| 天数 | 学习任务 | 当天产出 |
| --- | --- | --- |
| Day 16 | 完成11模块第6～7章：超时重试、错误分类和源码调用链 | 错误矩阵与模型调用总结 |
| Day 17 | 学习系统 Prompt、任务 Prompt、JSON/Pydantic 输出 | 结构化输出最小实验 |
| Day 18 | 学习解析失败、`format_recovery` 和结构化校验 | 输出失败与恢复记录 |
| Day 19 | 学习 Tool Schema、参数校验、工具结果和事件协议 | 两个最小 Tool 的 Notebook 记录 |
| Day 20 | 学习查询改写、过滤、混合召回、引用和质量门禁 | Advanced RAG 检索链路图 |

高级 RAG 需要建立在 `06-chroma-basics` 和 `07-embedding-basics` 之上：

```text
用户问题
→ 查询改写
→ Metadata 过滤
→ 向量召回 + 关键词召回
→ 去重与排序
→ 质量门禁
→ 引用来源
→ 注入 Prompt
```

### 第五周：运行可靠性、业务管线与部署

| 天数 | 学习任务 | 当天产出 |
| --- | --- | --- |
| Day 21 | 阅读 AgentService、Session、Generation Job、Checkpoint 和恢复 | 服务—会话—任务关系图 |
| Day 22 | 深入心跳、断线重连、持久化事件和补发，并做一次部署链路检查 | WebSocket 可靠性清单 |
| Day 23 | 阅读 Validator、Repair、Callback，跟踪一次失败怎样被处理 | 校验—修复闭环图 |
| Day 24 | 串联 Architecture、Floor、Component、Merge、交付和前端重建 | Blueprint 到 Three.js 交付图 |
| Day 25 | 根据源码证据选择一个最小优化，补回归测试并部署验证 | 优化前后证据、演示与简历素材 |

本周需要明确区分：

- LangGraph State：一次工作流内部由节点读取和更新的数据；
- Session：用户多轮交互的数据；
- Generation Job：可以脱离某一条 WebSocket 连接继续运行的后台任务；
- WebSocket：消息与事件的传输通道，不等于任务本身。

第25天的优化必须来自前面画出的调用链、依赖图、日志或测试证据。一次只改一个边界清楚的问题；验证通过后再继续下一项，不按一份笼统问题清单同时重构多个模块。

## 五、每天的固定学习方法

每个学习日按照下面的节奏进行：

1. 运行现有功能，先观察输入和输出。
2. 找到入口函数，沿调用链只向下追一层。
3. 用最小代码复现当天概念。
4. 故意制造一次失败并记录日志表现。
5. 回到 WildAgent，说明它为什么需要这一层封装。
6. 整理当天笔记和仍未理解的问题。

每个模块至少覆盖下面四类内容；内容较多时可以拆成更多章节：

```text
第 1 章：这个模块解决什么问题
第 2 章：最小可运行示例
第 3 章：WildAgent 源码调用链
第 4 章：错误实验、排查方式和练习题
```

学习笔记不能只解释某一行代码，还应回答：

- 谁调用它？
- 它接收什么？
- 它返回或修改什么？
- 失败以后由谁处理？
- 如何通过日志或 LangSmith 观察它？
- 如何编写最小测试证明理解正确？

## 六、下一步

1. 自己创建 `08-websocket-request-flow/01.websocket-request-flow.ipynb`，完成第1～3章。
2. 完成第4～5章，从 `start_job()` 跟到 runner、`astream_events()` 和实际节点文件。
3. 完成第6～7章，用一条真实 chat 请求写出带源码与日志证据的完整往返链路。
4. 完成08模块检查表后，再创建 `09-architecture-and-patterns`，分析模块边界、依赖方向和设计模式。
5. 暂时不进入已经准备好的 [`11-model-client`](11-model-client/README.md)，等09和10完成后再学习。
