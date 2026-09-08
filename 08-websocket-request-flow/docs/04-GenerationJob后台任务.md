# 第4章：GenerationJob 后台任务

## 本章目标

本章结束时，你能解释 `GenerationJobService` 为什么存在，能跟踪 `start_job → _spawn → _run_job → runner`，并能区分任务、事件接收者和 WebSocket 连接。

## 前置知识

- 已知道 `agent_websocket()` 的 `user_message` 分支不会直接执行 Graph；
- 知道 `asyncio.create_task()` 会创建可并发推进的后台协程任务；
- 能在 Notebook 中直接使用顶层 `await`。

## 1. 当前主调用链

```text
agent_websocket()
→ generation_job_service.start_job(payload, ws)
→ 校验 request_id
→ 检查同一 session 是否已有活动任务
→ 检查 request_id 是否已经存在
→ 把任务写入 SQLite
→ attach(request_id, ws)
→ _spawn(job, resume=False)
→ asyncio.create_task(_run_job(...))
→ DurableEventSink
→ runner(sink, payload, resume)
```

源码：[`generation_job_service.py`](../../../WildAgent/wild-server/app/services/generation_job_service.py)。

## 2. 为什么不把 ws 直接传到底层 Graph

当前 `_run_job()` 创建 `DurableEventSink`，runner 收到的是 sink，不是某一条真实浏览器连接：

```text
Graph/runner 只会 sink.send_json(event)
→ sink 调用 service.publish_event()
→ 服务决定持久化和广播给哪些连接
```

这样任务执行与连接解耦：

- 浏览器断开时，任务对象仍由服务持有；
- 新连接可以重新成为 subscriber；
- 关键事件可以从数据库补发；
- Graph 代码不用知道当前有几个浏览器连接。

## 3. start_job 的去重语义

返回值是 `(job, created)`：

| 情况 | 返回 | 调用方后续动作 |
|---|---|---|
| 新 request、新 session 空闲 | 新任务，`True` | 后台开始执行 |
| 相同 request 已存在 | 旧任务，`False` | 恢复订阅或补发 |
| 同 session 有另一个活动任务 | 活动任务，`False` | 附着已有任务，不重复生成 |
| request_id 为空 | 抛出 `ValueError` | 请求失败 |

这不是 LangGraph 节点重试，而是请求级幂等和会话并发控制。

## 4. runner 从哪里注册

服务启动时：

```text
main.py lifespan
→ startup_generation_jobs()
→ generation_job_service.startup(_run_persistent_langgraph)
```

因此 `_run_job()` 中的 `self._runner` 实际指向 `_run_persistent_langgraph()`。这是从任务服务继续跟到 Graph 的关键线索。

## 5. Notebook 分单元格练习

建立 `# 第4章：GenerationJob后台任务`。

### Cell 1：定义任务、订阅者和事件出口

- 依赖：导入 `asyncio`、`dataclass`；
- 是否联网：否；
- 预期：获得三个职责分开的最小对象。

```python
import asyncio
from dataclasses import dataclass


@dataclass
class DemoJob:
    request_id: str
    session_id: str
    payload: dict
    status: str = "running"
    last_event_seq: int = 0


class DemoSubscriber:
    def __init__(self, name: str):
        self.name = name
        self.messages: list[dict] = []

    async def send_json(self, event: dict):
        self.messages.append(dict(event))


class DemoDurableSink:
    def __init__(self, service, request_id: str):
        self.service = service
        self.request_id = request_id

    async def send_json(self, event: dict):
        await self.service.publish_event(self.request_id, event)
```

### Cell 2：实现最小任务服务

- 依赖：Cell 1；
- 是否联网：否；
- 输入：runner；
- 预期：支持创建、去重、执行、持久化事件和广播。

```python
class DemoJobService:
    def __init__(self, runner):
        self.runner = runner
        self.jobs: dict[str, DemoJob] = {}
        self.active_by_session: dict[str, str] = {}
        self.subscribers: dict[str, list[DemoSubscriber]] = {}
        self.events: dict[str, list[dict]] = {}
        self.tasks: dict[str, asyncio.Task] = {}

    async def attach(self, request_id: str, subscriber: DemoSubscriber):
        self.subscribers.setdefault(request_id, []).append(subscriber)

    async def start_job(
        self,
        payload: dict,
        subscriber: DemoSubscriber,
    ) -> tuple[DemoJob, bool]:
        request_id = str(payload.get("request_id") or "")
        session_id = str(payload.get("session_id") or request_id)
        if not request_id:
            raise ValueError("request_id不能为空")

        active_request_id = self.active_by_session.get(session_id)
        if active_request_id:
            return self.jobs[active_request_id], False

        if request_id in self.jobs:
            return self.jobs[request_id], False

        job = DemoJob(request_id, session_id, dict(payload))
        self.jobs[request_id] = job
        self.active_by_session[session_id] = request_id
        await self.attach(request_id, subscriber)

        task = asyncio.create_task(
            self._run_job(job),
            name=f"demo-graph:{request_id}",
        )
        self.tasks[request_id] = task
        return job, True

    async def _run_job(self, job: DemoJob):
        sink = DemoDurableSink(self, job.request_id)
        try:
            await self.runner(sink, job.payload, False)
        except Exception:
            job.status = "failed"
            raise
        else:
            job.status = "completed"
        finally:
            self.active_by_session.pop(job.session_id, None)

    async def publish_event(self, request_id: str, event: dict):
        stored_events = self.events.setdefault(request_id, [])
        stored = {
            **event,
            "event_seq": len(stored_events) + 1,
        }
        stored_events.append(stored)

        for subscriber in self.subscribers.get(request_id, []):
            await subscriber.send_json(stored)
```

