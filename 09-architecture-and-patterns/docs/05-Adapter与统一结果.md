# 第05章：Adapter 与统一结果

## 本章目标

理解 WildAgent 怎样让接口不兼容的对象被同一调用者使用，并区分对象适配、继承适配和结果归一化。

## 前置知识

- 方法调用与鸭子类型；
- 继承中的 `super()`；
- 第03章的结构化接口。

## 1. 当前源码中的三种适配

| 源码 | 被适配的差异 | 稳定接口 |
| --- | --- | --- |
| `DurableEventSink` | Graph 不应绑定物理 WebSocket | `send_json(payload)` |
| `ReasoningChatOpenAI` | 供应商扩展的 reasoning/usage 字段 | LangChain ChatModel 行为 |
| `content_as_text()`、`message_texts()`、`LlmResult` | 字典、对象、分块、不同 token 键名 | 文本、推理和统一 usage |

只读文件：

- [`generation_job_service.py`](../../../WildAgent/wild-server/app/services/generation_job_service.py)；
- [`model_client.py`](../../../WildAgent/wild-server/app/agent/model_client.py)；
- [`llm_invocation.py`](../../../WildAgent/wild-server/app/agent/llm_invocation.py)。

它们不完全是同一种教科书 Adapter 实现，但目标一致：把外部或旧形状收敛成项目内部稳定形状。

## 2. `DurableEventSink` 与真实 WebSocket 是两跳关系

它们没有继承关系，也没有做方法绑定。关联来自 Python 鸭子类型：`_send_event()` 收到的对象只要具有可等待的 `send_json(payload)`，调用就能成立。

直接处理旧链是：

```text
_send_event(real_websocket, payload)
→ real_websocket.send_json(versioned_payload)
→ 浏览器
```

当前持久任务主链是：

```text
_send_event(durable_sink, payload)
→ durable_sink.send_json(versioned_payload)
→ generation_job_service.publish_event(request_id, payload)
→ [关键事件先 _append_event 写入 SQLite]
→ generation_job_service._broadcast(request_id, event)
→ subscriber.send_json(event)
→ 真实 WebSocket.send_json(event)
→ 浏览器
```

这里出现了两个不同对象的同名方法：

| 调用位置 | 对象真实类型 | `send_json()` 做什么 |
| --- | --- | --- |
| `_send_event()` 内 | `DurableEventSink` | 转给任务服务持久化/广播 |
| `_broadcast()` 内 | FastAPI/Starlette `WebSocket` | 通过网络发送给浏览器 |

真实 WebSocket 在 `start_job(data, ws)` 中以 `subscriber` 传入，并由：

```python
self._subscribers[request_id][id(ws)] = ws
```

保存。`DurableEventSink` 则在 `_run_job()` 中另外创建：

```python
sink = DurableEventSink(self, job.request_id)
```

所以 Sink 不是 WebSocket，也不保存 WebSocket；它只持有 `GenerationJobService` 和 `request_id`。任务服务再通过 `request_id` 找到当前订阅连接。

## 3. Notebook 分单元格观察

### Cell 1：定义只依赖 `send_json()` 的调用者

- 输入：任何具有异步 `send_json()` 的对象；
- 依赖：无；
- 预期：调用者不检查具体类；
- 观察：形参名不决定真实类型，方法契约才决定。

```python
async def emit_status(target, text: str) -> None:
    await target.send_json({"type": "status", "content": text})
```

代码解释：这对应 `ws_agent.py` 的事件发送方式。主链中 target 可以是持久事件 Sink，而不一定是浏览器连接。

### Cell 2：实现直接连接与持久适配器

- 输入：无；
- 依赖：Cell 1；
- 预期：两个对象都能被 `emit_status()` 使用；
- 观察：它们没有公共父类。

```python
class DirectSocket:
    def __init__(self):
        self.sent = []

    async def send_json(self, payload: dict) -> None:
        self.sent.append(dict(payload))


class EventStore:
    def __init__(self):
        self.saved = []

    async def publish(self, request_id: str, payload: dict) -> None:
        self.saved.append((request_id, dict(payload)))


class DurableSinkAdapter:
    def __init__(self, store: EventStore, request_id: str):
        self.store = store
        self.request_id = request_id

    async def send_json(self, payload: dict) -> None:
        await self.store.publish(self.request_id, payload)

socket = DirectSocket()
store = EventStore()
sink = DurableSinkAdapter(store, "req-1")

await emit_status(socket, "直接发送")
await emit_status(sink, "持久发送")
print(socket.sent)
print(store.saved)
```

代码解释：`DurableSinkAdapter` 把 `publish(request_id, payload)` 适配成调用者需要的 `send_json(payload)`。

### Cell 3：验证同一接口产生不同副作用

- 输入：Cell 2 的结果；
- 依赖：Cell 2；
- 预期：直接对象写入 sent，适配器写入 store；
- 观察：统一接口不代表统一实现。

```python
assert socket.sent == [{"type": "status", "content": "直接发送"}]
assert store.saved == [
    ("req-1", {"type": "status", "content": "持久发送"})
]
print("ok：调用者未改变，输出边界已替换")
```

