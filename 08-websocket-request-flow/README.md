# 08 · WebSocket Request Flow：从用户消息找到执行节点

## 模块定位

- 前置模块：`07-embedding-basics`，你已经完成向量模型与索引流程学习；
- 后续模块：`09-architecture-and-patterns`，继续整理 WildAgent 的模块边界、依赖方向和设计模式；
- 本模块解决：一条用户消息怎样从前端进入 WebSocket，变成后台任务，进入 LangGraph 节点，再以事件形式返回前端；
- 本模块不包含：节点内部的完整业务算法、LangGraph Reducer 细节、模型客户端实现、心跳与断线恢复的全部可靠性设计。

这是一个 WildAgent 源码导读模块。WildAgent 只用于只读对照；所有练习都在 studyAgent 的 Notebook 中用最小假对象完成，不导入、不启动、不修改 WildAgent。

## 学习目标

学完后，你应该能够：

1. 区分 WebSocket 连接、用户请求、后台任务、Graph 运行、节点和事件；
2. 从前端 `sendUserMessage()` 找到后端 `/ws/agent`；
3. 解释 `agent_websocket()` 为什么不直接执行耗时节点；
4. 从 `GenerationJobService.start_job()` 跟踪到持久化 runner；
5. 从 `_handle_with_langgraph()` 找到 `graph.astream_events()` 和入口节点；
6. 根据事件中的节点名定位 `graph.add_node()` 和真实节点函数；
7. 解释 LangGraph 内部事件怎样变成 WebSocket 业务事件并返回前端；
8. 识别主路径、兼容路径和仅测试引用，避免跟错代码。

## 先区分六个对象

| 对象 | 例子 | 生命周期 |
|---|---|---|
| WebSocket 连接 | 浏览器与 `/ws/agent` 的连接 | 可以断开并重连 |
| 请求 | 一个 `request_id` 对应的 `user_message` | 从提交到完成或失败 |
| 会话 | `session_id` | 可以包含多轮请求 |
| 后台任务 | `GenerationJob` | 可以脱离某条 WebSocket 连接继续运行 |
| Graph 运行 | 一个 `thread_id` 对应的 LangGraph 执行 | 可以暂停并从 Checkpoint 恢复 |
| 事件 | `agent_step`、`agent_reply` 等 | 用于持久化、广播和更新前端状态 |

不要把“WebSocket 断开”直接理解成“生成任务停止”。当前 WildAgent 已经用 `GenerationJobService` 把任务和物理连接分开。

## 当前源码确认的主链

```text
wild-web/src/agent/protocol.ts
→ createUserMessageRequest()

wild-web/src/agent/agentBridge.ts
→ sendUserMessage()
→ ws.send(JSON.stringify(request))

wild-server/app/api/ws_agent.py
→ agent_websocket()
→ receive_text()
→ JSON / 协议版本 / type 分发
→ _prepare_server_request()
→ generation_job_service.start_job()

wild-server/app/services/generation_job_service.py
→ _spawn()
→ _run_job()
→ DurableEventSink
→ 已注册的 runner

wild-server/app/api/ws_agent.py
→ _run_persistent_langgraph()
→ _handle_with_langgraph()
→ get_graph()
→ graph.astream_events()

wild-server/app/agent/graph.py
→ entry point: classifier
→ add_node() 注册的具体节点

节点事件
→ _send_event()
→ DurableEventSink.send_json()
→ publish_event()
→ _broadcast()
→ agentBridge.onmessage
→ handleMessage()
→ Pinia Store / UI
```

## 一个必须提前知道的源码陷阱

`ws_agent.py` 中还能看到：

```text
_process_user_message_safely()
_handle_user_message()
_handle_with_langchain()
```

它们是保留的兼容或测试路径。当前 `agent_websocket()` 的 `user_message` 主分支直接调用 `generation_job_service.start_job()`，并不调用 `_handle_user_message()`。

阅读时不能只看“函数名字像入口”，必须再搜索“谁调用它”。测试文件引用某个函数，也不能证明生产主链会经过它。

## 章节目录

| 章节 | 核心问题 | Notebook 练习结果 |
|---|---|---|
| [第1章：先看一条完整请求](docs/01-先看一条完整请求.md) | 一条请求经过哪些对象和边界？ | 建立可检查的调用链台账 |
| [第2章：前端消息与协议](docs/02-前端消息与协议.md) | 前端到底发送了什么，返回事件怎样分发？ | 构造、序列化并校验协议消息 |
| [第3章：WebSocket接收与分发](docs/03-WebSocket接收与分发.md) | `/ws/agent` 怎样维护连接并分发消息类型？ | 用假 WebSocket 运行接收循环 |
| [第4章：GenerationJob后台任务](docs/04-GenerationJob后台任务.md) | 为什么接收循环不直接等待 Graph？ | 用假任务服务观察创建、去重和执行 |
| [第5章：从Runner进入LangGraph节点](docs/05-从Runner进入LangGraph节点.md) | 怎样从任务 runner 找到入口节点和实际文件？ | 观察最小 Graph 的节点事件 |
| [第6章：节点事件怎样返回前端](docs/06-节点事件怎样返回前端.md) | 内部 Graph 事件怎样变成 WebSocket 业务事件？ | 翻译、持久化、广播并去重事件 |
| [第7章：源码跟踪方法与边界](docs/07-源码跟踪方法与边界.md) | 怎样避免跟到兼容路径、测试路径或错误节点？ | 完成带证据的源码调用链表 |

