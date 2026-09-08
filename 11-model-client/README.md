# 11 · Model Client：从配置到统一模型调用

## 模块定位

- 前置模块：`10-langgraph-state-node-flow`，你已经知道节点在什么位置调用模型，以及结果怎样写回状态；
- 后续模块：`12-structured-output`，继续处理模型返回 JSON/Pydantic 后的解析与恢复；
- 本模块解决：聊天模型配置、客户端创建、消息调用、流式响应、统一结果、超时重试和供应商兼容；
- 本模块不包含：Agent Tool、LangGraph 路由、业务 Prompt、结构化输出修复和 Blueprint 生成。

本模块结合 WildAgent 源码做只读导读，但所有代码练习都由你在 studyAgent 自己维护的 Notebook 中完成，不运行或修改 WildAgent。

## 学习目标

学完后，你应该能够：

1. 从 `.env` 读取聊天模型配置，并创建 `ChatOpenAI`；
2. 区分创建 Client、发送请求和消费响应三个阶段；
3. 使用 `invoke()`、`ainvoke()`、`stream()` 和 `astream()`；
4. 从 `AIMessage` 或 `AIMessageChunk` 提取正文、推理扩展字段、Token Usage 和结束原因；
5. 区分 SDK 内部重试与业务外层重试；
6. 只重试429、5xx和超时等瞬态错误，不重试鉴权或参数错误；
7. 说明 WildAgent 为什么使用 `create_llm()` 和 `LlmResult`，而不是让每个节点直接操作 SDK。

## 章节目录

| 章节 | 核心问题 | Notebook 练习结果 |
|---|---|---|
| [第1章：先看完整调用链](docs/01-先看完整调用链.md) | 配置、Client、调用器和业务节点是什么关系？ | 画出并验证最小对象链路 |
| [第2章：配置与客户端工厂](docs/02-配置与客户端工厂.md) | 怎样把环境变量稳定地变成 `ChatOpenAI`？ | 创建客户端但不发请求 |
| [第3章：消息与非流式调用](docs/03-消息与非流式调用.md) | `invoke/ainvoke` 输入和返回的是什么？ | 完成一次真实问答并检查元数据 |
| [第4章：流式调用与结果拼接](docs/04-流式调用与结果拼接.md) | 为什么流式响应是一系列 Chunk？ | 逐块显示并还原完整回答 |
| [第5章：统一响应与Token Usage](docs/05-统一响应与TokenUsage.md) | 怎样屏蔽供应商返回结构差异？ | 把多种假响应归一化为同一结果 |
| [第6章：超时、重试与错误分类](docs/06-超时重试与错误分类.md) | 哪些错误该重试，哪些应该立即停止？ | 用离线假模型验证有限重试 |
| [第7章：WildAgent源码调用链](docs/07-WildAgent源码调用链.md) | 这些概念在真实项目中怎样组合？ | 能沿一个节点说明完整模型调用链 |

建议分三天完成：

```text
本模块第1天：第1～3章，配置、Client、非流式调用
本模块第2天：第4～5章，流式响应和统一结果
本模块第3天：第6～7章，超时重试和 WildAgent 源码导读
```

## Notebook 学习方法

请自行创建并维护：

```text
11-model-client/01.model-client.ipynb
```

仓库不会替你创建或填充这个 Notebook。每读完一章，再把该章的 Cell 逐个手写进去，运行后记录真实输出。

Notebook 第一个 Cell 使用下面的公共初始化代码：

```python
from pathlib import Path
import sys

current_dir = Path.cwd().resolve()
if current_dir.name == "11-model-client":
    MODULE_ROOT = current_dir
    PROJECT_ROOT = current_dir.parent
else:
    PROJECT_ROOT = current_dir
    MODULE_ROOT = PROJECT_ROOT / "11-model-client"

assert MODULE_ROOT.exists(), f"没有找到11模块：{MODULE_ROOT}"
sys.path.insert(0, str(PROJECT_ROOT))

print("Notebook工作目录：", current_dir)
print("studyAgent根目录：", PROJECT_ROOT)
print("11模块目录：", MODULE_ROOT)
```

Notebook 中不使用 `__file__`。Kernel 重启后，先重新运行公共初始化 Cell，再从当前章节第一个 Cell 开始。

## 环境配置边界

本模块只使用聊天模型变量：

```dotenv
LLM_MODEL=你的聊天模型
LLM_BASE_URL=https://你的聊天服务/v1
LLM_API_KEY=你的聊天密钥
```

不要把07模块的 `EMBEDDING_MODEL`、`EMBEDDING_BASE_URL`、`EMBEDDING_API_KEY` 传给 `ChatOpenAI`。

## 版本与资料依据

当前 studyAgent 安装版本：

| 依赖 | 当前版本 | 本模块用途 |
|---|---:|---|
| Python | 3.12+ | Notebook 和异步调用 |
| `langchain` | 1.4.0 | 消息与模型统一接口 |
| `langchain-core` | 1.6.2 | `AIMessage`、`AIMessageChunk` |
| `langchain-openai` | 1.6.0 | `ChatOpenAI` |
| `openai` | 3.8.0 | 底层 OpenAI-compatible SDK |
| `python-dotenv` | 1.2.3 | 根目录 `.env` 加载 |

官方资料：

- [LangChain ChatOpenAI](https://docs.langchain.com/oss/python/integrations/chat/openai)
- [LangChain Models](https://docs.langchain.com/oss/python/langchain/models)
- [OpenAI Python SDK](https://github.com/openai/openai-python)

第三方 OpenAI-compatible 服务通常能复用基础 Chat Completions，但 `reasoning_content` 等扩展字段并不是统一标准。本模块会先掌握标准字段，再理解 WildAgent 为什么需要兼容层。

## WildAgent 只读源码地图

```text
wild-server/config.py
→ ModelConfig：模型名、Base URL、Key、超时等配置

app/agent/model_client.py
→ create_llm()：创建 ChatOpenAI
→ ReasoningChatOpenAI：兼容推理字段和流式 Usage

app/agent/llm_invocation.py
→ invoke_llm()/stream_llm()：统一调用
→ LlmResult：统一结果

app/agent/model_errors.py
→ classify_model_error()：错误分类

app/agent/nodes/*.py
→ 业务节点只消费统一接口和统一结果
```

## 模块完成标准

- [ ] 能解释 `ChatOpenAI(...)` 为什么还没有调用模型
- [ ] 能独立完成同步与异步非流式调用
- [ ] 能逐块消费流式响应并拼出完整正文
- [ ] 能找到 Token Usage 和 finish reason
- [ ] 能说明第三方扩展字段为什么需要适配
- [ ] 能用假模型证明超时和有限重试逻辑
- [ ] 能从 WildAgent 节点追到 `create_llm()`、`invoke_llm()` 和 `LlmResult`
- [ ] 没有修改 WildAgent，也没有让项目替自己写完 Notebook
