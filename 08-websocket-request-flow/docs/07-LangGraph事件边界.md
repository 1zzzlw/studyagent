# 第07章：LangGraph 事件边界

## 本章目标

只研究 `ws_agent.py` 怎样进入 LangGraph、消费 `astream_events()`，以及如何识别节点开始/结束；节点内部状态合并和路由留到10模块。

## 前置知识

- 异步生成器与 `async for`；
- 字典、集合和 `continue`；
- 第06章中 sink 与物理连接的解耦。

## 1. 从 runner 进入 Graph

只读调用链：

```text
GenerationJobService._run_job()
→ self._runner(sink, job.payload, resume)
→ _run_persistent_langgraph(sink, payload, resume)
→ _handle_with_langgraph(sink, payload, resume=resume)
```

注意 `_handle_with_langgraph()` 的第一个形参仍叫 `ws`，但持久任务主链传入的实际对象是 `DurableEventSink`。两者都提供 `send_json()`，所以调用方不依赖具体类型。

这个细节很有教学意义，也暴露了命名滞后：代码能工作，但 `ws` 这个名字会让阅读者误以为它始终是物理连接。

这里的 `self._runner(...)` 不是 LangGraph 通知：应用启动时先把 `_run_persistent_langgraph` 函数对象传给 `GenerationJobService.startup()`，服务保存到 `_runner`，后台任务运行时再直接 `await` 调用。完整的“函数注册—保存—回调”与 Notebook Cell 见09模块第09章。

## 2. `_handle_with_langgraph()` 的五段边界

文件：[`ws_agent.py`](../../../WildAgent/wild-server/app/api/ws_agent.py)

| 阶段 | 当前源码动作 | 08掌握程度 |
| --- | --- | --- |
| 构造输入 | 请求字段转换为 `GenerationState` | 只认输入边界 |
| 获取 Graph | `get_graph(checkpointer=...)` | 知道返回可运行 Graph |
| 运行配置 | `thread_id`、`recursion_limit` | 知道用途 |
| 消费事件 | `graph.astream_events(..., version="v2")` | 本章重点 |
| 交付结果 | chat/edit/generate 分支发送业务事件 | 第08章衔接 |

恢复路径还会读取 Checkpoint，并可能用 `Command(resume=...)`。它属于10模块的深度内容，现在只记住 `resume=True` 会改变 Graph 输入方式。

## 3. 内部事件与业务事件不是一回事

`astream_events()` 给出的事件近似下面结构：

```python
{
    "event": "on_chain_start",
    "name": "classifier",
    "data": {...},
}
```

- `event`：LangChain/LangGraph 的运行事件类型；
- `name`：当前 Runnable 或节点名称；
- `data`：输入、输出等运行数据；
- `agent_step`：WildAgent 自己发送给前端的业务协议，不是 `astream_events()` 原生事件名。

## 4. Notebook 分单元格观察

### Cell 1：创建假异步事件流

- 输入：无；
- 依赖：无；
- 预期：异步逐条产生5个事件；
- 观察：函数体含 `yield` 后成为异步生成器。

```python
async def fake_graph_events():
    yield {"event": "on_chain_start", "name": "classifier", "data": {}}
    yield {"event": "on_chat_model_stream", "name": "model", "data": {"chunk": "A"}}
    yield {"event": "on_chain_end", "name": "classifier", "data": {"output": {"intent": "chat"}}}
    yield {"event": "on_chain_start", "name": "chat", "data": {}}
    yield {"event": "on_chain_end", "name": "chat", "data": {"output": {"chat_reply": "你好"}}}
```

代码解释：调用 `fake_graph_events()` 得到异步迭代器，不会一次性返回列表。真实 `astream_events()` 也是边运行边产生事件。

### Cell 2：只筛选当前项目节点边界

- 输入：异步事件流和允许节点集合；
- 依赖：Cell 1；
- 预期：忽略模型流事件，保留4个节点边界；
- 观察：集合成员检查用于排除 Graph 内部的其他 Runnable。

