# 第00章：Notebook 公共环境初始化

## 本章目标

显式建立 `module_root`、`studyagent_root` 和 `wildagent_root`，并把本模块会读取的真实源码统一放进 `source_paths`。这些变量只存在于当前 Kernel，重启后必须重新运行。

## Notebook 分单元格练习

## Cell 1：定位两个项目

- 输入：Notebook 当前目录；
- 前序依赖：无；
- 预期：兼容从 studyAgent 根目录或10模块目录启动；
- 观察：`wildagent_root` 应是 `E:\AgentProject\WildAgent`，不能指向 `wild-server`。

```python
from pathlib import Path

current_dir = Path.cwd().resolve()

if current_dir.name == "10-langgraph-state-node-flow":
    module_root = current_dir
elif (current_dir / "10-langgraph-state-node-flow").is_dir():
    module_root = current_dir / "10-langgraph-state-node-flow"
else:
    raise RuntimeError(
        "请从 studyAgent 根目录或 10-langgraph-state-node-flow 目录启动 Notebook"
    )

studyagent_root = module_root.parent
agent_project_root = studyagent_root.parent
wildagent_root = agent_project_root / "WildAgent"

print("当前目录：", current_dir)
print("studyAgent：", studyagent_root)
print("10模块：", module_root)
print("WildAgent（只读）：", wildagent_root)
```

## Cell 2：建立真实源码地图

- 输入：Cell 1 的三个路径；
- 前序依赖：Cell 1；
- 预期：逐项打印 `OK`；
- 观察：本模块不仅看 `graph.py`，还要看状态契约、节点、恢复入口和最终编译。

```python
source_paths = {
    "graph": wildagent_root / "wild-server/app/agent/graph.py",
    "state": wildagent_root / "wild-server/app/agent/graph_state.py",
    "architecture": wildagent_root / "wild-server/app/agent/nodes/architecture_node.py",
    "material": wildagent_root / "wild-server/app/agent/nodes/material_plan_node.py",
    "design_review": wildagent_root / "wild-server/app/agent/nodes/design_review_node.py",
    "skeleton": wildagent_root / "wild-server/app/agent/nodes/skeleton_node.py",
    "merge": wildagent_root / "wild-server/app/agent/nodes/merge_node.py",
    "contracts": wildagent_root / "wild-server/app/design/contracts.py",
    "resolver": wildagent_root / "wild-server/app/design/resolver.py",
    "repository": wildagent_root / "wild-server/app/design/repository.py",
    "ws": wildagent_root / "wild-server/app/api/ws_agent.py",
    "jobs": wildagent_root / "wild-server/app/services/generation_job_service.py",
}

for name, path in source_paths.items():
    assert path.is_file(), (name, path)
    print(f"OK  {name:13} {path.relative_to(wildagent_root)}")
```

## Cell 3：记录本次源码快照

- 输入：`source_paths`；
- 前序依赖：Cell 2；
- 预期：打印文件修改时间和行数；
- 观察：WildAgent 正在开发中，以你运行 Notebook 时的工作区为准。

```python
from datetime import datetime

source_snapshot = {}
for name, path in source_paths.items():
    stat = path.stat()
    source_snapshot[name] = {
        "lines": len(path.read_text(encoding="utf-8").splitlines()),
        "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
    }

source_snapshot
```

## Cell 4：只读加载源码

- 输入：`source_paths`；
- 前序依赖：Cell 2；
- 预期：得到 `sources: dict[str, str]`；
- 观察：只调用 `read_text()`，不会触发 WildAgent 的配置、模型或数据库初始化。

```python
sources = {
    name: path.read_text(encoding="utf-8")
    for name, path in source_paths.items()
}

assert "class GenerationState" in sources["state"]
assert "def build_generation_graph" in sources["graph"]
assert "class DesignDocument" in sources["contracts"]
assert "def design_review" in sources["design_review"]
print("源码已只读加载：", list(sources))
```

## 错误实验

重启 Kernel 后直接运行 Cell 2，应出现 `NameError: wildagent_root is not defined`。这说明 Notebook 的变量依赖执行历史，Markdown 中出现过变量名并不会创建它。

如果导入 LangGraph 时出现 `WinError 10106`，先继续所有只读源码 Cell。它属于 Windows 异步网络栈问题，不能据此判断 Graph 或 State 设计错误。

## 完成检查

- [ ] 三个根路径都已打印并核对
- [ ] 12 个源码文件全部存在
- [ ] 我保存了本次源码快照
- [ ] 我能解释为何本模块读取源码而不直接 import WildAgent
