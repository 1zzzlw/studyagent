# 第03章：WebSocket 连接生命周期

## 本章目标

读懂 `agent_websocket()` 中连接建立、循环接收、心跳/在线状态启动，以及无论怎样退出都执行清理的结构。

## 前置知识

- `async def`、`await`、`try/finally`；
- 第02章的 JSON 文本；
- 暂时不研究每一种 `type` 的内部逻辑。

## 1. 真实入口的骨架

只读入口：[`ws_agent.py`](../../../WildAgent/wild-server/app/api/ws_agent.py) 中的 `@router.websocket("/ws/agent")` 与 `agent_websocket()`。

精简后的结构是：

```python
async def lifecycle_shape(ws):
    await ws.accept()
    heartbeat = "创建并启动心跳"
    presence = "登记在线状态"
    try:
        while True:
            raw_text = await ws.receive_text()
            # 解析和分发放在第04章
    finally:
        # 停止心跳、解绑订阅者、移除在线状态
        pass
```

这段是学习用骨架，不是从源码复制出的可运行路由。真实函数还会读取请求头、处理断开异常、调用 Presence 服务和任务服务。

## 2. 为什么清理必须放在 `finally`

接收循环可能因为多种原因结束：

- 浏览器主动断开；
- 网络异常；
- JSON 或业务处理抛出异常；
- 服务关闭。

`finally` 不关心正常还是异常，只要控制流离开 `try` 就执行，因此适合释放连接相关资源。

## 3. Notebook 分单元格观察

### Cell 1：创建只记录行为的假 WebSocket

- 输入：预设文本消息；
- 依赖：无；
- 预期：对象保存调用日志；
- 观察：假对象不联网，只实现当前切片需要的方法。

```python
class EndOfMessages(Exception):
    pass


class FakeWebSocket:
    def __init__(self, incoming: list[str]):
        self.incoming = list(incoming)
        self.calls: list[str] = []

    async def accept(self) -> None:
        self.calls.append("accept")

    async def receive_text(self) -> str:
        self.calls.append("receive_text")
        if not self.incoming:
            raise EndOfMessages()
        return self.incoming.pop(0)
```

代码解释：`list(incoming)` 创建副本，测试过程弹出元素时不会修改调用者原来的列表。`calls` 是可观察状态。

### Cell 2：写最小生命周期函数

- 输入：`FakeWebSocket`；
- 依赖：Cell 1；
- 预期：收到两条消息后仍执行三个清理步骤；
- 观察：执行顺序比返回值更重要。

```python
async def observe_lifecycle(ws: FakeWebSocket) -> list[str]:
    await ws.accept()
    ws.calls.append("heartbeat.start")
    ws.calls.append("presence.connect")
    try:
        while True:
            text = await ws.receive_text()
            ws.calls.append(f"message:{text}")
    except EndOfMessages:
        ws.calls.append("disconnect")
    finally:
        ws.calls.append("heartbeat.stop")
        ws.calls.append("subscriber.detach")
        ws.calls.append("presence.disconnect")
    return ws.calls

fake_ws = FakeWebSocket(["first", "second"])
calls = await observe_lifecycle(fake_ws)
calls
```

代码解释：Notebook 可直接顶层 `await`。本例用自定义异常代表连接结束，目的是观察控制流，不是模拟 FastAPI 的全部行为。

### Cell 3：验证关键顺序

- 输入：`calls`；
- 依赖：Cell 2；
- 预期：断言通过；
- 观察：清理动作必须出现在最后，并且只执行一次。

```python
assert calls[0] == "accept"
assert calls.index("heartbeat.start") < calls.index("receive_text")
assert calls[-3:] == [
    "heartbeat.stop",
    "subscriber.detach",
    "presence.disconnect",
]
assert calls.count("heartbeat.stop") == 1
print("ok：连接建立、接收、断开、清理顺序正确")
```

代码解释：`index()` 验证相对顺序，切片 `[-3:]` 验证尾部清理步骤。这样的断言比只打印日志更明确。

### Cell 4：主动制造处理中异常

- 输入：一条特殊消息；
- 依赖：Cell 1；
- 预期：即使抛出 `ValueError`，`finally` 中的标记仍存在；
- 排查顺序：异常发生位置 → finally 是否执行 → 哪些资源仍需清理。

```python
async def lifecycle_with_failure(ws: FakeWebSocket) -> None:
    await ws.accept()
    try:
        text = await ws.receive_text()
        if text == "boom":
            raise ValueError("模拟消息处理失败")
    finally:
        ws.calls.append("cleanup")

failed_ws = FakeWebSocket(["boom"])
try:
    await lifecycle_with_failure(failed_ws)
except ValueError as exc:
    print(type(exc).__name__, str(exc))

print(failed_ws.calls)
assert failed_ws.calls[-1] == "cleanup"
```

代码解释：`finally` 保证清理，但不会自动吞掉异常；如果没有 `except`，异常仍向调用者传播。

## 4. 回到 WildAgent 应该观察什么

在 `agent_websocket()` 中依次定位：

1. `await ws.accept()`；
2. `WebSocketHeartbeat(...)` 与 `start()`；
3. Presence 连接登记；
4. `while True` 和 `receive_text()`；
5. `finally` 中停止心跳、解绑任务订阅和断开 Presence。

暂时不要展开每个消息分支；第04章专门处理分发。

## 5. 补充知识点

WildAgent 的心跳创建时传入 `processing_probe`，用于知道当前连接是否关联仍在运行的生成任务。它避免把长时间没有普通消息误认为失联。具体心跳、断线和恢复放到第09章。

## 6. 完成检查

- [ ] 我能解释 `accept()` 为什么早于接收
- [ ] 我能解释 `while True` 为什么需要断开出口
- [ ] 我能用自己的话说明 `finally` 与 `except` 的区别
- [ ] 我能在真实函数中找到启动与清理对应位置
- [ ] 我已观察正常结束和处理中异常两种顺序
