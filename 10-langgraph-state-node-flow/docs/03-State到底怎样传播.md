# 第03章：State 到底怎样传播

## 本章目标

看清四个经常被混在一起的对象：初始 State、节点输入、节点局部返回、合并后的完整 State。最后再把它们与 `astream_events` 事件分开。

源码锚点：[graph_state.py](../../../WildAgent/wild-server/app/agent/graph_state.py)、[architecture_node.py](../../../WildAgent/wild-server/app/agent/nodes/architecture_node.py)、[ws_agent.py](../../../WildAgent/wild-server/app/api/ws_agent.py)。

## 1. 初始 State 从哪里来

`_handle_with_langgraph()` 从 WebSocket payload 建立 `initial_state`。其中包括：

| 字段组 | 例子 | 来源 |
| --- | --- | --- |
| 请求身份 | `request_id`、`session_id` | WebSocket payload |
| 用户上下文 | `user_message`、`current_blueprint` | WebSocket payload |
| 模式开关 | `thinking_mode`、`plan_mode` | payload + 服务端兜底 |
| 循环预算 | `max_retries`、`retry_count` | 服务端初始化 |
| 并行容器 | `component_fragments={}` | 服务端初始化 |

随后执行：

```python
graph.astream_events(
    initial_state,
    config={"configurable": {"thread_id": f"generation:{request_id}"}},
    version="v2",
)
```

## 2. 节点收到完整 State，只返回局部更新

`architecture_planner(state)` 可以读取 `user_message`、`style_preference`、旧 `design_document` 等字段，但它只返回本次负责生产的字段：

```text
architecture_plan
design_document
resolved_design
design_review_status
design_feedback
design_material_refresh
complexity_profile
architecture_diag
```

LangGraph 将这些局部更新写回对应 channel。下一节点看到的是合并后的完整 State：

```text
initial_state
+ classifier 的 intent 字段
+ architecture 的设计字段
= material_plan 节点收到的 state
```

节点不应复制返回自己没有修改的所有字段。复制会让所有权模糊，也更容易用旧值覆盖并行更新。

## 3. 没有 Reducer 的字段采用更新语义

普通字段没有自定义 Reducer。节点返回同名字段时，新值替换旧值。这个规则适合：

- `design_review_status`：每轮只需要当前状态；
- `architecture_plan`：当前批准文档编译出的版本应覆盖旧版本；
- `merged_blueprint`：校验和修复围绕当前候选产物进行。

它不适合多个并行组件同时写同一个普通字典，因此 `component_fragments` 使用：

```python
component_fragments: Annotated[dict[str, Any], merge_state_mapping]
```

`merge_state_mapping(left, right)` 会保留不同的顶层组件 key。它是浅合并，同名 key 仍由右侧覆盖。

## 4. 三种观察结果不是一回事

| 观察对象 | 典型形状 | 含义 |
| --- | --- | --- |
| 节点局部更新 | `{"architecture": {"design_document": ...}}` | 某节点这一步写了什么 |
| 完整 State | `{"user_message": ..., "intent": ..., "design_document": ...}` | 所有 channel 当前值 |
| v2 事件 | `{"event": "on_chain_end", "name": "architecture", "data": {"output": ...}}` | 对一次运行活动的观测信封 |

WildAgent 在 `ws_agent.py` 中只处理 `_OUR_NODES` 的节点事件，并从 `event["data"]["output"]` 取该节点输出。需要完整 State 时，它调用 `graph.aget_state(graph_config)` 读取 checkpoint snapshot。

## Notebook 分单元格练习

### Cell 1：定义一个同构微型 State

- 输入：无；
- 前序依赖：第00章只用于对照；
- 预期：定义字段和 trace Reducer；
- 观察：`TypedDict` 负责类型说明，Reducer 写在具体 channel 上。

```python
from operator import add
from typing import Annotated, TypedDict

class DemoState(TypedDict, total=False):
    user_message: str
    intent: str
    design: dict
    material: dict
    trace: Annotated[list[str], add]
```

### Cell 2：定义三个只返回局部更新的节点

- 输入：Cell 1 的 `DemoState`；
- 前序依赖：Cell 1；
- 预期：每个函数只返回自己拥有的字段；
- 观察：节点参数仍能看到前序积累的完整 State。

```python
def classify(state: DemoState) -> dict:
    return {"intent": "generate", "trace": ["classifier"]}

def architecture(state: DemoState) -> dict:
    assert state["intent"] == "generate"
    return {
        "design": {"revision": 1, "width": 20},
        "trace": ["architecture"],
    }

def material(state: DemoState) -> dict:
    assert state["design"]["width"] == 20
    return {
        "material": {"concept": "silver + glass"},
        "trace": ["material_plan"],
    }
```

### Cell 3：构图并观察局部更新

- 输入：Cell 1～2；
- 前序依赖：Cell 2；
- 预期：依次看到三个以节点名包裹的更新；
- 观察：`stream_mode="updates"` 展示局部更新。

```python
from langgraph.graph import END, StateGraph

builder = StateGraph(DemoState)
builder.add_node("classifier", classify)
builder.add_node("architecture", architecture)
builder.add_node("material_plan", material)
builder.set_entry_point("classifier")
builder.add_edge("classifier", "architecture")
builder.add_edge("architecture", "material_plan")
builder.add_edge("material_plan", END)
demo_graph = builder.compile()

demo_input = {"user_message": "生成玻璃幕墙写字楼", "trace": []}
for update in demo_graph.stream(demo_input, stream_mode="updates"):
    print(update)
```

### Cell 4：观察完整最终 State

- 输入：同一 `demo_input`；
- 前序依赖：Cell 3；
- 预期：同时保留输入、三个业务字段和三条 trace；
- 观察：这次是另一次完整执行，不是把 Cell 3 的生成器接着跑。

```python
final_state = demo_graph.invoke(demo_input)
final_state
```

### Cell 5：查看事件信封

- 输入：`demo_graph`；
- 前序依赖：Cell 3；
- 预期：输出节点名、事件类型和 `data` 的 key；
- 观察：事件携带观测元数据，它本身不是完整 State。

```python
async for event in demo_graph.astream_events(demo_input, version="v2"):
    if event.get("name") in {"classifier", "architecture", "material_plan"}:
        print(
            event.get("event"),
            event.get("name"),
            list((event.get("data") or {}).keys()),
        )
```

## 错误实验

让 `material()` 返回 `{"design": {"material": "glass"}}`。最终 `design` 中原有的 `revision` 和 `width` 会被整个替换，因为普通 dict channel 不做递归合并。这正是“节点返回值越多越安全”的反例。

## 完成检查

- [ ] 我能指出 initial State 在哪里构造
- [ ] 我能解释节点输入为何比节点返回包含更多字段
- [ ] 我能区分普通覆盖 channel 与带 Reducer 的 channel
- [ ] 我能分别打印局部更新、完整 State 和事件信封
