# 第四章：LangGraph 基础

## 1. LangGraph 解决什么问题

普通函数适合固定顺序：

```text
A → B → C
```

LangGraph 适合需要状态、分支、循环、暂停或恢复的流程：

```text
START → 检查输入 → 条件判断 ─┬→ 节点 A → END
                              └→ 节点 B → END
```

它不是大模型，也不会自动帮你设计 Agent。它是工作流编排和运行时。

## 2. 五个核心概念

| 概念 | 含义 |
|---|---|
| State | 整个流程共享的数据 |
| Node | 读取 State、返回局部更新的函数 |
| Edge | 固定的下一步 |
| Conditional Edge | 根据 State 选择下一步 |
| Graph | 将节点和边组装、编译后的可运行对象 |

节点不要原地修改 State，推荐只返回本节点产生的更新：

```python
def node(state):
    return {"result": state["number"] * 2}
```

## 3. 本章最小项目

文件：

- `basic_graph.py`：Graph 实现
- `test_basic_graph.py`：两个分支的自动测试

Graph 的结构：

```text
START
  ↓
validate
  ↓
number 是偶数？
  ├─ 是 → double → END
  └─ 否 → triple → END
```

运行：

```powershell
cd E:\AgentProject\studyAgent\04-langgraph-basics
uv run python basic_graph.py
uv run python -m unittest -v test_basic_graph.py
```

预期：

```text
4 → 8，steps=[收到数字 4, 偶数乘以 2]
5 → 15，steps=[收到数字 5, 奇数乘以 3]
```

## 4. 逐段理解代码

### 定义 State

```python
class NumberState(TypedDict):
    number: int
    result: int
    steps: Annotated[list[str], operator.add]
```

`number` 是输入，`result` 是结果。`steps` 使用 `operator.add` reducer，因此不同节点返回的列表会追加，而不是互相覆盖。

### 定义 Node

```python
def double_number(state: NumberState) -> dict:
    return {"result": state["number"] * 2, "steps": ["偶数乘以 2"]}
```

节点接收当前 State，只返回更新。

### 定义条件路由

```python
def route_number(state):
    return "double" if state["number"] % 2 == 0 else "triple"
```

路由函数不执行业务，只决定下一个节点名称。

### 组装并编译

```python
builder = StateGraph(NumberState)
builder.add_node("validate", validate_input)
builder.add_edge(START, "validate")
builder.add_conditional_edges("validate", route_number)
builder.add_edge("double", END)
builder.add_edge("triple", END)
graph = builder.compile()
```

只有 `compile()` 后的 `graph` 才能 `invoke()`。

## 5. `MessagesState` 是什么

聊天 Agent 常用：

```python
from langgraph.graph import MessagesState
```

它已经定义了带消息 reducer 的 `messages` 字段。新消息会按规则追加，并处理相同 message ID 的更新，比自己写 `list + list` 更适合对话。

```python
def chatbot(state: MessagesState):
    response = llm.invoke(state["messages"])
    return {"messages": [response]}
```

## 6. 普通调用、流式调用

一次得到最终 State：

```python
result = graph.invoke(input_state)
```

观察每个节点更新：

```python
for event in graph.stream(input_state, stream_mode="updates"):
    print(event)
```

异步程序对应 `ainvoke()` 和 `astream()`。

## 7. Checkpointer 与 Thread

直接 `graph.compile()` 不会跨调用保存对话。需要本地测试持久状态时，可以编译时传入 checkpointer，并在调用配置里提供 `thread_id`。

Agent Server 则会负责 Thread、Run 和持久化基础设施，所以第五章导出的 Graph 不要自行绑定内存 checkpointer。

## 8. 常见错误

- 忘记连接 `START`：Graph 没有入口。
- 节点返回完整旧 State：容易覆盖其他节点更新。
- 列表字段没定义 reducer：后一个节点会替换前一个值。
- 路由返回的节点名不存在：运行时报错。
- 把业务处理写进路由函数：流程难测试。
- 把 Notebook 全局变量当 State：无法可靠恢复和部署。

## 9. 学完标准

你应能不看答案解释：

1. State 和普通局部变量有什么不同；
2. Node 为什么返回字典；
3. Edge 与 Conditional Edge 的区别；
4. reducer 为什么影响列表更新；
5. `compile()` 和 `invoke()` 分别做什么。

官方参考：[LangGraph Quickstart](https://docs.langchain.com/oss/python/langgraph/quickstart)、[Graph API](https://docs.langchain.com/oss/python/langgraph/graph-api)。
