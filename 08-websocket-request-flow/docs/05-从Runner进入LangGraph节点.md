# 第5章：从 Runner 进入 LangGraph 节点

## 本章目标

本章结束时，你能从任务服务注册的 runner 找到 `_handle_with_langgraph()`，知道 Graph 从哪个节点开始，并能根据节点注册名定位实际 Python 函数和文件。

## 前置知识

- 已完成第4章，知道 `_run_job()` 会调用预先注册的 runner；
- 学过04模块的 LangGraph 基础，知道 Node、Edge 和 State；
- 本章只观察节点入口，不深入复杂 State 合并，详细内容留到10模块。

## 1. runner 的真实绑定

应用启动阶段：

```text
wild-server/main.py lifespan
→ startup_generation_jobs()
→ generation_job_service.startup(_run_persistent_langgraph)
→ self._runner = _run_persistent_langgraph
```

任务执行阶段：

```text
GenerationJobService._run_job()
→ sink = DurableEventSink(...)
→ await self._runner(sink, job.payload, resume)
→ _run_persistent_langgraph(sink, payload, resume)
→ 安全检查
→ _handle_with_langgraph(sink, payload, resume=resume)
```

“注册函数”和“稍后调用函数”分处两个文件，是第一次跟踪时容易断掉的地方。

## 2. `_handle_with_langgraph()` 做了什么

先只记五步：

```text
1. 从 payload 构造 initial_state: GenerationState
2. 初始化 GenerationJobService 的 Checkpointer
3. get_graph(enable_callback=True, checkpointer=...)
4. 构造 graph_config，其中 thread_id = generation:{request_id}
5. graph.astream_events(graph_input, config=graph_config, version="v2")
```

`initial_state` 才第一次出现 `user_message`、`request_id`、`session_id`、`thinking_mode`、`plan_mode` 等 Graph State 字段。前端请求本身不是 `GenerationState` 类型。

## 3. Graph 从 classifier 开始

[`graph.py`](../../../WildAgent/wild-server/app/agent/graph.py) 中：

```python
graph.add_node("classifier", classifier_node)
graph.add_node("chat", chat_node)
graph.add_node("patch", _planned_node("patch", patch_node))
...
graph.set_entry_point("classifier")
```

`classifier` 执行后，`_classifier_dispatch(state)` 根据 `intent` 选择：

```text
chat     → chat
edit     → patch（plan_mode 关闭时）
generate → architecture（plan_mode 关闭时）
plan_mode=True → planning_research
模型终态错误 → END
```

因此用户问题不会在 WebSocket 层直接选择 `chat_node`。它先进入 `classifier`，由 Graph 状态决定下一跳。

## 4. 节点名称怎样定位源码

看到日志里的 `node="classifier"`，按这个顺序找：

```text
第1步：在 graph.py 搜索 add_node("classifier"
第2步：看第二个参数是 classifier_node
第3步：看 graph.py 顶部从 app.agent.nodes 导入
第4步：打开 nodes/__init__.py，看它从 classifier_node.py 导出
第5步：打开 classifier_node.py，找到函数实现
```

常见注册形式：

| 注册形式 | 示例 | 定位方式 |
|---|---|---|
| 直接函数 | `add_node("chat", chat_node)` | 跟踪导入到 `chat_node.py` |
| 包装函数 | `add_node("architecture", _planned_node(...))` | 先看包装器，再找原函数 |
| 动态工厂 | `add_node(gen_name, create_component_generator(cfg))` | 看名称生成规则、Registry 和工厂 |
| 本地别名 | `skeleton_generator = approved_plan_assembler` | 以当前赋值为准，不凭文件名猜 |

### skeleton 是一个典型陷阱

当前 `graph.py` 把主链的 `skeleton` 指向 `approved_plan_assembler`。`nodes/skeleton_node.py` 的旧 LLM 骨架实现仍通过 `legacy_skeleton_generator` 保留给旧 Checkpoint 或测试。搜索到同名历史实现，不等于当前主链会调用它。

## 5. Notebook 分单元格练习

建立 `# 第5章：从Runner进入LangGraph节点`。

### Cell 1：定义最小 Graph State 和节点

- 依赖：studyAgent 环境中的 LangGraph；
- 是否联网：否；
- 输入：一条 `user_message`；
- 预期：分类节点写入 `intent`，业务节点写入 `result`。

```python
from typing import TypedDict

from langgraph.graph import END, StateGraph


class DemoGraphState(TypedDict, total=False):
    request_id: str
    user_message: str
    intent: str
    result: str


def demo_classifier(state: DemoGraphState) -> dict:
    message = state["user_message"]
    intent = "generate" if "生成" in message else "chat"
    return {"intent": intent}


def demo_chat(state: DemoGraphState) -> dict:
    return {"result": f"知识回答：{state['user_message']}"}


def demo_generate(state: DemoGraphState) -> dict:
    return {"result": f"生成请求：{state['user_message']}"}


def route_after_classifier(state: DemoGraphState) -> str:
    return state["intent"]
```

