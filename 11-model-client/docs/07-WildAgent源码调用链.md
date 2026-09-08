# 第7章：回到 WildAgent 阅读真实调用链

## 本章目标

把前6章的零散知识放回 WildAgent，回答下面几个问题：

- 配置怎样进入聊天模型客户端；
- 普通调用和流式思考调用怎样选择；
- 为什么节点不直接处理供应商原始响应；
- 超时、重试、错误分类和诊断分别在哪一层；
- 哪些代码是通用模型调用能力，哪些代码是 WildAgent 业务逻辑。

本章只阅读 WildAgent。不要在 Notebook 中导入、启动或修改 WildAgent 源码。

## 前置知识

- 已完成第2章的配置与客户端工厂；
- 已完成第4章的流式收集；
- 已完成第5章的统一结果；
- 已完成第6章的超时、重试和错误分类。

## 1. 先记住完整链路

WildAgent 当前不只有一条模型调用路径，但它们共享相同的底层能力：

```text
.env / 运行时配置
→ config.py：Settings.chat / ModelConfig
→ model_client.py：create_llm(...)
→ ReasoningChatOpenAI
→ LangChain ChatModel 协议
→ llm_invocation.py：invoke_llm(...) / stream_llm(...)
→ LlmResult
→ AgentService 或 LangGraph 节点读取统一结果
→ 状态、诊断、日志或最终响应
```

要特别注意两个入口：

```text
服务式入口：AgentService 初始化时创建普通客户端和流式思考客户端
节点式入口：chat_node、base_component_node 等节点按本次调用需要创建客户端
```

这意味着“谁持有客户端”可以不同，但“客户端怎样创建”和“结果怎样归一化”已经集中到公共模块。

## 2. 按顺序阅读源码

不要打开一个大文件从第一行读到最后一行。按下面顺序，每次只回答一个问题。

| 顺序 | 源码 | 只关注什么 |
|---|---|---|
| 1 | [`config.py`](../../../WildAgent/wild-server/config.py) | `ModelConfig` 与 `Settings.chat` 保存哪些连接参数 |
| 2 | [`model_client.py`](../../../WildAgent/wild-server/app/agent/model_client.py) | `create_llm()` 怎样把配置变成客户端 |
| 3 | [`llm_invocation.py`](../../../WildAgent/wild-server/app/agent/llm_invocation.py) | 完整响应与流式分块怎样变成 `LlmResult` |
| 4 | [`model_errors.py`](../../../WildAgent/wild-server/app/agent/model_errors.py) | 哪些错误允许重试 |
| 5 | [`agent_service.py`](../../../WildAgent/wild-server/app/services/agent_service.py) | 服务初始化时为什么创建两种客户端 |
| 6 | [`chat_node.py`](../../../WildAgent/wild-server/app/agent/nodes/chat_node.py) | 简单节点怎样非流式调用并消费结果 |
| 7 | [`base_component_node.py`](../../../WildAgent/wild-server/app/agent/nodes/base_component_node.py) | 复杂节点怎样在流式和非流式之间选择 |

## 3. 配置层：这里只描述连接，不发请求

`config.py` 中的 `ModelConfig` 描述一项 OpenAI-compatible 聊天服务，主要字段包括：

```text
name
api_key
base_url
thinking_budget
timeout
max_retries
```

`Settings.chat` 持有聊天模型配置。`Settings.embedding` 和 `Settings.rerank` 是另外两项配置，不要因为都使用“模型”二字就混用。

```text
Settings.chat       → 对话与 Agent 推理
Settings.embedding  → 文档和问题向量化
Settings.rerank     → 候选文档重排
```

配置对象只是数据。真正创建客户端的是下一层的 `create_llm()`。

## 4. 工厂层：把差异关在 create_llm 里面

`create_llm()` 主要做四件事：

1. 没有显式传入配置时，读取 `config.chat`；
2. 把模型名、密钥、地址和超时交给 `ReasoningChatOpenAI`；
3. 根据 `streaming` 决定是否启用流式响应和流式 Token Usage；
4. 根据供应商与模型能力，决定是否添加思考参数。

调用方看到的接口很小：

```python
llm = create_llm(
    enable_thinking=False,
    streaming=False,
)
```

供应商的思考参数并不是统一协议。WildAgent 的 `_thinking_extra_body()` 只对已知供应商和已知模型组合进行映射；遇到未知端点时返回 `None`，避免盲目加入扩展字段导致400参数错误。

这条原则很重要：

```text
OpenAI-compatible
≠ 每个供应商的扩展字段也完全兼容
```

## 5. 兼容层：为什么不是直接使用 ChatOpenAI

`ReasoningChatOpenAI` 继承 `ChatOpenAI`，补充了两类兼容处理：

- 非流式响应：从供应商原始响应中恢复 `reasoning_content`；
- 流式响应：从每个 chunk 中恢复思考增量，并保留最终 Usage。

另外，`content_as_text()` 和 `message_texts()` 把字符串、内容块、普通正文和推理正文转换成稳定文本。

