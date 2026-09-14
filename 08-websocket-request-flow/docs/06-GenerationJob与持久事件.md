# 第06章：`GenerationJob` 与持久事件

## 本章目标

理解 `GenerationJobService` 为什么把耗时生成与某一条 WebSocket 连接分开，以及 `DurableEventSink` 怎样统一“记录事件”和“广播事件”。

## 前置知识

- Python 类、实例属性和 `dataclass`；
- 异步方法与依赖注入；
- 第05章的 `start_job(payload, subscriber)`。

## 1. 只读源码切片

文件：[`generation_job_service.py`](../../../WildAgent/wild-server/app/services/generation_job_service.py)

本章只读下面这些成员，不展开数据库表和 Checkpoint 细节：

| 成员 | 责任 |
| --- | --- |
| `GenerationJob` | 保存请求、会话、载荷、状态、最后事件序号和错误 |
| `start_job()` | 检查重复任务、持久化任务、附着订阅者、启动 runner |
| `DurableEventSink.send_json()` | 把类似 WebSocket 的发送接口适配为持久事件发布 |
| `publish_event()` | 分配事件序号、保存并广播 |
| `attach()` / `detach()` | 维护当前可接收实时事件的连接 |
| `resume_or_replay()` | 重新附着并补发指定序号后的事件 |

最关键的依赖方向：

```text
Graph 处理函数只需要 sink.send_json(payload)
                    ↓
             DurableEventSink
                    ↓
        GenerationJobService.publish_event
          ↙ 持久化             ↘ 广播
```

Graph 不需要知道当前浏览器连接是哪一个。

### `send_json()` 为什么最后还能到 WebSocket

`DurableEventSink` 没有继承 `WebSocket`。当前链路依靠两个对象恰好都提供异步 `send_json(payload)`：

```text
ws_agent._send_event(sink, payload)
→ sink.send_json(versioned_payload)                 # DurableEventSink
→ service.publish_event(request_id, payload)
→ service._append_event(...)                        # 仅关键事件持久化
→ service._broadcast(request_id, event)
→ subscriber.send_json(event)                       # 这里才是真实 WebSocket
→ 浏览器
```

真实连接在 `start_job(payload, subscriber)` 中通过 `attach(request_id, subscriber)` 存进 `_subscribers`。后台 `_run_job()` 创建的 Sink 只保存任务服务和 `request_id`，然后由任务服务用该编号找到零个、一个或多个当前连接。

因此：

- 有连接时：事件先按规则持久化，再实时广播；
- 连接断开时：任务和关键事件仍可继续保存；
- 重新连接时：`resume_or_replay()` 重新 attach，并按 `event_seq` 补发。

09模块第05章会从 Adapter 和鸭子类型角度，用假 WebSocket Cell 完整观察这两次同名方法调用。

## 2. Notebook 分单元格观察

### Cell 1：定义最小任务数据

- 输入：请求与会话编号；
- 依赖：无；
- 预期：打印一个结构清楚的任务对象；
- 观察：`dataclass` 自动生成初始化与展示方法。

```python
from dataclasses import dataclass

@dataclass
class MiniJob:
    request_id: str
    session_id: str
    payload: dict
    status: str = "running"
    last_event_seq: int = 0
    error: str | None = None

job = MiniJob("req-1", "session-1", {"message": "生成住宅"})
job
```

代码解释：类描述“任务拥有哪些状态”，不负责执行。`str | None` 表示错误可以没有值，类型注解本身不会阻止错误类型赋值。

### Cell 2：实现最小事件服务

- 输入：请求编号与事件；
- 依赖：Cell 1；
- 预期：事件获得递增序号，同时写入历史与在线订阅者；
- 观察：历史事件和实时发送是两个独立结果。

```python
class MiniEventService:
    def __init__(self):
        self.events: dict[str, list[dict]] = {}
        self.subscribers: dict[str, list[list[dict]]] = {}

    def attach(self, request_id: str, inbox: list[dict]) -> None:
        self.subscribers.setdefault(request_id, []).append(inbox)

    def detach(self, request_id: str, inbox: list[dict]) -> None:
        current = self.subscribers.get(request_id, [])
        if inbox in current:
            current.remove(inbox)

    async def publish_event(self, request_id: str, payload: dict) -> dict:
        history = self.events.setdefault(request_id, [])
        event = dict(payload)
        event["event_seq"] = len(history) + 1
        history.append(event)
        for inbox in self.subscribers.get(request_id, []):
            inbox.append(dict(event))
        return event
```

