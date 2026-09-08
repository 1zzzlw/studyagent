# 第3章：WebSocket 接收与分发

## 本章目标

本章结束时，你能读懂 `agent_websocket()` 的连接生命周期，知道消息先按协议 `type` 分发，而不是直接按 LangGraph 节点名分发。

## 前置知识

- 已完成第2章的请求构造和协议校验；
- 知道 `await` 会等待异步操作，但等待期间可以把执行权交还事件循环；
- 知道 `receive_text()` 得到的是文本，不是 Python 字典。

## 1. 真实连接生命周期

当前 [`ws_agent.py`](../../../WildAgent/wild-server/app/api/ws_agent.py) 中的主结构可以缩减为：

```text
@router.websocket("/ws/agent")
→ await ws.accept()
→ 创建并启动 heartbeat
→ presence_service.connect(ws)
→ while connection_alive
    → raw = await ws.receive_text()
    → heartbeat.touch()
    → json.loads(raw)
    → 检查 protocol_version
    → 按 data["type"] 分发
→ WebSocketDisconnect / 其他异常
→ finally
    → generation_job_service.detach(ws)
    → heartbeat.stop()
    → presence_service.disconnect(ws)
```

`receive_text()` 等待新消息时不会同步阻塞整个服务；其他协程仍可以运行。

## 2. 消息类型分发，不是节点分发

| 客户端 `type` | 后端动作 | 是否直接进入 Graph 节点 |
|---|---|---|
| `ping` | 返回 `pong` | 否 |
| `presence_identify` | 更新展示名 | 否 |
| `user_message` | 准备请求并创建/附着后台任务 | 间接进入 |
| `resume_generation` | 恢复订阅或补发事件 | 否 |
| `floor_plan_review` | 提交平面审核结果 | 恢复暂停的 Graph |
| `style_review` | 提交风格审核结果 | 恢复暂停的 Graph |
| `execution_plan_review` | 提交执行计划审核结果 | 恢复暂停的 Graph |
| `execution_feedback` | 把反馈放入运行中任务 | 间接影响 Graph |

所以不能在 `agent_websocket()` 里寻找 `architecture_node` 或 `chat_node` 的直接调用。`user_message` 下一跳是任务服务。

## 3. user_message 主分支

```python
data = _prepare_server_request(data, access_context)
job, created = await generation_job_service.start_job(data, ws)
if not created:
    await generation_job_service.resume_or_replay(...)
```

这三步分别表示：

1. 把不可信客户端输入收敛成服务端请求；
2. 尝试创建新任务；
3. 如果请求或会话已有任务，不重复生成，而是恢复订阅和事件。

## 4. 为什么主循环必须保持轻量

如果接收循环直接 `await` 一次几十秒或几分钟的模型/Graph 执行，同一连接就难以及时处理：

- `ping`；
- 审核消息；
- 执行反馈；
- 恢复请求；
- 连接关闭。

因此主循环负责协议和调度，耗时工作交给后台任务。

## 5. Notebook 分单元格练习

建立 `# 第3章：WebSocket接收与分发`。

### Cell 1：定义假 WebSocket

- 依赖：第2章的 `AGENT_PROTOCOL_VERSION`；
- 是否联网：否；
- 预期：能够按顺序接收文本并记录服务端响应。

```python
class FakeWebSocket:
    def __init__(self, incoming_texts: list[str]):
        self.incoming_texts = list(incoming_texts)
        self.sent_messages: list[dict] = []
        self.accepted = False

    async def accept(self):
        self.accepted = True

    async def receive_text(self) -> str:
        if not self.incoming_texts:
            raise StopAsyncIteration
        return self.incoming_texts.pop(0)

    async def send_json(self, payload: dict):
        self.sent_messages.append(dict(payload))
```

### Cell 2：定义轻量消息分发器

- 依赖：Cell 1、导入 `json`；
- 是否联网：否；
- 输入：一个假连接；
- 输出：收到的用户请求列表和连接响应记录。

