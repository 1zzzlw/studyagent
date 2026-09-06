# 第五章：LangSmith Studio 完整入门

## 1. Studio、Agent Server 和 Graph 的关系

```text
app.py 中的 compiled graph
          ↓ 由 langgraph.json 声明
Agent Server（提供 HTTP API、Thread、Run、持久化）
          ↓ Studio 通过 API 地址连接
LangSmith Studio（可视化运行和调试界面）
```

Studio 不直接导入你电脑里的 Python 文件。它连接 Agent Server API，再由 Server 加载 Graph。

本章文件：

```text
05-studio/
├── app.py             # 最小 MessagesState Graph
├── langgraph.json     # 告诉 Agent Server 去哪里加载 Graph
├── test_graph.py      # 不经过 Server，直接调用 Graph
├── test_api.py        # 经过 localhost API 调用 Graph
└── Studio学习指南.md
```

## 2. 三种常见连接方式

### 方式一：本地 localhost（当前最推荐）

```text
Studio 网页 → http://127.0.0.1:2024 → 本地 Agent Server → 本地代码
```

特点：修改代码自动重载、无需部署、适合日常开发。

### 方式二：Tunnel 或可访问的远程 API URL

```text
Studio 网页 → https://某个可访问地址 → Agent Server → Graph
```

本质与 localhost 相同，区别只是 Server 地址能被浏览器访问。适用于浏览器禁止 localhost、远程开发机或团队测试环境。

### 方式三：LangSmith Deployment

```text
LangSmith Deployments → 选择部署 → Studio → 已部署 Agent Server
```

适合共享、稳定测试和生产部署。需要完成部署配置，不是入门阶段必须步骤。

所谓“API 连接”和“localhost 连接”不是两套完全不同的协议：localhost 本身就是本地 Agent Server API；远程方式只是把 API URL 换成远程地址。

## 3. 理解最小 Graph

`app.py` 使用 `MessagesState`：

```text
START → call_model → END
```

`call_model` 读取历史消息并返回一条 AI 消息。Server 将 `study_agent` 暴露为 Assistant/Graph ID。

先直接测试 Graph：

```powershell
cd E:\AgentProject\studyAgent\05-studio
uv run python test_graph.py
```

这一步不涉及 Studio，用来确认 Graph 和模型配置本身正常。

## 4. `langgraph.json` 是什么

```json
{
  "dependencies": [".."],
  "graphs": {
    "study_agent": "./app.py:graph"
  },
  "env": "../.env"
}
```

- `dependencies`：父目录有本项目 `pyproject.toml`；
- `graphs`：Graph ID 对应 Python 文件中的编译对象；
- `env`：加载项目根目录 `.env`。

`study_agent` 也是 API 调用中使用的 `assistant_id`。

## 5. 安装 CLI

`langgraph` 库负责写 Graph；`langgraph-cli[inmem]` 负责启动本地 Agent Server。安装：

```powershell
cd E:\AgentProject\studyAgent
uv add "langgraph-cli[inmem]"
```

确认：

```powershell
uv run langgraph --help
```

## 6. 启动 localhost Agent Server

```powershell
cd E:\AgentProject\studyAgent\05-studio
uv run langgraph dev
```

默认会显示：

```text
API: http://127.0.0.1:2024
Docs: http://127.0.0.1:2024/docs
Studio: https://smith.langchain.com/studio/?baseUrl=http://127.0.0.1:2024
```

保持终端运行。停止服务使用 `Ctrl+C`。

## 7. 通过 localhost 连接 Studio

可以使用任一方式：

1. `langgraph dev` 自动打开的 Studio 地址；
2. 手动访问 `https://smith.langchain.com/studio/?baseUrl=http://127.0.0.1:2024`；
3. 在 Studio 中选择连接本地 Server，输入 `http://127.0.0.1:2024`。

连接后选择 `study_agent`，输入：

```text
请用一句话介绍 LangGraph。
```

你应看到 `START → call_model → END` 和节点输入输出。

## 8. 通过 API 调用 localhost