```python
OUR_NODES = {
    "classifier", "chat", "patch", "planning_research", "web_research",
    "planner", "plan_validator", "plan_review", "plan_executor",
    "architecture", "material_plan", "skeleton", "merge",
    "final_validate", "callback",
}

async def collect_node_boundaries(event_stream, allowed_nodes: set[str]) -> list[dict]:
    boundaries = []
    async for event in event_stream:
        kind = event.get("event")
        node_name = event.get("name", "")
        if node_name not in allowed_nodes:
            continue
        if kind not in {"on_chain_start", "on_chain_end"}:
            continue
        boundaries.append({"kind": kind, "node": node_name, "data": event.get("data", {})})
    return boundaries

boundaries = await collect_node_boundaries(fake_graph_events(), OUR_NODES)
boundaries
```

代码解释：两次 `continue` 分别过滤未知名称和无关事件类型。真实源码还会动态加入组件的 `*_gen` 与 `*_val` 节点。

### Cell 3：验证节点时序

- 输入：`boundaries`；
- 依赖：Cell 2；
- 预期：classifier 和 chat 都先 start 后 end；
- 观察：事件顺序能说明实际运行路径，但不直接解释路由条件。

```python
compact_path = [(item["kind"], item["node"]) for item in boundaries]

assert compact_path == [
    ("on_chain_start", "classifier"),
    ("on_chain_end", "classifier"),
    ("on_chain_start", "chat"),
    ("on_chain_end", "chat"),
]
print(compact_path)
```

代码解释：列表推导式把复杂事件缩成便于比较的二元组。它证明“实际发生了什么”，路由为什么选择 chat 要回到 `graph.py`，并在10模块分析 State。

### Cell 4：把内部事件翻译为最小业务事件

- 输入：节点边界；
- 依赖：Cell 2；
- 预期：start 变成 running，end 变成 done；
- 观察：这是翻译层，不是简单原样转发。

```python
def to_agent_step(boundary: dict, request_id: str) -> dict:
    is_start = boundary["kind"] == "on_chain_start"
    return {
        "type": "agent_step",
        "request_id": request_id,
        "node": boundary["node"],
        "status": "running" if is_start else "done",
    }

agent_steps = [to_agent_step(item, "req-1") for item in boundaries]
agent_steps
```

代码解释：真实源码会按节点补充 `stage`、`label`、`detail`、诊断和耗时，因此同一个 `on_chain_end` 可产生不止一个业务事件。

### Cell 5：主动制造未知节点事件

- 输入：只包含 `third_party_runnable` 的流；
- 依赖：Cell 2；
- 预期：返回空列表；
- 排查顺序：事件 `name` → `_OUR_NODES` → `graph.add_node()` 的注册名。

```python
async def unknown_events():
    yield {"event": "on_chain_start", "name": "third_party_runnable", "data": {}}

ignored = await collect_node_boundaries(unknown_events(), OUR_NODES)
assert ignored == []
print("未知 Runnable 被过滤")
```

代码解释：看不到前端进度不一定是节点没运行，也可能是事件名称没有进入允许集合或没有对应翻译逻辑。

## 5. 如何从事件名找到真实节点

当日志显示 `node=architecture` 时，按下面顺序搜索：

```text
graph.py 中 add_node("architecture", ...)
→ 找到注册时传入的函数或可调用对象
→ 打开它的定义文件
→ 再看 graph.py 中进入和离开该节点的边
```

08到这里停止。节点读了哪些 State 字段、返回值怎样合并、条件边为何选择下一节点，全部放在10模块。

## 6. 补充知识点

`astream_events(version="v2")` 是观测接口，而 Graph 的最终业务状态来自节点输出和 Checkpoint。不要把“捕获到某个事件”误认为“业务结果已经成功提交”。

## 7. 完成检查

- [ ] 我能从任务 runner 找到 `_handle_with_langgraph()`
- [ ] 我能区分内部运行事件和前端业务事件
- [ ] 我会用 `async for` 消费异步事件流
- [ ] 我知道 `_OUR_NODES` 为什么需要过滤事件
- [ ] 我能从一个节点名反查 `graph.add_node()`，但没有提前展开节点内部