```python
async def send_event(ws: FakeWebSocket, payload: dict):
    await ws.send_json({
        "protocol_version": AGENT_PROTOCOL_VERSION,
        **payload,
    })


async def receive_loop(ws: FakeWebSocket) -> list[dict]:
    started_jobs: list[dict] = []
    await ws.accept()

    while True:
        try:
            raw = await ws.receive_text()
        except StopAsyncIteration:
            break

        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            await send_event(ws, {
                "type": "error",
                "error": "消息格式错误，需要JSON",
            })
            continue

        version = data.get("protocol_version")
        if version not in (None, AGENT_PROTOCOL_VERSION):
            await send_event(ws, {
                "type": "error",
                "error": f"不支持的协议版本：{version}",
            })
            continue

        message_type = data.get("type")
        if message_type == "ping":
            await send_event(ws, {
                "type": "pong",
                "timestamp": data.get("timestamp"),
            })
        elif message_type == "user_message":
            started_jobs.append(dict(data))
        else:
            await send_event(ws, {
                "type": "error",
                "error": f"未知消息类型：{message_type}",
            })

    return started_jobs
```

这个函数是学习用缩减版，只保留 `ping` 和 `user_message` 两条分支，不代表 WildAgent 完整实现。

### Cell 3：运行一次 ping 和一次 user_message

- 依赖：Cell 2、第2章的 `message_request`；
- 是否联网：否；
- 预期：一个 `pong`，一个准备创建任务的请求。

```python
incoming = [
    json.dumps({
        "protocol_version": "1.0",
        "type": "ping",
        "timestamp": 123456,
    }),
    json.dumps(message_request, ensure_ascii=False),
]

fake_ws = FakeWebSocket(incoming)
started_jobs = await receive_loop(fake_ws)

print("连接已接受：", fake_ws.accepted)
print("准备启动的任务数：", len(started_jobs))
print("发送的事件：", fake_ws.sent_messages)
```

### Cell 4：验证消息类型与节点名无关

- 依赖：Cell 3；
- 是否联网：否；
- 观察点：当前只知道要创建任务，还不知道 Graph 会走哪个节点。

```python
queued_request = started_jobs[0]

print("协议消息类型：", queued_request["type"])
print("是否已有intent：", "intent" in queued_request)
print("是否已有node：", "node" in queued_request)

assert queued_request["type"] == "user_message"
assert "intent" not in queued_request
assert "node" not in queued_request
```

意图和节点选择发生在后续 Graph 内，而不是前端请求协议中。

### Cell 5：主动运行异常输入

- 依赖：Cell 2；
- 是否联网：否；
- 主动错误：非法 JSON、错误协议版本、未知类型；
- 预期：连接循环继续处理，并返回三条错误事件。

```python
bad_ws = FakeWebSocket([
    "not-json",
    json.dumps({
        "protocol_version": "9.9",
        "type": "ping",
    }),
    json.dumps({
        "protocol_version": "1.0",
        "type": "unknown",
    }),
])

bad_jobs = await receive_loop(bad_ws)

print("任务数：", len(bad_jobs))
for event in bad_ws.sent_messages:
    print(event["type"], "=>", event["error"])

assert len(bad_ws.sent_messages) == 3
```

### Cell 6：写下接收循环职责

- 类型：Markdown Cell；
- 预期：分别写“做什么”和“不做什么”。

```markdown
## agent_websocket 的职责边界

它负责：
- 

它不负责：
- 

user_message 的下一跳是：

我之前为什么会在这里找不到具体节点：
```

## 6. 常见问题

### 为什么 `receive_text()` 可以一直等待

它是异步等待，连接没有消息时会挂起当前协程，但不会用同步循环占满线程。

### 为什么错误消息后使用 continue

单条消息格式错误不一定代表整条连接必须关闭。服务端回复错误后继续等待下一条消息。

## 7. 练习题

1. 为缩减版循环增加 `presence_identify`，只记录展示名，不创建任务。
2. 给 `user_message` 增加 `request_id` 门禁，观察错误发生在任务创建前还是后。
3. 解释为什么不应该让前端直接发送 `node="architecture"` 控制后端路由。

## 8. 完成检查

- [ ] 我能说出连接生命周期的开始和结束
- [ ] 我能解释消息类型分发与节点路由的区别
- [ ] 我运行了假 WebSocket 接收循环
- [ ] 我证明 user_message 中还没有 intent 和 node
- [ ] 我触发了三类输入错误并观察连接继续处理
- [ ] 我用自己的话写出了接收循环职责