Server 运行时另开一个终端：

```powershell
cd E:\AgentProject\studyAgent\05-studio
uv run python test_api.py
```

核心代码：

```python
client = get_client(url="http://127.0.0.1:2024")
result = await client.runs.wait(
    None,
    "study_agent",
    input={"messages": [{"role": "user", "content": "你好"}]},
)
```

第一个参数 `None` 表示无 Thread 的单次 Stateless Run。

## 9. Stateful Thread API

希望保留多轮状态时：

```python
thread = await client.threads.create()
thread_id = thread["thread_id"]

first = await client.runs.wait(
    thread_id,
    "study_agent",
    input={"messages": [{"role": "user", "content": "我叫小明"}]},
)

second = await client.runs.wait(
    thread_id,
    "study_agent",
    input={"messages": [{"role": "user", "content": "我叫什么？"}]},
)
```

同一个 `thread_id` 共享对话状态。Studio 的 Threads 页面可以查看这些状态和 Run。

## 10. Tunnel 连接

浏览器或网络阻止 `https` Studio 访问 `http://localhost` 时：

```powershell
uv run langgraph dev --tunnel
```

CLI 会提供临时公网 HTTPS URL。在 Studio 的连接界面填写该 URL。Tunnel 只适合开发调试，不应作为生产部署。

## 11. 连接远程或已部署 API

### 自己可访问的 Agent Server

Studio 中选择连接 Server，填写：

```text
https://your-agent-server.example.com
```

必须保证浏览器能访问，并正确配置 HTTPS、CORS 和认证。

### LangSmith Deployment

进入：

```text
Deployments → 选择应用 → Studio
```

平台会自动使用该 Deployment URL。远程 SDK 调用通常需要 API Key：

```python
client = get_client(
    url="https://你的部署地址",
    api_key=os.environ["LANGSMITH_API_KEY"],
)
```

## 12. `langgraph dev` 与 `langgraph up`

| 命令 | 环境 | 用途 |
|---|---|---|
| `langgraph dev` | 当前 Python 环境，无需 Docker | 快速开发、热重载、Studio 调试 |
| `langgraph up` | Docker 容器 | 部署前验证依赖、环境和容器行为 |

初学先用 `dev`。准备部署时再安装 Docker 并使用 `up`。

## 13. Studio 中重点学习什么

1. Graph 视图：节点和实际路径；
2. Input/Output：每个节点读写了哪些 State；
3. Threads：多轮对话状态；
4. Assistants：同一 Graph 的不同配置；
5. Time travel：从历史状态分叉重跑；
6. View LLM Runs：把某次模型调用送到 Playground；
7. Run experiment：让 Assistant 跑 LangSmith Dataset。

## 14. 常见故障

### Studio 显示 Failed to fetch

- 确认 `langgraph dev` 终端仍在运行；
- 打开 `http://127.0.0.1:2024/docs` 检查 API；
- 尝试 `--tunnel`；
- 检查代理、防火墙和浏览器 localhost 限制。

### Graph 加载失败

- 检查 `langgraph.json` 路径；
- 确认变量名确实是 `graph`；
- 先运行 `uv run python test_graph.py`；
- 检查 `.env` 中三个 LLM 配置。

### Studio 看不到历史对话

Stateless Run 没有 Thread。需要创建 Thread，或者直接在 Studio Chat 模式建立会话。

### 为什么本地调用成功，Server 启动失败

通常是 CLI 依赖、`langgraph.json`、工作目录或 Agent Server 环境加载问题，不是 Graph 业务逻辑问题。

## 15. 学完标准

你应能解释并完成：

```text
Python Graph
→ langgraph.json
→ langgraph dev
→ localhost:2024 Agent Server
→ Studio 或 SDK 客户端
```

官方参考：[Studio 快速开始](https://docs.langchain.com/langsmith/quick-start-studio)、[LangGraph CLI](https://docs.langchain.com/langsmith/cli)、[Agent Server API](https://docs.langchain.com/langsmith/server-api-ref)。
