# 08 · WebSocket 源码导读：读懂 `ws_agent.py`

## 模块定位

- 前置模块：`07-embedding-basics`；
- 后续模块：`09-architecture-and-patterns`、`10-langgraph-state-node-flow`；
- 核心任务：把 WildAgent 当前的 `ws_agent.py` 拆成可阅读、可验证的源码切片；
- 学习载体：你已有的 `01.basic.ipynb`；
- 参考项目：`E:\AgentProject\WildAgent`，本模块只读，不修改、不导入运行。

本模块不是一份通用 WebSocket 教程，也不再让你重新实现一个完整服务器。每章只做三件事：

```text
定位 WildAgent 的真实源码
→ 摘出一个可以独立理解的行为
→ 在 Notebook 中用最小假对象或纯函数验证这个行为
```

## `ws_agent.py` 值得学吗

值得学，但不能把它当成“完美范本”。它有两方面教学价值：

- 值得借鉴：协议版本、心跳、在线状态、后台任务、事件持久化、断线恢复、错误翻译等生产问题都被真实处理了；
- 值得反思：一个文件同时承担接入、请求清洗、Graph 编排、事件翻译和遗留兼容，长度超过 1700 行，阅读成本和改动风险都很高。

因此你既要学会“这段代码为什么能工作”，也要学会发现“哪些职责以后可以拆开”。职责和设计模式的系统分析放到09模块，本模块不边读边重构。

## 学完后你能做到什么

1. 从前端 `sendUserMessage()` 找到后端 `/ws/agent`；
2. 解释 `agent_websocket()` 的连接生命周期与消息分发；
3. 解释 `_prepare_server_request()` 如何清洗用户输入；
4. 从 `start_job()` 找到后台 runner 和 `DurableEventSink`；
5. 从 `_run_persistent_langgraph()` 找到 `graph.astream_events()`；
6. 解释 LangGraph 事件怎样变成前端能处理的业务消息；
7. 区分当前主链、遗留函数和只被测试调用的函数；
8. 用 Python 的字典、列表、函数、类、异步函数、异常和回调解释源码。

## 先建立对象边界

| 对象 | 代码中的代表 | 要记住的边界 |
| --- | --- | --- |
| 物理连接 | `WebSocket` | 可断开、可重连 |
| 一次请求 | `request_id` | 对应一次用户操作 |
| 会话 | `session_id` | 包含多次请求 |
| 后台任务 | `GenerationJob` | 可脱离连接继续执行 |
| Graph 运行 | `thread_id` + Checkpoint | 可暂停、恢复 |
| 业务事件 | `agent_step`、`agent_reply` 等 | 可持久化、广播、重放 |

`WebSocket` 不是后台任务，断线也不必然意味着任务停止。这正是 `GenerationJobService` 存在的原因。

## 当前源码主链

```text
protocol.ts / types/agent.ts
→ agentBridge.sendUserMessage()
→ WebSocket.send(JSON.stringify(request))
→ ws_agent.agent_websocket()
→ json.loads() + protocol_version + type 分发
→ _prepare_server_request()
→ generation_job_service.start_job()
→ GenerationJobService._run_job()
→ DurableEventSink
→ _run_persistent_langgraph()
→ _handle_with_langgraph()
→ graph.astream_events()
→ publish_event() / _broadcast()
→ agentBridge.handleMessage()
→ 前端 Store / UI
```

## 章节目录

| 章节 | 只解决一个问题 | Notebook 中的观察结果 |
| --- | --- | --- |
| [01 源码地图与阅读顺序](docs/01-ws_agent源码地图与阅读顺序.md) | 1700 多行从哪里开始看 | 能区分主链、辅助函数和遗留路径 |
| [02 前端协议与 user_message](docs/02-前端协议与user_message.md) | 浏览器实际发送什么 | 构造并断言一条协议消息 |
| [03 WebSocket 连接生命周期](docs/03-WebSocket连接生命周期.md) | 连接怎样开始和结束 | 观察 `accept → receive → cleanup` |
| [04 消息解析与类型分发](docs/04-消息解析与类型分发.md) | 多种消息怎样走不同分支 | 表格化验证消息路由 |
| [05 请求预处理与后台任务入口](docs/05-请求预处理与后台任务入口.md) | 用户消息怎样进入 `start_job()` | 验证复制、过滤、截断和调用参数 |
| [06 GenerationJob 与持久事件](docs/06-GenerationJob与持久事件.md) | 为什么耗时任务不绑死连接 | 观察任务、事件序号、订阅者变化 |
| [07 LangGraph 事件边界](docs/07-LangGraph事件边界.md) | WS 文件怎样接入 Graph | 消费假异步事件流并筛选节点事件 |
| [08 事件回传与前端状态](docs/08-事件回传与前端状态.md) | 后端事件怎样改变前端状态 | 用 Python 镜像 `handleMessage()` |
| [09 心跳、恢复与源码验收](docs/09-心跳恢复与源码验收.md) | 断线后如何判断任务是否继续 | 完成一次带证据的完整链路审计 |

