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
| `06-embedding-basics` | 学习文档切片、向量化、Chroma 建库、查询与模型切换 | 学习中 |

当前近期目标：完成 `06-embedding-basics`，能够独立说明下面这条链路：

```text
Markdown 文档
→ 文档加载
→ RAG 切片
→ 文本向量化
→ 写入向量数据库
→ 问题向量化
→ 相似度检索
→ 返回相关上下文
```

## 三、后续计划模块

以下目录属于规划，不代表已经实现。学习到对应阶段时再创建，避免提前堆积空模块。

| 编号 | 计划模块 | 学习重点 | WildAgent 对照代码 |
| --- | --- | --- | --- |
| 07 | `model-client` | 模型配置、客户端创建、模型兼容、流式调用、重试 | `model_client.py`、`llm_invocation.py` |
| 08 | `structured-output` | Prompt、JSON/Pydantic 输出、解析和格式恢复 | `prompts.py`、`format_recovery.py`、`schemas/` |
| 09 | `graph-state-routing` | State、Reducer、条件路由、循环和结束条件 | `graph_state.py`、`graph.py` |
| 10 | `agent-nodes` | 节点读取状态、调用能力、写回状态的标准结构 | `classifier_node.py`、`chat_node.py` |
| 11 | `tools-and-protocol` | Tool 定义、参数校验、工具结果和事件协议 | `tools/`、`protocol.py` |
| 12 | `advanced-rag` | 查询改写、混合检索、过滤、引用、门禁和校准 | `agent/rag/`、`rag_gate.py` 等 |
| 13 | `service-layer` | AgentService 如何组装模型、RAG、Graph 和业务能力 | `agent_service.py` |
| 14 | `session-and-jobs` | Session、后台任务、Checkpoint、暂停和恢复 | `session_service.py`、`generation_job_service.py` |
| 15 | `websocket-streaming` | 流式事件、思考过程、进度、心跳和断线恢复 | `ws_agent.py`、`ws_heartbeat.py` |
| 16 | `validation-repair` | 校验器、错误分类、确定性修复和回调重试 | `validators/`、`repair_tools.py`、`callback_node.py` |
| 17 | `blueprint-pipeline` | 建筑规划、楼层、构件、合并和最终校验 | `architecture_node.py`、`floor_*`、`merge_node.py` |
| 18 | `frontend-delivery` | Agent 事件如何进入前端并完成场景重建 | `agentBridge`、Store、`wild-compiler`、`wild-core` |
| 19 | `testing-and-deployment` | 单元测试、回归测试、配置检查、日志和部署排障 | `tests/`、配置模块和部署脚本 |

## 四、25 个学习日计划

建议每天投入 1.5～2 小时，每天只解决一个核心问题。

### 第一周：模型调用层

| 天数 | 学习任务 | 当天产出 |
| --- | --- | --- |
| Day 1 | 阅读 `model_client.py`，理解配置如何变成模型客户端 | 独立调用模型的最小程序 |
| Day 2 | 理解普通模型、思考模型及不同供应商的参数差异 | 模型兼容参数表 |
| Day 3 | 阅读 `llm_invocation.py`，对比 invoke 和 stream | 流式与非流式示例 |
| Day 4 | 学习超时、重试、Token Usage 和错误转换 | 可重试的模型调用器 |
| Day 5 | 串联模型调用全过程 | `07-model-client` 学习文档 |

完成标准：能够解释为什么 WildAgent 节点不应该各自直接调用 OpenAI SDK。

### 第二周：状态、路由与节点

| 天数 | 学习任务 | 当天产出 |
| --- | --- | --- |
| Day 6 | 阅读 `GenerationState`，区分输入状态和过程状态 | 简化版 State |
| Day 7 | 学习 Reducer 和多节点状态合并 | 状态合并实验 |
| Day 8 | 阅读 `classifier_node` 和条件路由 | 分类路由 Agent |
| Day 9 | 阅读 `chat_node`，总结标准节点结构 | 自定义 LangGraph 节点 |
| Day 10 | 阅读 `graph.py`，整理主要节点和路由 | WildAgent Graph 简化图 |

阅读顺序应从 `classifier_node`、`chat_node` 开始，不要一开始就进入复杂的建筑生成节点。

### 第三周：结构化输出、工具和高级 RAG

| 天数 | 学习任务 | 当天产出 |
| --- | --- | --- |
| Day 11 | 学习系统 Prompt、任务 Prompt 和动态上下文 | Prompt 分层示例 |
| Day 12 | 学习 JSON/Pydantic 结构化输出 | 结构化建筑需求对象 |
| Day 13 | 学习解析失败和 `format_recovery` | 错误 JSON 修复实验 |
| Day 14 | 学习 Tool Schema、参数校验和工具结果 | 两个最小 Tool |
| Day 15 | 学习查询改写、混合召回、引用和 RAG Gate | Advanced RAG 示例 |

高级 RAG 需要在 `06-embedding-basics` 之上继续理解：

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

### 第四周：服务、会话和实时通信

| 天数 | 学习任务 | 当天产出 |
| --- | --- | --- |
| Day 16 | 阅读 `AgentService`，理解各依赖如何组装 | 服务初始化流程图 |
| Day 17 | 学习 Session、Thread ID 和历史消息 | 多轮会话示例 |
| Day 18 | 学习 Checkpoint、暂停和恢复 | 可恢复的 LangGraph |
| Day 19 | 阅读 `ws_agent.py`，理解事件推送 | FastAPI WebSocket 示例 |
| Day 20 | 学习后台任务、心跳和断线重连 | 长任务进度推送示例 |

本周需要明确区分：

- LangGraph State：一次工作流内部的数据。
- Session：用户多轮对话的数据。
- Generation Job：可以脱离 WebSocket 继续运行的后台任务。

### 第五周：WildAgent 业务核心

| 天数 | 学习任务 | 当天产出 |
| --- | --- | --- |
| Day 21 | 阅读 Architecture Plan 和 Execution Plan | 建筑规划数据结构图 |
| Day 22 | 阅读楼层设计、空间分析和开洞流程 | 楼层节点调用链 |
| Day 23 | 阅读构件生成和 Fragment Merge | 多节点结果合并实验 |
| Day 24 | 阅读 Validator、Repair 和 Callback | 校验—修复闭环示例 |
| Day 25 | 阅读最终交付和前端场景重建链路 | WildAgent 全链路总结 |

完成第五周以后，再单独安排前端交付、自动化测试和部署排障，不把后端 Agent 学习与 Three.js 细节混在一起。

## 五、每天的固定学习方法

每个学习日按照下面的节奏进行：

1. 运行现有功能，先观察输入和输出。
2. 找到入口函数，沿调用链只向下追一层。
3. 用最小代码复现当天概念。
4. 故意制造一次失败并记录日志表现。
5. 回到 WildAgent，说明它为什么需要这一层封装。
6. 整理当天笔记和仍未理解的问题。

每个模块统一采用四章结构：

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

1. 完成 `06-embedding-basics` 的文档、建库、查询和模型切换实验。
2. 运行索引状态检查，理解断点续建和不完整索引。
3. 创建 `07-model-client`，从 `model_client.py` 和 `llm_invocation.py` 开始。
4. 先实现一个独立模型调用器，再对照 WildAgent 的封装设计。
