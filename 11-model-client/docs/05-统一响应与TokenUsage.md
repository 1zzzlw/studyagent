# 第5章：统一响应与Token Usage

## 本章目标

把字符串、内容块、扩展推理字段和两种 Usage 键名整理为稳定的应用结果，使业务代码不依赖某一家供应商的响应细节。

## 前置知识

- 知道非流式返回 `AIMessage`，流式返回多个 `AIMessageChunk`；
- 已观察当前供应商的 `response_metadata` 和 `usage_metadata`；
- 理解本章只做响应归一化，不做 JSON/Pydantic 结构化输出。

## 1. 为什么不能只写 `response.content`

常见响应差异包括：

```text
content = "普通字符串"
content = [{"type": "text", "text": "内容"}]
reasoning_content 位于 additional_kwargs
finish_reason 位于 response_metadata
Usage 使用 prompt_tokens/completion_tokens
Usage 使用 input_tokens/output_tokens
```

业务节点真正需要的是稳定结果：

```text
content: str
reasoning: str
token_usage: {input, output, total} | None
finish_reason: str | None
```

## 2. Notebook 分单元格练习

建立 `# 第5章：统一响应`。本章先使用假响应离线练习，再处理第3章真实响应。

### Cell 1：定义统一结果

- 依赖：无；
- 是否联网：否；
- 预期：创建一个不依赖供应商 SDK 的数据对象。

```python
from dataclasses import dataclass


@dataclass
class ModelResult:
    content: str = ""
    reasoning: str = ""
    token_usage: dict[str, int] | None = None
    finish_reason: str | None = None

    @property
    def content_chars(self) -> int:
        return len(self.content)

    @property
    def reasoning_chars(self) -> int:
        return len(self.reasoning)
```

### Cell 2：把多种content转换成文本

- 依赖：无；
- 是否联网：否；
- 输入：字符串、列表、字典或空值；
- 预期：统一返回字符串。

```python
def content_as_text(value: object) -> str:
    if isinstance(value, str):
        return value

    if isinstance(value, list):
        parts = [content_as_text(item) for item in value]
        return "\n".join(part for part in parts if part)

    if isinstance(value, dict):
        for key in ("text", "content", "output_text"):
            text = content_as_text(value.get(key))
            if text:
                return text

    return ""


content_cases = [
    "普通字符串",
    [{"type": "text", "text": "第一段"}, {"output_text": "第二段"}],
    {"content": "字典正文"},
    None,
]

for value in content_cases:
    print(repr(value), "=>", repr(content_as_text(value)))
```

### Cell 3：归一化两种Usage键名

- 依赖：无；
- 是否联网：否；
- 输入：供应商风格和LangChain风格Usage；
- 预期：都转换为 `input/output/total`。

```python
def normalize_usage(usage: object) -> dict[str, int] | None:
    if not isinstance(usage, dict) or not usage:
        return None

    input_tokens = usage.get("prompt_tokens", usage.get("input_tokens"))
    output_tokens = usage.get("completion_tokens", usage.get("output_tokens"))
    total_tokens = usage.get("total_tokens")

    if input_tokens is None and output_tokens is None and total_tokens is None:
        return None

    input_value = int(input_tokens or 0)
    output_value = int(output_tokens or 0)
    total_value = int(total_tokens or 0) or input_value + output_value

    return {
        "input": input_value,
        "output": output_value,
        "total": total_value,
    }


usage_cases = [
    {"prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14},
    {"input_tokens": 8, "output_tokens": 3, "total_tokens": 11},
    {"input_tokens": 5, "output_tokens": 2},
    {},
]

for usage in usage_cases:
    print(usage, "=>", normalize_usage(usage))
```

### Cell 4：从消息中提取正文和推理

- 依赖：Cell 2；
- 是否联网：否；
- 预期：正文和推理字段分别保存。