建议用三天完成：

```text
Day 6：第1～3章，请求对象、前端协议和后端接收循环
Day 7：第4～5章，后台任务、runner 和 Graph 节点定位
Day 8：第6～7章，事件返回、恢复边界和源码跟踪方法
```

## Notebook 学习方法

请自行创建并维护：

```text
08-websocket-request-flow/01.websocket-request-flow.ipynb
```

仓库不会替你创建或填写 Notebook。每读完一章，再把对应 Cell 逐个手写进去；每运行一步，都记录输入、输出、对象状态和自己的疑问。

Notebook 第一个 Cell 使用：

```python
from pathlib import Path
import sys

current_dir = Path.cwd().resolve()
if current_dir.name == "08-websocket-request-flow":
    MODULE_ROOT = current_dir
    PROJECT_ROOT = current_dir.parent
else:
    PROJECT_ROOT = current_dir
    MODULE_ROOT = PROJECT_ROOT / "08-websocket-request-flow"

assert MODULE_ROOT.exists(), f"没有找到08模块：{MODULE_ROOT}"
sys.path.insert(0, str(PROJECT_ROOT))

print("Notebook工作目录：", current_dir)
print("studyAgent根目录：", PROJECT_ROOT)
print("08模块目录：", MODULE_ROOT)
```

Notebook 中不使用 `__file__`。异步练习直接使用顶层 `await`，不要在 Notebook 中套 `asyncio.run()`。

进入第3章前，先在 studyAgent 根目录执行一次本地环境检查：

```powershell
uv run python -c "import asyncio; print('asyncio ok')"
```

这个命令不联网。如果在 `import asyncio` 阶段就出现 Windows `WinError 10106`，说明代码尚未进入 WebSocket、GenerationJob 或 LangGraph。先把它记录为当前 Python/Windows Socket 运行环境阻塞，不要据此修改消息协议、节点或模型配置。

## 版本与资料依据

本模块以当前仓库源码为准：

| 项目 | 当前声明 | 本模块用途 |
|---|---|---|
| studyAgent | Python 3.12+ | Notebook 基础练习 |
| studyAgent | `langgraph-cli[inmem]>=0.4.31` | 最小 Graph 事件观察 |
| WildAgent | `fastapi[standard]>=0.139.2` | `/ws/agent` WebSocket 入口 |
| WildAgent | `langgraph>=1.2.9` | Graph、节点和 `astream_events()` |
| WildAgent | `langgraph-checkpoint-sqlite>=3.1.0` | 持久化 Checkpoint |

只读对照源码：

- [`agentBridge.ts`](../../WildAgent/wild-web/src/agent/agentBridge.ts)
- [`protocol.ts`](../../WildAgent/wild-web/src/agent/protocol.ts)
- [`ws_agent.py`](../../WildAgent/wild-server/app/api/ws_agent.py)
- [`generation_job_service.py`](../../WildAgent/wild-server/app/services/generation_job_service.py)
- [`graph.py`](../../WildAgent/wild-server/app/agent/graph.py)
- [`graph_state.py`](../../WildAgent/wild-server/app/agent/graph_state.py)

## 本模块与后续模块的边界

```text
08：纵向走通一次请求，只要求能找到节点
09：横向梳理包、职责、依赖和设计模式
10：深入 State、Reducer、边和节点间数据传递
11：深入节点内部的模型客户端调用
16：深入心跳、断线、事件重放和并发可靠性
```

## 模块完成标准

- [ ] 能区分连接、请求、会话、任务、Graph 运行和事件
- [ ] 能从 `sendUserMessage()` 找到 `agent_websocket()`
- [ ] 能从 `start_job()` 找到 `_handle_with_langgraph()`
- [ ] 能解释为什么 Graph 从 `classifier` 开始
- [ ] 给出一个节点名后，能找到 `add_node()` 和真实实现文件
- [ ] 能区分 `on_chain_end` 与 `agent_step`
- [ ] 能解释事件为什么先进入 `DurableEventSink`
- [ ] 能识别主路径与兼容路径
- [ ] 已在自己的 Notebook 中写出一份带源码证据的完整调用链
- [ ] 没有修改 WildAgent，也没有让项目替自己写完 Notebook
