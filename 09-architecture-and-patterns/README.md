# 09 · WildAgent 架构与设计模式源码导读

## 模块定位

- 前置模块：`08-websocket-request-flow`；
- 后续模块：`10-langgraph-state-node-flow`；
- 核心任务：用 WildAgent 当前源码理解模块边界、依赖方向和真实存在的设计模式；
- 学习载体：你自行维护的 `01.basic.ipynb`；
- 参考项目：`E:\AgentProject\WildAgent`，只读分析，不修改、不导入启动。

09不是设计模式名词大全。每个模式都必须回答：

```text
WildAgent 中谁参与
→ 调用者只依赖什么接口
→ 这个模式消除了哪种重复或耦合
→ 它又引入了什么代价
→ 对理解 LangGraph 有什么帮助
```

## 为什么09放在10前面

10会看到大量“函数作为节点”“工厂生成节点”“注册表批量建图”“包装器增强节点”“ContextVar 传递回调”。如果不知道函数也是对象、结构化接口、闭包和依赖注入，很容易把 `graph.py` 看成一堆杂乱导入。

09先建立这些结构认知，10再研究 State、Reducer、边和暂停恢复。

## 先给当前源码下结论

WildAgent 中确实存在有价值的模式，但代码并不因此自动变得整洁：

| 分类 | 当前源码证据 | 判断 |
| --- | --- | --- |
| 简单工厂 | `create_llm()`、`create_search_client()` | 明确存在 |
| 策略与结构化接口 | `SearchClient(Protocol)`、Tavily/Mock 实现 | 明确存在 |
| 注册表 | `COMPONENT_REGISTRY`、`ComponentConfig` | 明确存在 |
| 参数化节点工厂 | `create_component_generator/validator()` | 明确存在 |
| 适配层 | `DurableEventSink`、`ReasoningChatOpenAI`、`LlmResult` | 适配器式设计 |
| 观察者/发布订阅 | `attach/detach/_broadcast`、Presence 广播 | 明确存在 |
| 装饰器式包装 | `_planned_node(step_type, node)` | 高阶函数包装 |
| 作用域依赖注入 | `ContextVar` 的 bind/get/reset | Python 运行时机制 |
| 启动期回调注入 | `startup(_run_persistent_langgraph)` → `self._runner(...)` | 单一异步 Callback/Strategy，不是事件通知 |
| 统一服务入口 | `AgentService`、`commit_generation_result()` | Facade/Service/Transaction Script 风格 |
| 全局实例与缓存 | `agent_service`、`generation_job_service`、`_graphs` | Singleton/Multiton 风格，同时有代价 |
| 前端通信门面 | `AgentBridge`、模块级 `agentBridge` | 封装连接、协议、恢复和 Store 协作 |

本模块会严格区分：

- “源码明确命名并实现的模式”；
- “具有某种模式作用，但不是教科书实现”；
- “只是框架 API 或普通 Python 技巧”；
- “看似模式，实际是耦合或历史负担”。

## 章节目录

| 章节 | WildAgent 源码重点 | Notebook 观察结果 |
| --- | --- | --- |
| [00 Notebook 公共环境初始化](docs/00-Notebook公共环境初始化.md) | 定义 `module_root`、`wildagent_root` 并验证源码路径 | 后续章节不再出现路径变量未定义 |
| [01 真实模块与依赖地图](docs/01-真实模块与依赖地图.md) | `api/services/agent/spec/tools` 的真实导入 | 找到正常依赖和反向依赖 |
| [02 简单工厂与对象创建](docs/02-简单工厂与对象创建.md) | `create_llm()`、`create_search_client()` | 改配置而不改调用者 |
| [03 Protocol 与策略模式](docs/03-Protocol与策略模式.md) | `SearchClient`、Tavily、Mock | 不继承也能满足统一接口 |
| [04 注册表与组件节点工厂](docs/04-注册表与组件节点工厂.md) | `COMPONENT_REGISTRY`、节点闭包、批量建图 | 新增配置如何产生 gen/val 节点 |
| [05 Adapter 与统一结果](docs/05-Adapter与统一结果.md) | Event Sink、模型响应适配、`LlmResult` | 同一调用接口连接不同实现 |
| [06 Observer 与事件广播](docs/06-Observer与事件广播.md) | 任务订阅者、Presence 广播 | 观察 attach/detach/broadcast |
| [07 高阶函数与节点包装](docs/07-高阶函数与节点包装.md) | `_planned_node()` | 原节点不改也能补计划状态 |
| [08 ContextVar 与运行时依赖](docs/08-ContextVar与运行时依赖.md) | reasoning callback、feedback poller | 理解非序列化依赖为何不进 State |
| [09 服务入口、runner 回调、全局对象与重构边界](docs/09-服务入口全局对象与重构边界.md) | `AgentService`、`GenerationJobService._runner`、交付入口、Graph 缓存、反向依赖 | 观察函数注册后怎样被后台任务回调，并形成模式证据与耦合清单 |

