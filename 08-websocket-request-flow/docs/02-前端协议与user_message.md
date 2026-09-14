# 第02章：前端协议与 `user_message`

## 本章目标

从 WildAgent 前端真实代码确认一条消息怎样被创建、序列化和发送，并在 Notebook 中用 Python 镜像协议结构。

## 前置知识

- Python 字典、列表和 JSON；
- TypeScript 对象与 Python 字典写法不同，但数据序列化后都是 JSON；
- 已完成第01章的源码定位方法。

## 1. 三个前端文件各负责什么

| 文件 | 真实职责 | 本章锚点 |
| --- | --- | --- |
| [`protocol.ts`](../../../WildAgent/wild-web/src/agent/protocol.ts) | 构造客户端请求 | `AGENT_PROTOCOL_VERSION`、`createUserMessageRequest()` |
| [`types/agent.ts`](../../../WildAgent/wild-web/src/types/agent.ts) | 声明消息联合类型 | `AgentMessage`、`UserMessageRequest` |
| [`agentBridge.ts`](../../../WildAgent/wild-web/src/agent/agentBridge.ts) | 读取 Store/场景并发送 | `sendUserMessage()`、`ws.send()` |

调用关系不是“类型文件主动调用协议文件”，而是：

```text
UI 调用 agentBridge.sendUserMessage(message)
→ 收集 session、scene、selection、history 等上下文
→ createUserMessageRequest(...)
→ JSON.stringify(request)
→ WebSocket.send(...)
```

当前 `UserMessageRequest` 的主要字段来自真实 `types/agent.ts`：

| 字段 | 来源或含义 |
| --- | --- |
| `request_id` / `session_id` | 本次请求与会话身份 |
| `scene_id` / `scene_revision` | 当前场景及其版本 |
| `message` | 用户输入 |
| `scene_summary` / `selection` / `blueprint` | 场景摘要、选中构件和当前蓝图 |
| `thinking_mode` / `precision_mode` | 思考展示和精密执行开关 |
| `procedural_materials_enabled` | 是否允许程序化材质 |
| `plan_mode` | 是否先进入计划与审核流程 |
| `recent_messages` | 最多若干条最近对话，用于消歧 |

## 2. 为什么需要 `protocol_version`

前后端可能不是同时部署。字段或语义变化后，版本号可以让双方尽早拒绝不兼容消息，而不是进入生成流程后才报一个难懂的错误。

当前前端创建请求时写入固定版本，后端允许缺失版本的兼容请求，也接受当前版本；明显不兼容的版本会被拒绝。

## 3. Notebook 分单元格观察

### Cell 1：构造 Python 版请求

- 输入：用户文本和最小会话信息；
- 依赖：无；
- 预期：得到可以 JSON 序列化的字典；
- 观察：客户端消息的 `type` 是分发依据，`request_id` 是一次操作的身份。

```python
from time import time
from uuid import uuid4

PROTOCOL_VERSION = "1.0"

def create_user_message_request(
    message: str,
    session_id: str,
    *,
    scene_id: str | None = None,
    scene_revision: int = 0,
    scene_summary: dict | None = None,
    selection: list[str] | None = None,
    blueprint: dict | None = None,
    thinking_mode: bool = False,
    precision_mode: bool = False,
    procedural_materials_enabled: bool = False,
    plan_mode: bool = False,
    recent_messages: list[dict] | None = None,
) -> dict:
    return {
        "type": "user_message",
        "protocol_version": PROTOCOL_VERSION,
        "request_id": f"req_{int(time() * 1000)}_{uuid4().hex[:9]}",
        "session_id": session_id,
        "scene_id": scene_id,
        "scene_revision": scene_revision,
        "message": message,
        "scene_summary": scene_summary or {},
        "selection": list(selection or []),
        "blueprint": blueprint,
        "thinking_mode": thinking_mode,
        "precision_mode": precision_mode,
        "procedural_materials_enabled": procedural_materials_enabled,
        "plan_mode": plan_mode,
        "recent_messages": list(recent_messages or []),
    }

request = create_user_message_request(
    "生成一个小型住宅",
    "session-demo",
    scene_id="scene-1",
    scene_revision=3,
    scene_summary={"element_count": 0},
    selection=[],
    blueprint={"version": "1.0", "elements": []},
    plan_mode=True,
)
request
```