这是教学缩减版：使用内存字典代替 SQLite，所有事件都持久化，也没有锁和异常广播。

### Cell 3：注册并运行假 runner

- 依赖：Cell 2；
- 是否联网：否；
- 预期：`start_job()` 很快返回，后台任务随后产生两条事件。

```python
async def demo_runner(sink, payload: dict, resume: bool):
    await sink.send_json({
        "type": "agent_step",
        "request_id": payload["request_id"],
        "node": "classifier",
        "status": "running",
    })
    await asyncio.sleep(0)
    await sink.send_json({
        "type": "agent_reply",
        "request_id": payload["request_id"],
        "content": "这是后台任务返回的结果",
    })


subscriber_a = DemoSubscriber("browser-A")
job_service = DemoJobService(demo_runner)

demo_payload = {
    "type": "user_message",
    "request_id": "req_job_001",
    "session_id": "session_job_001",
    "message": "测试后台任务",
}

demo_job, created = await job_service.start_job(
    demo_payload,
    subscriber_a,
)

print("created：", created)
print("刚返回时状态：", demo_job.status)
print("任务名：", job_service.tasks[demo_job.request_id].get_name())

await job_service.tasks[demo_job.request_id]

print("执行后状态：", demo_job.status)
print("浏览器事件：", subscriber_a.messages)
```

### Cell 4：验证相同 request 不重复执行

- 依赖：Cell 3；
- 是否联网：否；
- 预期：返回旧任务且 `created=False`。

```python
subscriber_b = DemoSubscriber("browser-B")
same_job, created_again = await job_service.start_job(
    demo_payload,
    subscriber_b,
)

print("是否同一任务对象：", same_job is demo_job)
print("是否新建：", created_again)

assert same_job is demo_job
assert created_again is False
```

注意：真实调用方发现 `created=False` 后会继续调用 `resume_or_replay()`，把新连接附着到已有任务；缩减版这里没有自动补发。

### Cell 5：验证同一会话的活动任务门禁

- 依赖：Cell 2；
- 是否联网：否；
- 预期：第二个 request 不会创建第二个并发任务。

```python
runner_gate = asyncio.Event()


async def blocking_runner(sink, payload: dict, resume: bool):
    await sink.send_json({
        "type": "agent_step",
        "request_id": payload["request_id"],
        "node": "classifier",
        "status": "running",
    })
    await runner_gate.wait()


blocking_service = DemoJobService(blocking_runner)
first_subscriber = DemoSubscriber("first")
second_subscriber = DemoSubscriber("second")

first_job, first_created = await blocking_service.start_job(
    {
        "request_id": "req_active_001",
        "session_id": "session_shared",
    },
    first_subscriber,
)
second_job, second_created = await blocking_service.start_job(
    {
        "request_id": "req_active_002",
        "session_id": "session_shared",
    },
    second_subscriber,
)

print(first_created, second_created)
print("返回的活动任务：", second_job.request_id)
assert second_job is first_job
assert second_created is False

runner_gate.set()
await blocking_service.tasks[first_job.request_id]
```

### Cell 6：主动触发缺少 request_id

- 依赖：Cell 2；
- 是否联网：否；
- 预期：创建后台 Task 之前就失败。

```python
try:
    await job_service.start_job(
        {"session_id": "session_without_request"},
        DemoSubscriber("invalid"),
    )
except ValueError as exc:
    print("预期任务门禁错误：", exc)
```

### Cell 7：写下任务边界总结

- 类型：Markdown Cell；
- 预期：回答谁持有任务和谁接收事件。

```markdown
## 我的 GenerationJob 总结

- start_job 的输入：
- start_job 的输出：
- _spawn 创建：
- _run_job 调用：
- DurableEventSink 隔离了：
- subscriber 表示：
- WebSocket 断开后，任务为什么不必立即消失：
```

## 6. 常见问题

### created=False 是否表示失败

不表示。它可能说明同一个 request 已存在，或同一 session 已有活动任务。调用方会尝试恢复订阅和补发事件。

### asyncio Task 是否就是 GenerationJob

不是。`GenerationJob` 是可持久化的业务任务记录；`asyncio.Task` 是当前进程里运行协程的执行对象。

## 7. 练习题

1. 为缩减版增加 `resume_or_replay()`，让 `subscriber_b` 收到历史事件。
2. 让 runner 抛出异常，观察 `DemoJob.status` 是否变成 `failed`。
3. 解释真实实现为什么需要事件锁，而缩减版暂时没有。

## 8. 完成检查

- [ ] 我能讲出 `start_job → _spawn → _run_job → runner`
- [ ] 我能区分 GenerationJob 与 asyncio Task
- [ ] 我能解释 DurableEventSink 的目的
- [ ] 我验证了相同请求不会重复执行
- [ ] 我验证了同一会话的活动任务门禁
- [ ] 我触发了缺少 request_id 的错误
- [ ] 我用自己的话完成了任务边界总结