建议用两天完成：

```text
Day 9：先完成第00章，再学习第01～04章的模块依赖、Factory、Strategy、Registry
Day 10：第05～09章，Adapter、Observer、节点包装、ContextVar、全局边界
```

## Notebook 使用方式

请自行创建并维护：

```text
09-architecture-and-patterns/01.basic.ipynb
```

本模块不会代写 Notebook，也不会创建 `.py` 测试工程。每章代码都按 Cell 拆开，先预测输出，再亲手输入并运行。

开始第01章前，必须先完成[第00章公共环境初始化](docs/00-Notebook公共环境初始化.md)。把下面这个公共 Cell 放到你自己的 Notebook 最前面；每次重启 Kernel 后都要重新运行：

```python
from pathlib import Path

current_dir = Path.cwd().resolve()
module_root = current_dir if current_dir.name == "09-architecture-and-patterns" else current_dir / "09-architecture-and-patterns"
wildagent_root = module_root.parents[1] / "WildAgent"

assert module_root.exists(), module_root
assert wildagent_root.exists(), wildagent_root

print("09模块：", module_root)
print("WildAgent（只读）：", wildagent_root)
```

代码解释：后续源码观察只使用 `read_text()`。不要从 Notebook 导入 WildAgent 模块，因为模块级单例可能在导入时加载配置、模型客户端或存储。

当前环境的 `import asyncio` 仍可能触发 Windows `WinError 10106`。第03章涉及异步策略调用，可以先完成代码阅读与语法输入，等环境恢复后再执行顶层 `await`；不要因此修改策略接口或 LangGraph。

## 模块边界

09只回答“这些对象为什么这样连接”：

```text
Factory 创建对象
Strategy 替换行为
Registry 保存可扩展配置
Adapter 对齐接口
Observer 分发事件
Wrapper 增强节点
ContextVar 注入当前运行依赖
Service/Facade 提供统一入口
Global/Cache 管理生命周期
```

10才回答：

```text
GenerationState 的字段由谁写入
→ Reducer 怎样合并并行返回
→ 条件边为什么选择下一节点
→ Send/Command 怎样改变执行
→ Checkpoint、interrupt 和恢复怎样协作
```

## 完成标准

- [ ] 我能画出 `api → services → agent/spec/tools` 的主要依赖，并指出反向依赖
- [ ] 我能区分简单工厂、策略、注册表和适配器
- [ ] 我能解释 `SearchClient` 为什么不要求显式继承
- [ ] 我能解释一个 `ComponentConfig` 怎样变成两个 Graph 节点
- [ ] 我能区分 Event Sink 的适配责任与 Service 的广播责任
- [ ] 我能解释 `_planned_node()` 中闭包捕获了什么
- [ ] 我能解释回调为什么放进 `ContextVar` 而不是持久化 State
- [ ] 我能区分模块级单例与 `get_graph()` 的按键缓存
- [ ] 我能解释 `_run_persistent_langgraph` 如何被注册进 `_runner`，以及它为什么不是“通知事件”
- [ ] 我能用源码证据指出至少两个好边界和两个耦合风险
- [ ] 我没有修改 WildAgent，也没有让工具替我填完 Notebook