代码解释：字段结构与当前 `createUserMessageRequest()` 对齐；Python 只用相近格式模拟 JavaScript 的时间戳加随机串算法。`list(selection or [])` 创建新列表，避免调用者随后修改原列表影响请求。

### Cell 2：模拟浏览器序列化

- 输入：`request`；
- 依赖：Cell 1；
- 预期：`wire_text` 是字符串，反序列化后字段不变；
- 观察：WebSocket 传输的是文本，不是 Python 字典对象。

```python
import json

wire_text = json.dumps(request, ensure_ascii=False)
decoded = json.loads(wire_text)

print(type(request).__name__, "→", type(wire_text).__name__, "→", type(decoded).__name__)
print(wire_text)
assert decoded == request
```

代码解释：`dumps` 把内存对象编码成 JSON 文本，`loads` 把文本解析回对象。`ensure_ascii=False` 只影响中文显示，不改变协议含义。

### Cell 3：验证消息身份边界

- 输入：两次工厂调用；
- 依赖：Cell 1；
- 预期：会话相同、请求编号不同；
- 观察：为什么后台服务能按请求去重而不是按会话去重。

```python
request_a = create_user_message_request("第一条", "session-demo")
request_b = create_user_message_request("第二条", "session-demo")

assert request_a["session_id"] == request_b["session_id"]
assert request_a["request_id"] != request_b["request_id"]
print("同一会话中的两个独立请求")
```

代码解释：一个会话可以多轮交互。如果用 `session_id` 代替 `request_id` 判断重复，第二条合法请求也可能被误判。

### Cell 4：用表格做协议单元测试

- 输入：合法与非法请求；
- 依赖：Cell 1；
- 预期：合法项通过，缺失关键字段的项失败；
- 观察：类型注解与运行时校验不是一回事。

```python
def validate_user_message(data: dict) -> list[str]:
    errors = []
    if data.get("type") != "user_message":
        errors.append("type 必须是 user_message")
    if not str(data.get("request_id", "")).strip():
        errors.append("缺少 request_id")
    if not str(data.get("message", "")).strip():
        errors.append("message 不能为空")
    return errors

cases = [
    (request, []),
    ({"type": "user_message", "message": "你好"}, ["缺少 request_id"]),
    ({"type": "ping", "request_id": "r1", "message": "你好"}, ["type 必须是 user_message"]),
]

for payload, expected in cases:
    actual = validate_user_message(payload)
    print(actual)
    assert actual == expected
```

代码解释：表格驱动测试把“输入—预期”放在一起，后面增加协议场景时不用复制整个测试流程。

### Cell 5：主动制造 JSON 错误

- 输入：缺少右花括号的 JSON；
- 依赖：Cell 2；
- 预期：捕获 `JSONDecodeError`；
- 排查顺序：原始文本 → 报错位置 → 是否在进入业务分支前失败。

```python
broken_wire_text = '{"type": "user_message"'

try:
    json.loads(broken_wire_text)
except json.JSONDecodeError as exc:
    print(type(exc).__name__, "位置：", exc.pos, "原因：", exc.msg)
```

代码解释：解析失败发生在消息分发之前，因此此时不应排查 LangGraph 节点或模型接口。

## 4. 重点观察

- 前端 TypeScript 类型只约束前端编译期，后端仍必须验证收到的 JSON；
- `JSON.stringify()` 与 Python 的 `json.dumps()` 承担同类职责；
- `request_id` 贯穿创建任务、事件归属和恢复；
- `protocol_version` 解决部署版本不一致，不是模型版本。

## 5. 补充知识点

`AgentMessage` 是 TypeScript 联合类型：不同 `type` 对应不同字段结构。前端 `switch (message.type)` 能据此缩小类型范围。第08章会继续看返回事件如何进入这个 `switch`。

## 6. 完成检查

- [ ] 我能说出三个前端文件的不同职责
- [ ] 我能解释对象、JSON 文本和反序列化对象的区别
- [ ] 我能解释 `request_id` 与 `session_id` 的区别
- [ ] 我能判断 JSON 解析错误发生在主链的哪一层
- [ ] 我已对照真实 `createUserMessageRequest()` 补充自己观察到的字段
