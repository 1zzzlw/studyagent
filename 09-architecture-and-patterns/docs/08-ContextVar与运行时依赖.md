# 第08章：`ContextVar` 与运行时依赖

## 本章目标

理解 WebSocket 推送回调和执行反馈轮询器为什么不能放入 LangGraph State，以及 WildAgent 怎样用 `ContextVar` 在当前运行范围内注入它们。

## 前置知识

- 全局变量、函数参数和 `try/finally`；
- 回调函数；
- 08模块中 `_handle_with_langgraph()` 的事件边界。

## 1. 当前源码链路

只读文件：[`runtime_context.py`](../../../WildAgent/wild-server/app/agent/runtime_context.py)

```text
ws_agent._handle_with_langgraph()
→ bind_reasoning_callback(send_thinking_delta)
→ bind_execution_feedback_poller(...)
→ graph.astream_events(...)

各节点
→ get_reasoning_callback()
→ await callback(node_name, delta)

ws_agent finally
→ reset_execution_feedback_poller(token)
→ reset_reasoning_callback(token)
```

`GenerationState` 需要被 Checkpoint 序列化；函数、WebSocket、数据库连接等进程资源不能可靠序列化。`ContextVar` 保存的是当前执行上下文的临时依赖，不属于业务状态。

## 2. 这不是普通全局变量

普通模块变量被所有并发任务共享，任务A设置回调后可能影响任务B。`ContextVar` 的值跟随当前上下文，并且 `set()` 返回 Token，之后可精确恢复设置前的值。

它是一种“作用域依赖注入”机制，不是经典 GoF 模式。

## 3. Notebook 分单元格观察

### Cell 1：声明 ContextVar 和读取函数

- 输入：无；
- 依赖：无；
- 预期：初始值为 `None`；
- 观察：类型参数描述变量允许保存的对象。

```python
from contextvars import ContextVar, Token
from typing import Callable

ProgressCallback = Callable[[str], None]
progress_callback: ContextVar[ProgressCallback | None] = ContextVar(
    "progress_callback",
    default=None,
)

def get_progress_callback() -> ProgressCallback | None:
    return progress_callback.get()

assert get_progress_callback() is None
```

代码解释：`ContextVar` 对象是模块级定义，但其中的“当前值”属于上下文，不是单一共享值。

### Cell 2：绑定、使用并恢复

- 输入：记录消息的回调；
- 依赖：Cell 1；
- 预期：绑定期间节点能取得回调，恢复后重新为 `None`；
- 观察：Token 代表设置前的上下文状态。

```python
progress_messages = []

def record_progress(message: str) -> None:
    progress_messages.append(message)

token = progress_callback.set(record_progress)
try:
    callback = get_progress_callback()
    if callback is not None:
        callback("architecture:running")
finally:
    progress_callback.reset(token)

assert progress_messages == ["architecture:running"]
assert get_progress_callback() is None
print(progress_messages)
```

代码解释：`try/finally` 保证节点失败时仍恢复上下文。真实 `ws_agent.py` 使用同样结构绑定和重置两个运行时依赖。

### Cell 3：观察嵌套上下文恢复顺序

- 输入：外层和内层两个回调；
- 依赖：Cell 1；
- 预期：重置内层后恢复到外层，而不是直接变成默认值；
- 观察：Token 必须按作用域正确使用。

```python
outer = lambda message: print("outer", message)
inner = lambda message: print("inner", message)

outer_token = progress_callback.set(outer)
inner_token = progress_callback.set(inner)

assert get_progress_callback() is inner
progress_callback.reset(inner_token)
assert get_progress_callback() is outer
progress_callback.reset(outer_token)
assert get_progress_callback() is None
print("嵌套上下文已按层恢复")
```

代码解释：每次 `set()` 都产生对应 Token。它不是清空命令，而是恢复到该次设置之前的值。

### Cell 4：证明函数不适合进入持久化 State

- 输入：包含回调的字典；
- 依赖：Cell 2；
- 预期：JSON 序列化失败；
- 观察：Checkpoint State 与运行时资源必须分开。

```python
import json

bad_state = {
    "request_id": "req-1",
    "callback": record_progress,
}

try:
    json.dumps(bad_state)
except TypeError as exc:
    print(type(exc).__name__, str(exc))
```

代码解释：函数对象不是 JSON 数据。即使某种 Python 序列化器能保存引用，服务重启后连接资源也无法原样恢复。

### Cell 5：主动观察忘记 reset 的泄漏

- 输入：临时绑定；
- 依赖：Cell 1；
- 预期：不 reset 时后续读取仍得到旧回调，最后手动恢复；
- 排查方向：bind 位置 → finally → 对应 Token 是否 reset。

```python
leaked_token = progress_callback.set(record_progress)
print("未恢复时：", get_progress_callback())
assert get_progress_callback() is record_progress

progress_callback.reset(leaked_token)
assert get_progress_callback() is None
print("手动恢复后：", get_progress_callback())
```

代码解释：忘记恢复会让同一上下文的后续代码拿到过期依赖，所以真实源码必须在 `finally` 中成对 reset。

## 4. 补充知识点

ContextVar 解决的是“当前运行怎样取得临时资源”，并不负责资源持久化、重连或跨进程传播。服务恢复任务时，新的 runner 会重新绑定当前进程的 callback 和 poller。

## 5. 完成检查

- [ ] 我能区分业务 State 与运行时依赖
- [ ] 我能解释函数为什么不能直接写入 JSON Checkpoint
- [ ] 我能解释 Token 的恢复语义
- [ ] 我知道 bind/reset 为什么必须放在 try/finally 两侧
- [ ] 我能从一个节点的 `get_reasoning_callback()` 反查到 ws_agent 的绑定位置