```python
from types import SimpleNamespace


def message_texts(message: object) -> tuple[str, str]:
    content = content_as_text(getattr(message, "content", ""))
    additional = getattr(message, "additional_kwargs", {}) or {}
    metadata = getattr(message, "response_metadata", {}) or {}

    reasoning = ""
    if isinstance(additional, dict):
        reasoning = content_as_text(additional.get("reasoning_content"))
    if not reasoning and isinstance(metadata, dict):
        reasoning = content_as_text(metadata.get("reasoning_content"))

    return content, reasoning


fake_message = SimpleNamespace(
    content=[{"type": "text", "text": "最终回答"}],
    additional_kwargs={"reasoning_content": "供应商扩展推理"},
    response_metadata={"finish_reason": "stop"},
)

print(message_texts(fake_message))
```

### Cell 5：收集为统一结果

- 依赖：Cell 1～4；
- 是否联网：否；
- 预期：得到完整 `ModelResult`。

```python
def collect_message(message: object) -> ModelResult:
    content, reasoning = message_texts(message)
    metadata = getattr(message, "response_metadata", {}) or {}
    usage_metadata = getattr(message, "usage_metadata", None) or {}

    finish_reason = None
    usage = None
    if isinstance(metadata, dict):
        finish_reason = metadata.get("finish_reason") or metadata.get("stop_reason")
        usage = normalize_usage(
            metadata.get("token_usage") or metadata.get("usage")
        )

    if usage is None:
        usage = normalize_usage(usage_metadata)

    return ModelResult(
        content=content,
        reasoning=reasoning,
        token_usage=usage,
        finish_reason=finish_reason,
    )


fake_message.usage_metadata = {
    "input_tokens": 12,
    "output_tokens": 5,
    "total_tokens": 17,
}
fake_result = collect_message(fake_message)

print(fake_result)
print("正文字符：", fake_result.content_chars)
print("推理字符：", fake_result.reasoning_chars)
```

### Cell 6：处理第3章真实响应

- 依赖：第3章 Cell 2，以及本章 Cell 5；
- 是否联网：否，不重新请求；
- 预期：真实 `AIMessage` 被转换成相同结构。

```python
real_result = collect_message(response)

print("正文：", real_result.content)
print("推理字符：", real_result.reasoning_chars)
print("Token Usage：", real_result.token_usage)
print("结束原因：", real_result.finish_reason)
```

推理和Usage为空不一定是代码错误，也可能是当前供应商没有返回对应字段。

### Cell 7：合并多次调用的Usage

- 依赖：Cell 3；
- 是否联网：否；
- 预期：模拟“首次生成+第二次修复”的总消耗。

```python
def merge_token_usage(*items: dict[str, int] | None):
    present = [item for item in items if item]
    if not present:
        return None

    merged = {"input": 0, "output": 0, "total": 0}
    for item in present:
        for key in merged:
            merged[key] += int(item.get(key, 0) or 0)
    return merged


first_usage = {"input": 100, "output": 40, "total": 140}
repair_usage = {"input": 50, "output": 20, "total": 70}

print(merge_token_usage(first_usage, repair_usage))
```

## 3. 主动错误实验

把 `usage_cases` 增加 `{"total_tokens": "not-a-number"}`，观察转换失败位置。不要直接吞掉异常；先决定这是供应商响应损坏，还是应该在兼容层记录警告并返回 `None`。

## 4. WildAgent 对照提示

WildAgent 的 `content_as_text()`、`message_texts()`、`collect_response()` 和 `LlmResult` 完成同类工作，让业务节点不必重复处理字符串、内容块、推理字段和Usage键名。

## 5. 练习题

1. 让 `message_texts()` 同时支持字典消息。
2. 为 `ModelResult` 增加 `has_usage` 属性。
3. 解释为什么推理内容不能和最终正文直接拼接后交给用户。

## 6. 完成检查

- [ ] 我能把多种content转成字符串
- [ ] 我能统一两种Usage键名
- [ ] 我能分别保存正文和推理
- [ ] 我能把真实响应转换为稳定结果
- [ ] 我知道Usage为空不一定是异常