建议用三天完成：

```text
Day 6：第01～03章，源码地图、前端请求、连接生命周期
Day 7：第04～06章，分发、请求预处理、后台任务
Day 8：第07～09章，Graph 边界、事件回传、恢复与验收
```

## Notebook 使用方式

继续使用你已经创建的：

```text
08-websocket-request-flow/01.basic.ipynb
```

项目不会替你改这个 Notebook。每章的 Cell 都要亲手输入；代码块后面的解释要先读，再对照自己的真实输出。

如果这个 Notebook 已经写过旧版08的 Cell，请保留为自己的历史记录，并新加一个 Markdown 标题“08源码导读重构版”后再继续。旧 Cell 中出现的已移除节点名只能作为版本对比，不能继续当作当前 WildAgent 主链。

本模块先用普通 `assert` 做单元级验证，第04章再用一次标准库 `unittest` 观察正式测试报告。这样可以先看清输入与状态变化，再认识测试类、`subTest()` 和测试结果对象。

第一个 Cell 建议写：

```python
from pathlib import Path

current_dir = Path.cwd().resolve()
module_root = current_dir if current_dir.name == "08-websocket-request-flow" else current_dir / "08-websocket-request-flow"
wildagent_root = module_root.parents[1] / "WildAgent"

assert module_root.exists(), module_root
assert wildagent_root.exists(), wildagent_root

print("08模块：", module_root)
print("WildAgent（只读）：", wildagent_root)
```

代码解释：

- `Path.cwd()` 取得 Notebook 的实际工作目录，不能在 Notebook 中依赖 `__file__`；
- `parents[1]` 从模块目录回到 `E:\AgentProject`；
- 后续 Cell 只用 `read_text()` 查看源码，不对 WildAgent 调用写入方法。

异步练习使用 Notebook 支持的顶层 `await`，不要在 Cell 中套 `asyncio.run()`。

### 当前环境的异步预检

进入第03、05、06、07、09章的异步 Cell 前，先在终端运行：

```powershell
uv run python -c "import asyncio; print('asyncio ok')"
```

本次整理时，这台机器仍在 `import asyncio` 阶段出现 `OSError: [WinError 10106]`。这说明 Python 尚未运行到 WebSocket、假对象或 LangGraph 代码，属于当前 Windows Socket/Winsock 环境阻塞。同步阅读与同步 Cell 可以继续；异步 Cell 要等该环境恢复后再运行，不要因此修改消息协议或节点。

## 阅读时的三条规则

1. 先找调用者，再判断函数是否属于主链；名字像入口并不等于真的被入口调用。
2. 对照当前 `graph.py` 验证注释。`ws_agent.py` 中仍可能存在未同步的旧注释，调用图比注释更可信。
3. 08只研究 Graph 的接入与事件边界；State、Reducer、条件边、`Command` 和 Checkpoint 的内部机制留到10模块。

## 与09、10模块的边界

```text
08：纵向读懂一条 WebSocket 请求，能从前端找到 Graph 边界再回到前端
09：横向识别模块职责、依赖方向和设计模式，解释代码为什么这样组织
10：深入 LangGraph 的 State、Reducer、边、节点通信、暂停和恢复
```

后续模块也必须继续使用“真实源码切片 + Notebook 最小观察”的方式：

- 09不背设计模式定义。每个模式必须指出 WildAgent 的参与类、调用关系、解决的问题和带来的代价；最终产出模块依赖图与模式证据表。
- 10不重复04的入门 Graph。先用 `classifier → chat` 最短路径建立字段来源—消费者表，再进入 Reducer、条件边、动态 `Send`、`Command`、Checkpoint、计划审核暂停与恢复，并把节点事件重新接回08的 WebSocket 链路。

## 完成标准

- [ ] 我能画出 `sendUserMessage → agent_websocket → start_job → Graph → handleMessage` 主链
- [ ] 我能解释请求、连接、任务、Graph 运行和事件的区别
- [ ] 我能说出 `agent_websocket()` 每个 `type` 分支负责什么
- [ ] 我能解释 `_prepare_server_request()` 不直接修改原字典的原因
- [ ] 我能说明 `DurableEventSink` 为什么不是普通 `WebSocket.send_json()`
- [ ] 我能从 `astream_events()` 的事件找到节点名
- [ ] 我能区分主路径、遗留路径和测试入口
- [ ] 我已在 `01.basic.ipynb` 中完成各章的最小验证与错误观察
- [ ] 我没有修改 WildAgent，也没有让工具替我填完 Notebook