因此节点不需要反复判断：

```text
content 是字符串还是内容块？
reasoning_content 在 additional_kwargs 还是 response_metadata？
usage 使用 prompt_tokens 还是 input_tokens？
```

这些差异应在客户端兼容层和调用收集层消化，而不是扩散到每个节点。

## 6. 调用层：统一返回 LlmResult

`llm_invocation.py` 定义了统一结果：

```python
@dataclass
class LlmResult:
    content: str = ""
    reasoning: str = ""
    token_usage: dict[str, int] | None = None
    finish_reason: str | None = None
    retry_count: int = 0
```

两种入口最终返回同一种类型：

| 调用函数 | 底层协议 | 收集方式 | 返回值 |
|---|---|---|---|
| `invoke_llm()` | `llm.ainvoke(messages)` | 收集一条完整消息 | `LlmResult` |
| `stream_llm()` | `llm.astream(messages)` | 累加多个 chunk | `LlmResult` |

`invoke_llm()` 对被判定为瞬态的错误做有限重试；`stream_llm()` 为每次等待下一个 chunk 设置超时，发生异常时向上抛出。节点只消费归一化结果或处理异常，不再自己解析供应商响应。

## 7. 业务层：两处真实用法

### 7.1 chat_node：最直接的非流式路径

`chat_node.py` 的核心顺序是：

```text
整理 system/user messages
→ create_llm(enable_thinking=False, streaming=False)
→ await invoke_llm(llm, messages)
→ 读取 llm_result.content
→ 读取 llm_result.token_usage
→ 写回节点结果
```

这条路径最适合第一次跟读，因为它没有复杂的思考流式分支。

### 7.2 base_component_node：根据场景选择调用方式

`base_component_node.py` 会先判断本次是否启用思考模式，以及是否存在思考内容回调：

```text
thinking_mode 且有回调
→ create_llm(enable_thinking=True, streaming=True)
→ stream_llm(...)

其他情况
→ create_llm(..., streaming=False)
→ invoke_llm(...)
```

流式不是“答案质量更高”的开关。这里使用流式，是为了让思考增量能够及时通过回调进入进度事件，同时最后仍得到完整的 `LlmResult`。

## 8. AgentService 为什么创建两个客户端

`AgentService.__init__()` 中会创建：

```text
self.llm          → 普通模式
self.thinking_llm → 流式思考模式
```

两者使用同一份聊天连接配置，但运行选项不同。运行时配置更新后，`reload_chat_models()` 会先创建新客户端，再替换旧客户端及相关 Agent。

不要把它理解成两个不同用途的模型配置。它表达的是：

```text
同一个聊天模型连接
+ 不同的调用模式
= 两个可分别持有的客户端对象
```

## 9. Notebook 分单元格练习

建立 `# 第7章：WildAgent源码调用链`。下面的练习全部在 studyAgent 内离线完成，只复现结构，不导入 WildAgent。

### Cell 1：把源码地图变成可查询数据

- 依赖：无；
- 是否联网：否；
- 预期：能够从业务入口一路找到配置和调用层。

```python
source_map = {
    "config": {
        "file": "wild-server/config.py",
        "symbols": ["ModelConfig", "Settings.chat"],
        "question": "连接参数从哪里来？",
    },
    "factory": {
        "file": "wild-server/app/agent/model_client.py",
        "symbols": ["create_llm", "ReasoningChatOpenAI"],
        "question": "配置怎样变成客户端？",
    },
    "invocation": {
        "file": "wild-server/app/agent/llm_invocation.py",
        "symbols": ["invoke_llm", "stream_llm", "LlmResult"],
        "question": "供应商响应怎样变成统一结果？",
    },
    "errors": {
        "file": "wild-server/app/agent/model_errors.py",
        "symbols": ["classify_model_error"],
        "question": "失败后是否应该重试？",
    },
    "consumer": {
        "file": "wild-server/app/agent/nodes/chat_node.py",
        "symbols": ["chat_node"],
        "question": "业务节点怎样消费结果？",
    },
}

for layer, info in source_map.items():
    print(f"{layer:10} -> {info['file']}")
    print(" " * 14, info["question"])
```

### Cell 2：复现“配置”和“运行模式”分离

- 依赖：无；
- 是否联网：否；
- 输入：一份连接配置、两种运行选项；
- 输出：两份不同的客户端创建参数。

```python
from dataclasses import dataclass


@dataclass(frozen=True)
class DemoModelConfig:
    name: str
    api_key: str
    base_url: str
    timeout: float = 60.0
    thinking_budget: int = 0


def build_client_options(
    config: DemoModelConfig,
    *,
    enable_thinking: bool,
    streaming: bool,
) -> dict:
    return {
        "model": config.name,
        "base_url": config.base_url,
        "timeout": config.timeout,
        "enable_thinking": enable_thinking,
        "streaming": streaming,
        "stream_usage": streaming,
    }


demo_config = DemoModelConfig(
    name="demo-chat-model",
    api_key="not-used-in-offline-demo",
    base_url="https://example.invalid/v1",
    timeout=30.0,
)

normal_options = build_client_options(
    demo_config,
    enable_thinking=False,
    streaming=False,
)
thinking_options = build_client_options(
    demo_config,
    enable_thinking=True,
    streaming=True,
)

print("普通客户端：", normal_options)
print("思考客户端：", thinking_options)
```