代码解释：这是08中“连接与任务解耦”的设计模式解释。Adapter 负责接口转换，事件保存和广播仍是 Service 的职责。

### Cell 4：归一化两种响应形状

- 输入：字典响应与对象响应；
- 依赖：无；
- 预期：都得到相同内部字典；
- 观察：归一化函数也属于适配层，但不一定需要一个 Adapter 类。

```python
class ObjectResponse:
    def __init__(self, content: str):
        self.content = content


def normalize_content(response: object) -> str:
    if isinstance(response, dict):
        return str(response.get("content") or "")
    return str(getattr(response, "content", "") or "")

assert normalize_content({"content": "字典结果"}) == "字典结果"
assert normalize_content(ObjectResponse("对象结果")) == "对象结果"
print("两种外部形状已收敛为字符串")
```

代码解释：真实 `message_texts()` 还处理多内容块、`additional_kwargs` 和 `response_metadata`，`LlmResult` 再统一 token 与 finish reason。

### Cell 5：主动传入缺少接口的对象

- 输入：普通 `object()`；
- 依赖：Cell 1；
- 预期：捕获 `AttributeError`；
- 排查方向：调用者要求的方法 → 工厂/适配器返回类型 → 是否传错物理连接或 Sink。

```python
try:
    await emit_status(object(), "无法发送")
except AttributeError as exc:
    print(type(exc).__name__, str(exc))
```

代码解释：鸭子类型减少继承依赖，但错误会在实际调用时暴露，因此接口契约要靠类型检查和测试保护。

### Cell 6：完整观察 Sink 到真实 WebSocket 的第二跳

- 输入：一个任务服务、一个假 WebSocket 和一个 Durable Sink；
- 依赖：Cell 1；
- 预期：调用方只调用 Sink，最终事件却进入假 WebSocket；
- 观察：Sink 和 WebSocket 的 `send_json()` 分别承担不同职责。

```python
class FakeWebSocket:
    def __init__(self):
        self.network_messages = []

    async def send_json(self, payload: dict) -> None:
        self.network_messages.append(dict(payload))


class ForwardingJobService:
    def __init__(self):
        self.saved_events = []
        self.subscribers = {}

    def attach(self, request_id: str, subscriber) -> None:
        self.subscribers.setdefault(request_id, []).append(subscriber)

    async def publish_event(self, request_id: str, payload: dict) -> None:
        event = dict(payload)
        self.saved_events.append((request_id, event))
        for subscriber in self.subscribers.get(request_id, []):
            await subscriber.send_json(event)


class MiniDurableSink:
    def __init__(self, service: ForwardingJobService, request_id: str):
        self.service = service
        self.request_id = request_id

    async def send_json(self, payload: dict) -> None:
        await self.service.publish_event(self.request_id, payload)


job_service = ForwardingJobService()
real_socket = FakeWebSocket()
job_service.attach("req-1", real_socket)
durable_sink = MiniDurableSink(job_service, "req-1")

await emit_status(durable_sink, "处理中")

assert job_service.saved_events == [
    ("req-1", {"type": "status", "content": "处理中"})
]
assert real_socket.network_messages == [
    {"type": "status", "content": "处理中"}
]
print(real_socket.network_messages)
```

代码解释：`emit_status()` 只调用了一次 `durable_sink.send_json()`；任务服务保存事件后遍历订阅者，第二次调用的是 `real_socket.send_json()`。这就是当前生产链的两跳关联。

### Cell 7：断开订阅者后再次发送

- 输入：清空该请求的订阅者；
- 依赖：Cell 6；
- 预期：事件仍保存，但浏览器收件箱不再增加；
- 观察：持久任务不依赖某一条物理连接存活。

```python
job_service.subscribers["req-1"].clear()
await emit_status(durable_sink, "连接已断开但任务继续")

assert len(job_service.saved_events) == 2
assert len(real_socket.network_messages) == 1
print("已保存：", job_service.saved_events[-1])
print("网络消息数量：", len(real_socket.network_messages))
```

代码解释：Sink 仍能把事件送到任务服务，服务也仍能保存；只是当前没有 subscriber 可以实时接收。重新连接后由事件重放机制补发。

## 4. 补充知识点

`ReasoningChatOpenAI` 通过继承并覆盖受保护方法适配供应商返回。这种做法能复用 LangChain，但也依赖上游内部方法签名；源码用 `*args/**kwargs` 缓解版本差异，依赖升级时仍应运行兼容测试。

## 5. 完成检查

- [ ] 我能解释 `DurableEventSink` 适配了哪两个接口
- [ ] 我能区分 Sink 的 `send_json()` 与真实 WebSocket 的 `send_json()`
- [ ] 我能画出 `Sink → publish_event → _broadcast → WebSocket` 两跳链
- [ ] 我能区分 Adapter 与底层 Service
- [ ] 我能说出对象适配和继承适配的不同
- [ ] 我能解释为什么归一化函数也属于适配层
- [ ] 我知道鸭子类型失败会在调用点暴露