代码解释：`setdefault()` 在键不存在时创建容器。事件复制后再加序号，避免修改调用者传入的原字典。

### Cell 3：实现 `DurableEventSink` 的核心接口

- 输入：事件服务和请求编号；
- 依赖：Cell 2；
- 预期：`send_json()` 把事件交给服务；
- 观察：它与 WebSocket 具有相同方法名，却有不同实现。

```python
class MiniDurableEventSink:
    def __init__(self, service: MiniEventService, request_id: str):
        self.service = service
        self.request_id = request_id
        self.failed = False
        self.error: str | None = None

    async def send_json(self, payload: dict) -> None:
        if payload.get("type") == "error":
            self.failed = True
            self.error = str(payload.get("error") or "任务返回错误事件")
        await self.service.publish_event(self.request_id, payload)
```

代码解释：这是适配器思想：调用方仍使用 `send_json()`，实现却从“直接发给一个连接”变成“交给任务服务持久化并广播”。模式名称将在09模块系统学习。

### Cell 4：观察连接存在时的持久化与广播

- 输入：一个订阅者列表和两个事件；
- 依赖：Cell 2、3；
- 预期：历史与收件箱都有两条，序号是1、2；
- 观察：同一事件走了持久化和实时广播两条支路。

```python
event_service = MiniEventService()
browser_inbox: list[dict] = []
event_service.attach("req-1", browser_inbox)
sink = MiniDurableEventSink(event_service, "req-1")

await sink.send_json({"type": "agent_step", "status": "running"})
await sink.send_json({"type": "agent_reply", "content": "完成"})

assert [item["event_seq"] for item in event_service.events["req-1"]] == [1, 2]
assert browser_inbox == event_service.events["req-1"]
print("历史：", event_service.events["req-1"])
print("实时收件箱：", browser_inbox)
```

代码解释：当前简化实现用内存列表代替数据库和 WebSocket，只保留了你需要观察的双写边界。

### Cell 5：断开后事件仍然存在

- 输入：解绑订阅者后再发布一条事件；
- 依赖：Cell 4；
- 预期：历史变为3条，旧收件箱仍是2条；
- 观察：没有订阅者不等于任务不能产生事件。

```python
event_service.detach("req-1", browser_inbox)
await sink.send_json({"type": "agent_step", "status": "completed"})

assert len(event_service.events["req-1"]) == 3
assert len(browser_inbox) == 2
print("断线后历史数量：", len(event_service.events["req-1"]))
print("断线后实时收件箱数量：", len(browser_inbox))
```

代码解释：这正是任务与物理连接解耦的最小证明。真实项目还会把任务、事件和 Graph Checkpoint 存进 SQLite。

### Cell 6：主动发送错误事件

- 输入：`type=error`；
- 依赖：Cell 3～5；
- 预期：sink 标记失败且事件继续写入历史；
- 排查方向：区分“任务发布错误事件”和“发送接口自身抛异常”。

```python
await sink.send_json({"type": "error", "error": "模拟失败"})

assert sink.failed is True
assert sink.error == "模拟失败"
assert event_service.events["req-1"][-1]["type"] == "error"
print(sink.failed, sink.error)
```

代码解释：错误也是需要被前端看到和被恢复逻辑重放的业务事件，因此不能因为它代表失败就不保存。

## 3. 回到真实测试寻找证据

只读 [`test_generation_job_service.py`](../../../WildAgent/wild-server/tests/network/test_generation_job_service.py)，优先找这些测试名表达的行为：

- 无订阅者时任务继续并持久化；
- 服务重启后恢复并重放；
- 历史补发先于新的实时事件；
- Graph 暂停等待审核不是失败。

这些是生产行为的证据；Notebook 小实验只是帮助理解对象关系，不能替代真实回归测试。

## 4. 补充知识点

`GenerationPaused` 是业务控制流异常：它表示 Graph 已保存暂停点并等待输入，不应被当成失败。10模块会从 LangGraph 的 `interrupt`、Checkpoint 和恢复命令解释这一点。

## 5. 完成检查

- [ ] 我能区分任务状态、历史事件和实时订阅者
- [ ] 我能解释 `DurableEventSink` 为什么保留 `send_json()` 接口
- [ ] 我观察到解绑连接后事件仍能保存
- [ ] 我知道错误事件也需要持久化
- [ ] 我没有把本章内存示例误认为 WildAgent 的真实数据库实现
