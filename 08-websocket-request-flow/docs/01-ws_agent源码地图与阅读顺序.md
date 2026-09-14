# 第01章：`ws_agent.py` 源码地图与阅读顺序

## 本章目标

不从第一行硬读到最后一行，而是先把 `ws_agent.py` 划成区域，找到生产主入口，并用调用证据区分主链和遗留路径。

## 前置知识

- Python 的 `def`、`async def` 和装饰器；
- 已运行模块 README 中的路径 Cell；
- 本章只读 WildAgent 文件，不导入它。

## 1. 为什么不能按行顺序硬读

当前文件超过1700行，混合了四类代码：

| 区域 | 代表代码 | 阅读优先级 |
| --- | --- | --- |
| 事件辅助函数 | `_send_event()`、`_emit_agent_step()` | 第二轮 |
| 请求准备 | `_prepare_server_request()` | 主链 |
| WebSocket 路由 | `agent_websocket()` | 第一入口 |
| Graph 编排 | `_handle_with_langgraph()` | 主链边界 |
| 兼容或遗留函数 | `_handle_user_message()`、`_handle_with_langchain()` | 最后确认 |

源码中的函数出现得早，不代表它先执行。真正顺序由“谁调用谁”决定。

## 2. 当前源码锚点

只读文件：[`ws_agent.py`](../../../WildAgent/wild-server/app/api/ws_agent.py)

```text
_send_event                    统一发送协议事件
_prepare_server_request        清洗并补充请求
_run_persistent_langgraph      后台任务注册的 runner
@router.websocket("/ws/agent") 路由装饰器
agent_websocket                生产 WebSocket 接收循环
_handle_with_langgraph         Graph 调用与事件翻译
_handle_user_message           不是当前 user_message 主分支
_handle_with_langchain         保留的旧式处理路径
```

Python 基础对应关系：

- `@router.websocket(...)` 在函数定义时把函数注册为路由；
- `async def` 定义协程函数，调用后必须由 `await` 或任务调度执行；
- 名称以下划线开头表示模块内部使用约定，不等于不能被导入；
- 类型注解用于说明预期类型，不会自动完成运行时校验。

## 3. Notebook 分单元格观察

### Cell 1：读取源码并建立行列表

- 输入：`module_root`、`wildagent_root`；
- 依赖：模块 README 的路径 Cell；
- 预期：打印文件行数和前几行；
- 观察：这里只调用 `read_text()`，没有执行 WildAgent。

```python
ws_source_path = wildagent_root / "wild-server" / "app" / "api" / "ws_agent.py"
ws_source = ws_source_path.read_text(encoding="utf-8")
ws_lines = ws_source.splitlines()

print("源码路径：", ws_source_path)
print("当前总行数：", len(ws_lines))
print("前3行：", ws_lines[:3])
```

代码解释：`splitlines()` 把一个大字符串转换成列表，列表下标从0开始，而编辑器行号从1开始。

### Cell 2：列出顶层函数

- 输入：`ws_source`；
- 依赖：Cell 1；
- 预期：看到 `agent_websocket`、`_handle_with_langgraph` 等名称；
- 观察：同步函数与异步函数的数量。

```python
import re

function_pattern = re.compile(r"^(async\s+def|def)\s+([A-Za-z_]\w*)", re.MULTILINE)
function_rows = [
    {"kind": match.group(1), "name": match.group(2)}
    for match in function_pattern.finditer(ws_source)
]

for row in function_rows:
    print(f"{row['kind']:<9} {row['name']}")
```

代码解释：列表推导式逐个读取正则匹配；`group(1)` 是 `def` 类型，`group(2)` 是函数名。这里建立的是“目录”，还不是调用链。

### Cell 3：定位任意源码锚点

- 输入：源码行列表与锚点文本；
- 依赖：Cell 1；
- 预期：返回真实行号和该行内容；
- 观察：同一名称可能既出现在定义处，也出现在调用处。

```python
def find_lines(lines: list[str], needle: str) -> list[tuple[int, str]]:
    return [
        (line_number, line.strip())
        for line_number, line in enumerate(lines, start=1)
        if needle in line
    ]

for name in ["agent_websocket", "start_job(", "_handle_user_message("]:
    print(name, find_lines(ws_lines, name))
```

代码解释：`enumerate(..., start=1)` 让编号与编辑器一致。只出现定义、不出现调用，是“可能不在当前主链”的信号，但还要继续搜索其他文件和测试。

### Cell 4：做一个最小源码结构测试

- 输入：`ws_source`；
- 依赖：Cell 1；
- 预期：两个测试均为 `ok`；
- 观察：单元测试可以保护你依赖的源码锚点。

```python
def assert_source_contract(source: str) -> None:
    assert '@router.websocket("/ws/agent")' in source
    assert "generation_job_service.start_job(" in source
    assert "graph.astream_events(" in source

assert_source_contract(ws_source)
print("ok：入口、后台任务和 Graph 事件流锚点都存在")
```

代码解释：这不是测试业务结果，而是一个轻量“结构契约”。以后源码重构导致锚点消失时，你会立刻知道学习文档需要更新。

### Cell 5：主动制造定位失败

- 输入：一个不存在的旧节点名称；
- 依赖：Cell 3；
- 预期：结果为空列表；
- 排查顺序：拼写 → 当前分支 → 是否已重构删除 → 是否只存在旧文档。

```python
missing = find_lines(ws_lines, "floor_plan_review_required")
print("搜索结果：", missing)
assert missing == []
```

代码解释：搜索不到不是 Python 报错，而是一条源码证据。不要因为旧笔记写过某条链，就假设当前代码仍存在。

## 4. 一个重要的阅读陷阱

`ws_agent.py` 某些注释可能仍描述已经调整过的旧流程。判断当前行为时使用下面的证据优先级：

```text
当前调用点与 graph.py
> 当前自动化测试
> 当前注释
> 旧文档或聊天记录
```

本章不修改这些注释，只记录不一致；源码清理应在 WildAgent 的独立优化任务中完成。

## 5. 补充知识点

大型入口文件常同时存在“组合代码”和“业务代码”。组合代码负责把服务接起来，本身未必复杂；真正难点是职责混合。09模块会用 Facade、Adapter、Observer、Repository 等模式重新审视这些边界，但不会为了套模式而改代码。

## 6. 完成检查

- [ ] 我能说出为什么不能按文件行号推断执行顺序
- [ ] 我能用 `find_lines()` 找到函数定义和调用
- [ ] 我能区分结构测试与业务测试
- [ ] 我知道 `_handle_user_message()` 不是当前主分支的直接下一跳
- [ ] 我已在 Notebook 写下主链、辅助函数和遗留路径三类名称