### Cell 2：注册名称、函数和边

- 依赖：Cell 1；
- 是否联网：否；
- 观察点：注册名与 Python 函数名是两个概念。

```python
builder = StateGraph(DemoGraphState)

builder.add_node("classifier", demo_classifier)
builder.add_node("chat", demo_chat)
builder.add_node("generate", demo_generate)

builder.set_entry_point("classifier")
builder.add_conditional_edges(
    "classifier",
    route_after_classifier,
    {
        "chat": "chat",
        "generate": "generate",
    },
)
builder.add_edge("chat", END)
builder.add_edge("generate", END)

demo_graph = builder.compile()
print("Graph已编译")
```

### Cell 3：执行最短 chat 分支

- 依赖：Cell 2；
- 是否联网：否；
- 预期：最终状态包含 `intent=chat` 和回答。

```python
chat_state = await demo_graph.ainvoke({
    "request_id": "req_graph_chat",
    "user_message": "门和窗有什么区别？",
})

print(chat_state)
assert chat_state["intent"] == "chat"
```

### Cell 4：只观察节点 start/end 事件

- 依赖：Cell 2；
- 是否联网：否；
- 预期：看到 `classifier` 和 `chat` 两个注册名。

```python
known_nodes = {"classifier", "chat", "generate"}
observed_node_events = []

async for event in demo_graph.astream_events(
    {
        "request_id": "req_graph_events",
        "user_message": "解释一下楼梯",
    },
    version="v2",
):
    event_name = event.get("name", "")
    event_kind = event.get("event", "")
    if event_name in known_nodes and event_kind in {
        "on_chain_start",
        "on_chain_end",
    }:
        observed_node_events.append((event_kind, event_name))
        print(event_kind, "=>", event_name)
```

这里显示的是注册名 `classifier`，不是函数名 `demo_classifier`。

### Cell 5：切换到 generate 分支

- 依赖：Cell 2；
- 是否联网：否；
- 预期：输入变化后，第二个节点变成 `generate`。

```python
generate_state = await demo_graph.ainvoke({
    "request_id": "req_graph_generate",
    "user_message": "生成一座小亭子",
})

print(generate_state)
assert generate_state["intent"] == "generate"
```

### Cell 6：主动混淆注册名和函数名

- 依赖：Cell 1；
- 是否联网：否；
- 主动错误：用函数名查找只保存注册名的表；
- 预期：出现 `KeyError`。

```python
registered_nodes = {
    "classifier": demo_classifier,
    "chat": demo_chat,
    "generate": demo_generate,
}

try:
    registered_nodes["demo_classifier"]
except KeyError as exc:
    print("预期节点名错误：", exc)

print("正确注册名对应函数：", registered_nodes["classifier"].__name__)
```

### Cell 7：记录一个真实节点的定位过程

- 类型：Markdown Cell；
- 依赖：只读打开 WildAgent；
- 预期：选择 `classifier` 或 `chat`，逐项写证据。

```markdown
## 节点定位记录

- 日志或事件中的注册名：
- graph.add_node 所在文件：
- add_node 的第二个参数：
- graph.py 中的导入位置：
- nodes/__init__.py 的导出来源：
- 最终实现文件：
- 谁决定它的下一跳：
```

## 6. 常见问题

### 为什么搜索节点名只找到 graph.py

节点名通常只是 `add_node()` 的字符串，真实函数可能叫另一个名字。必须查看第二个参数和导入链。

### 为什么事件里还有不是节点的名称

`astream_events()` 会包含 Graph 内部及子 Runnable 事件。WildAgent 使用 `_OUR_NODES` 白名单只处理自己的节点名。

## 7. 练习题

1. 用同样方法定位 `architecture`，说明 `_planned_node()` 包装了什么。
2. 定位 `skeleton`，证明当前主链实现不是仅凭 `skeleton_node.py` 推断出来的。
3. 找出动态名称 `door_gen` 由哪段格式化代码产生、由哪个工厂创建。

## 8. 完成检查

- [ ] 我能从 runner 注册找到 `_handle_with_langgraph`
- [ ] 我知道 initial_state 在哪里创建
- [ ] 我知道 Graph 默认从 classifier 开始
- [ ] 我运行了 chat 和 generate 两条最小分支
- [ ] 我观察了 astream_events 中的注册节点名
- [ ] 我能按 add_node 第二个参数定位真实文件
- [ ] 我理解 skeleton 的当前主链与历史实现区别
