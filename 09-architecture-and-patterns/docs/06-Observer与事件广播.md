# 第06章：Observer 与事件广播

## 本章目标

从 `GenerationJobService` 和 Presence 注册表理解发布者、订阅者、事件广播与失效订阅者清理。

## 前置知识

- 列表、字典和可调用对象；
- 第05章中 Event Sink 只负责把事件交给 Service；
- 第08模块的事件回传链。

## 1. 两套真实观察者关系

### 生成任务事件

```text
发布者：GenerationJobService
订阅关系：request_id → WebSocket subscribers
订阅：attach(request_id, subscriber)
退订：detach(subscriber)
通知：_broadcast(request_id, event)
```

### Presence 快照

```text
发布者：WebSocketConnectionRegistry
观察者：当前连接集合
状态变化：connect / update_display_name / disconnect
通知：_broadcast_locked() 发送 presence_update
```

只读源码：

- [`generation_job_service.py`](../../../WildAgent/wild-server/app/services/generation_job_service.py)；
- [`presence/service.py`](../../../WildAgent/wild-server/app/extensions/presence/service.py)。

这是一种 Observer/Publish-Subscribe 风格。它没有独立消息中间件，订阅表只存在于当前 Python 进程。

## 2. Notebook 分单元格观察

### Cell 1：定义最小发布者

- 输入：无；
- 依赖：无；
- 预期：发布者维护主题到回调列表；
- 观察：回调函数本身可以存入容器。

```python
class EventPublisher:
    def __init__(self):
        self.subscribers: dict[str, list[object]] = {}

    def attach(self, topic: str, subscriber) -> None:
        self.subscribers.setdefault(topic, []).append(subscriber)

    def detach(self, topic: str, subscriber) -> None:
        current = self.subscribers.get(topic, [])
        if subscriber in current:
            current.remove(subscriber)

    def broadcast(self, topic: str, event: dict) -> list[Exception]:
        failures = []
        for subscriber in list(self.subscribers.get(topic, [])):
            try:
                subscriber(dict(event))
            except Exception as exc:
                failures.append(exc)
                self.detach(topic, subscriber)
        return failures
```

代码解释：`list(...)` 创建快照，避免广播过程中删除订阅者导致迭代错位。真实实现复制连接集合，并异步调用 `send_json()`。

### Cell 2：订阅两个观察者并广播

- 输入：两个收件箱回调；
- 依赖：Cell 1；
- 预期：两个收件箱都收到独立事件副本；
- 观察：发布者不关心观察者如何展示事件。

```python
publisher = EventPublisher()
inbox_a = []
inbox_b = []

def observer_a(event: dict) -> None:
    inbox_a.append(event)

def observer_b(event: dict) -> None:
    inbox_b.append(event)

publisher.attach("req-1", observer_a)
publisher.attach("req-1", observer_b)
failures = publisher.broadcast("req-1", {"type": "agent_step", "status": "running"})

assert failures == []
assert inbox_a == inbox_b
assert inbox_a[0] is not inbox_b[0]
print(inbox_a, inbox_b)
```

代码解释：事件内容相等，但字典身份不同。一个观察者修改自己的副本，不会污染另一个观察者收到的值。

### Cell 3：退订后不再接收

- 输入：已有订阅关系；
- 依赖：Cell 2；
- 预期：A 收到第二条，B 不再收到；
- 观察：连接结束应清理订阅关系，但后台任务可继续发布。

```python
publisher.detach("req-1", observer_b)
publisher.broadcast("req-1", {"type": "agent_reply", "content": "完成"})

assert len(inbox_a) == 2
assert len(inbox_b) == 1
print("A：", len(inbox_a), "B：", len(inbox_b))
```

代码解释：退订改变实时接收者，不应删除已持久化任务事件。持久化属于任务服务的另一条职责。

### Cell 4：主动制造失效观察者

- 输入：一个会抛异常的订阅者；
- 依赖：Cell 1；
- 预期：错误被记录，坏订阅者被移除，其他订阅者仍收到；
- 观察：单个连接失败不应阻止整次广播。

```python
received = []

def broken_observer(event: dict) -> None:
    raise ConnectionError("模拟连接失效")

def healthy_observer(event: dict) -> None:
    received.append(event)

failure_publisher = EventPublisher()
failure_publisher.attach("req-2", broken_observer)
failure_publisher.attach("req-2", healthy_observer)
failures = failure_publisher.broadcast("req-2", {"type": "presence_update"})

assert len(failures) == 1
assert len(received) == 1
assert broken_observer not in failure_publisher.subscribers["req-2"]
print(type(failures[0]).__name__, received)
```

代码解释：真实生成任务广播也收集失败连接后统一移除；Presence 则在剔除失效连接后重新广播修正后的在线人数。

### Cell 5：验证主题隔离

- 输入：另一个 request_id；
- 依赖：Cell 2；
- 预期：`req-1` 的观察者不收到 `req-3` 事件；
- 观察：生成事件按请求隔离，不是向所有连接全局广播。

```python
before_count = len(inbox_a)
publisher.broadcast("req-3", {"type": "agent_reply", "content": "其他任务"})

assert len(inbox_a) == before_count
print("不同 request_id 没有串线")
```

代码解释：Presence 是全体连接快照，GenerationJob 是按 `request_id` 订阅；两者都广播，但主题范围不同。

## 3. 补充知识点

当前订阅关系只在单进程内存中。如果以后部署多个 Server 进程，某个进程产生的事件不会自动通知另一个进程持有的连接，需要 Redis Pub/Sub、消息队列或共享事件分发层。这是部署架构问题，不是本模块要求立即实现的功能。

## 4. 完成检查

- [ ] 我能指出生成任务广播中的发布者和订阅者
- [ ] 我能区分按 request_id 广播和 Presence 全局快照
- [ ] 我能解释广播前为什么复制订阅者列表
- [ ] 我观察到一个订阅者失败不会阻止其他订阅者
- [ ] 我能区分 Observer 与 DurableEventSink Adapter