观察：模型名和地址没有变化，变化的是本次客户端的运行选项。

### Cell 3：复现未知供应商不注入扩展字段

- 依赖：Cell 2；
- 是否联网：否；
- 预期：未知域名返回 `None`，已知演示域名才返回思考开关。

```python
from urllib.parse import urlparse


def demo_thinking_extra_body(
    base_url: str,
    *,
    enable_thinking: bool,
) -> dict | None:
    hostname = (urlparse(base_url).hostname or "").lower()

    if hostname.endswith("known-provider.example"):
        return {"enable_thinking": enable_thinking}

    return None


print(
    demo_thinking_extra_body(
        "https://api.known-provider.example/v1",
        enable_thinking=True,
    )
)
print(
    demo_thinking_extra_body(
        "https://unknown-provider.example/v1",
        enable_thinking=True,
    )
)
```

这个函数只是教学缩减版，不代表 WildAgent 的真实供应商列表。真实规则必须回到 `_thinking_extra_body()` 阅读。

### Cell 4：复现统一结果与业务消费边界

- 依赖：无；
- 是否联网：否；
- 预期：业务函数只认识 `DemoLlmResult`，不解析供应商原始字段。

```python
from dataclasses import dataclass


@dataclass
class DemoLlmResult:
    content: str = ""
    reasoning: str = ""
    token_usage: dict[str, int] | None = None
    finish_reason: str | None = None
    retry_count: int = 0


def consume_chat_result(result: DemoLlmResult) -> dict:
    return {
        "reply": result.content,
        "diagnostics": {
            "token_usage": result.token_usage,
            "finish_reason": result.finish_reason,
            "retry_count": result.retry_count,
        },
    }


normalized_result = DemoLlmResult(
    content="模型调用已经完成。",
    reasoning="离线演示中的推理摘要。",
    token_usage={"input": 12, "output": 8, "total": 20},
    finish_reason="stop",
)

node_output = consume_chat_result(normalized_result)
print(node_output)
```

### Cell 5：主动制造边界错误

- 依赖：Cell 4；
- 是否联网：否；
- 预期：把供应商原始字典直接交给业务层会失败，从而证明归一化层不能省略。

```python
raw_provider_response = {
    "choices": [
        {"message": {"content": "原始响应"}}
    ]
}

try:
    consume_chat_result(raw_provider_response)
except AttributeError as exc:
    print("预期边界错误：", exc)
```

修复方式不是让每个业务函数都兼容字典，而是先由统一调用层把原始响应转换成 `DemoLlmResult`。

### Cell 6：画出自己理解的调用链

- 类型：Markdown Cell；
- 依赖：完成本章源码阅读；
- 预期：不复制本文，用自己的话填写。

```markdown
## 我的 WildAgent 模型调用链

1. 配置入口：
2. 客户端工厂：
3. 协议兼容：
4. 非流式收集：
5. 流式收集：
6. 错误与重试：
7. 最简单的业务调用方：

我现在仍不理解的问题：
- 
```

## 10. 本模块实现与后续模块的边界

08 模块已经学习：

- 模型连接配置；
- 客户端工厂；
- 消息调用；
- 流式分块；
- 响应归一化；
- 超时、重试和错误分类；
- WildAgent 中的真实调用关系。

以下内容不要提前塞进11模块：

- JSON/Pydantic 结构化输出和格式恢复：属于09模块；
- LangGraph State、Reducer 与条件路由：属于10模块；
- 节点标准输入输出：属于11模块；
- Tool Calling：属于12模块。

## 11. 练习题

1. 在纸上或 Notebook Markdown 中说明 `ChatOpenAI`、`ReasoningChatOpenAI` 和 `LlmResult` 的关系。
2. 对照 `chat_node.py`，标出消息创建、模型创建、模型调用和结果消费四个位置。
3. 对照 `base_component_node.py`，解释 `thinking_mode` 不等于 `streaming` 的原因。
4. 找出 `AgentService.reload_chat_models()` 为什么先创建新对象再替换旧对象。
5. 说明一个401错误从 SDK 抛出后，会依次经过哪些层。

## 12. 完成检查

- [ ] 我能从 `config.chat` 一路讲到节点消费 `LlmResult`
- [ ] 我能区分客户端工厂、调用层和业务节点的职责
- [ ] 我能解释普通客户端和流式思考客户端的区别
- [ ] 我知道未知供应商为什么不应自动注入思考参数
- [ ] 我能说明流式和非流式为什么最终返回同一种结果
- [ ] 我没有修改或运行 WildAgent 源码
- [ ] 我已经在自己的 Notebook 中写完模块总结
