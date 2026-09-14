# 第00章：Notebook 公共环境初始化

## 本章目标

在09模块所有源码观察 Cell 之前，统一定义 `module_root` 和 `wildagent_root`，避免直接从某一章节开始时出现 `NameError: name 'wildagent_root' is not defined`。

## 为什么会出现这个错误

`wildagent_root` 不是 Python 或 Jupyter 自动提供的变量。它必须由前面的 Cell 创建，并且只存在于当前 Notebook Kernel 的内存中。

出现下面任一情况都需要重新运行本章：

- 新建 Notebook 后直接复制第01章代码；
- 重启了 Kernel；
- 执行了“清除所有输出并重启”；
- 单独运行依赖 `wildagent_root` 的后续 Cell；
- 从另一个工作目录启动 Jupyter。

## Cell 1：定位 studyAgent 与 WildAgent

- 输入：当前 Notebook 工作目录；
- 依赖：无，这必须是09模块最先运行的代码 Cell；
- 预期：打印09模块和只读 WildAgent 根目录；
- 观察：支持从 `studyAgent` 根目录或09模块目录启动 Notebook。

```python
from pathlib import Path

current_dir = Path.cwd().resolve()

if current_dir.name == "09-architecture-and-patterns":
    module_root = current_dir
elif (current_dir / "09-architecture-and-patterns").is_dir():
    module_root = current_dir / "09-architecture-and-patterns"
else:
    raise RuntimeError(
        "没有找到09模块。请从 studyAgent 根目录或 "
        "09-architecture-and-patterns 目录启动 Notebook。"
    )

agent_project_root = module_root.parent.parent
wildagent_root = agent_project_root / "WildAgent"

print("当前工作目录：", current_dir)
print("09模块：", module_root)
print("WildAgent（只读）：", wildagent_root)
```

代码解释：当 Notebook 工作目录是 `E:\AgentProject\studyAgent` 时，从当前目录进入09模块；当工作目录已经是09模块时直接使用当前目录。再向上两级得到 `E:\AgentProject`，最后拼出相邻的 `WildAgent`。

## Cell 2：验证关键源码确实存在

- 输入：Cell 1 定义的两个路径；
- 依赖：Cell 1；
- 预期：三个断言通过；
- 观察：路径变量存在不等于路径一定正确，所以要立即验证。

```python
graph_path = wildagent_root / "wild-server" / "app" / "agent" / "graph.py"
ws_agent_path = wildagent_root / "wild-server" / "app" / "api" / "ws_agent.py"

assert module_root.is_dir(), module_root
assert graph_path.is_file(), graph_path
assert ws_agent_path.is_file(), ws_agent_path

print("公共路径初始化完成")
```

代码解释：报错信息会直接打印实际拼出来的路径。若失败，先检查 Jupyter 的 `Path.cwd()`，不要修改 WildAgent 源码或复制源码到 studyAgent。

## Cell 3：确认只读方式可以读取源码

- 输入：`graph_path`；
- 依赖：Cell 2；
- 预期：打印 `graph.py` 的前几行；
- 观察：只调用 `read_text()`，不会导入或启动 WildAgent。

```python
graph_preview = graph_path.read_text(encoding="utf-8").splitlines()[:8]

for line in graph_preview:
    print(line)
```

代码解释：09模块只把 WildAgent 当作源码资料。不要执行 `sys.path.insert()` 后 import WildAgent，因为导入可能初始化配置、全局服务、模型客户端或数据库。

## 常见错误

### `NameError: wildagent_root is not defined`

原因：Cell 1 没运行，或者 Kernel 重启后变量被清空。回到本章依次运行 Cell 1、Cell 2。

### `RuntimeError: 没有找到09模块`

原因：Notebook 从其他目录启动。先运行：

```python
from pathlib import Path
print(Path.cwd().resolve())
```

代码解释：只观察当前目录。确认后从 `E:\AgentProject\studyAgent` 或09模块目录重新打开 Notebook。

## 补充知识点

Jupyter 的 Cell 共享同一个 Kernel 命名空间，所以后续 Cell 能使用前面创建的变量；但执行顺序可以跳跃。看到 `In [数字]` 不连续时，应先确认公共初始化 Cell 是否在本次 Kernel 会话中运行过。

## 完成检查

- [ ] 我把 Cell 1 放在自己的09模块 Notebook 最前面
- [ ] `module_root` 指向 `09-architecture-and-patterns`
- [ ] `wildagent_root` 指向相邻的 `WildAgent`
- [ ] `graph.py` 与 `ws_agent.py` 路径断言通过
- [ ] 我知道 Kernel 重启后必须重新运行公共初始化

