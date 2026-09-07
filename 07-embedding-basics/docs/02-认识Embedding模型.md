# 第 2 章：认识 Embedding 模型

## 本章目标

理解文本如何变成向量，以及为什么文档和问题必须使用同一个 Embedding 模型与兼容配置。

## 1. 向量不是摘要

假设模型返回：

```python
[0.021, -0.104, 0.337, ...]
```

这些数字不适合逐个解释。系统关心的是两个向量之间的距离：语义越接近，通常距离越小。

```text
“玻璃幕墙如何连接墙体”
“幕墙窗需要通过 parentWall 挂接”
```

即使两句话不完全相同，语义向量仍可能靠得很近。这正是 Embedding 相比纯关键词查找的价值。

## 2. 文档向量与问题向量

建库时：

```python
document_vectors = embeddings.embed_documents(chunk_texts)
```

查询时：

```python
query_vector = embeddings.embed_query(question)
```

二者必须使用同一个模型和维度。若建库使用模型 A、查询使用模型 B：

- 维度不同，数据库通常会直接报错；
- 维度碰巧相同，空间含义仍不同，结果没有可比性。

因此本教程把模型名、接口地址和切块参数共同计算成 `index_signature`。配置发生变化时，程序会要求显式执行：

```powershell
uv run python 07-embedding-basics\run.py sync --rebuild
```

这只删除并重建本模块的 `studyagent_wild_knowledge_v1` 集合。

## 3. 对照教学代码

打开 `embedding_lab/embeddings.py`，主流程只有三步：

```python
response = client.embeddings.create(
    model=self.model,
    input=batch,
    encoding_format="float",
)

ordered = sorted(response.data, key=lambda item: item.index)
vectors = [list(item.embedding) for item in ordered]
```

这里值得注意：

- `input` 是字符串列表，不是聊天消息；
- `encoding_format="float"` 要求返回浮点数组；
- 按 `index` 排序，确保向量和输入文本一一对应；
- 单批最多 10 条，保持与 WildAgent 当前兼容策略一致。

## 4. 同一个 SDK 为什么可以创建两种 Client

先分清两个对象：

```python
from openai import OpenAI

chat_client = OpenAI(
    api_key="连接服务所需的凭证",
    base_url="OpenAI-compatible 服务地址",
)
```

`OpenAI` 是 SDK 中的客户端类型。每执行一次 `OpenAI(...)`，就创建一个保存特定地址、凭证、超时和重试配置的客户端对象；此时还没有调用任何模型。

真正选择能力的是后面访问的资源：

```text
chat_client.chat.completions.create(...) → 聊天地址/chat/completions → 对话模型
embedding_client.embeddings.create(...)  → 向量地址/embeddings       → 向量模型
```

当聊天与 Embedding 在同一供应商、共用同一个 Base URL 和 Key 时，一个 Client 确实可以调用两类端点。但本项目现在使用不同供应商，必须创建两个 Client，不能再让向量调用借用 `LLM_BASE_URL`。

### 4.1 创建两个相互独立的 SDK Client

下面这段可以作为 Notebook 的第一个对照 Cell。依赖：模块 README 的公共初始化 Cell。

```python
import os

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv(PROJECT_ROOT / ".env", override=True)

chat_client = OpenAI(
    api_key=os.environ["LLM_API_KEY"],
    base_url=os.environ["LLM_BASE_URL"],
    timeout=60.0,
    max_retries=1,
)

embedding_client = OpenAI(
    api_key=os.environ["EMBEDDING_API_KEY"],
    base_url=os.environ["EMBEDDING_BASE_URL"],
    timeout=60.0,
    max_retries=1,
)

print("聊天 Client 类型：", type(chat_client).__name__)
print("聊天 Base URL：", chat_client.base_url)
print("向量 Client 类型：", type(embedding_client).__name__)
print("向量 Base URL：", embedding_client.base_url)
```

两个对象的类型都是 `OpenAI`，但内部保存的地址和密钥不同。这里仍然没有产生模型请求，也不要打印任何 API Key。

### 4.2 使用它调用对话模型

```python
chat_response = chat_client.chat.completions.create(
    model=os.environ["LLM_MODEL"],
    messages=[
        {
            "role": "system",
            "content": "你是一个回答简洁的 Python 助手。",
        },
        {
            "role": "user",
            "content": "请用一句话解释 Chroma 是什么。",
        },
    ],
    temperature=0,
)

answer = chat_response.choices[0].message.content

print("对话模型：", chat_response.model)
print("自然语言回答：", answer)
```

这一调用的特征是：

- 模型来自 `LLM_MODEL`；
- 输入是带 `role` 的 `messages`；
- 输出从 `choices[0].message.content` 读取；
- 最终结果是给人阅读的自然语言。

### 4.3 使用独立的 Embedding Client 调用腾讯向量模型

```python
embedding_response = embedding_client.embeddings.create(
    model=os.environ["EMBEDDING_MODEL"],
    input=[
        "Chroma 是一个向量数据库",
        "Python 是一种编程语言",
    ],
    encoding_format="float",
)

ordered_items = sorted(
    embedding_response.data,
    key=lambda item: item.index,
)
vectors = [list(item.embedding) for item in ordered_items]

print("向量模型：", embedding_response.model)
print("返回向量数量：", len(vectors))
print("每个向量的维度：", len(vectors[0]))
print("第一个向量前 5 维：", vectors[0][:5])
```

这一调用的特征是：

- 模型来自 `EMBEDDING_MODEL`；
- 输入是字符串或字符串列表，不使用 `system/user/assistant` 角色；
- 输出从 `data[index].embedding` 读取；
- 最终结果是供程序计算相似度的浮点数列表，不是自然语言回答。

### 4.4 两段代码并排对比

| 对比项 | 对话模型 | Embedding 模型 |
|---|---|---|
| SDK Client | `OpenAI(...)` | `OpenAI(...)` |
| Client 对象 | `chat_client` | `embedding_client` |
| Base URL 变量 | `LLM_BASE_URL` | `EMBEDDING_BASE_URL` |
| API Key 变量 | `LLM_API_KEY` | `EMBEDDING_API_KEY` |
| 调用方法 | `chat_client.chat.completions.create()` | `embedding_client.embeddings.create()` |
| HTTP 端点 | `/chat/completions` | `/embeddings` |
| 模型变量 | `LLM_MODEL` | `EMBEDDING_MODEL` |
| 主要输入 | `messages=[{role, content}]` | `input="文本"` 或 `input=[...]` |
| 主要输出 | `choices[0].message.content` | `data[i].embedding` |
| 输出类型 | 自然语言字符串 | `list[float]` |
| 典型用途 | 回答、推理、生成内容 | 相似度、聚类、检索、排序 |
| 是否使用 `temperature` | 通常可以 | 不使用 |
| 是否需要向量数据库 | 不一定 | 模型本身不需要；RAG 通常会保存向量 |

最容易记住的方式是：

```text
OpenAI = 同一种电话机
chat_client = 接入聊天供应商线路的电话机
embedding_client = 接入腾讯向量线路的电话机
chat.completions / embeddings = 两种不同业务端点
model = 当前端点实际使用的模型或服务 ID
```

### 4.5 常见错误对照

下面两段用于辨认错误，不要在正常练习中执行；只有你准备观察供应商错误响应时再单独运行。

```python
# 错误：把向量模型用于对话端点
chat_client.chat.completions.create(
    model=os.environ["EMBEDDING_MODEL"],
    messages=[{"role": "user", "content": "你好"}],
)

# 错误：把对话模型用于向量端点
embedding_client.embeddings.create(
    model=os.environ["LLM_MODEL"],
    input="你好",
)
```

这两段通常会收到“模型不支持当前操作”或“模型不存在”等服务端错误。模型名称、端点和输入格式必须互相匹配。

还有一种情况是对话调用成功、Embedding 调用失败。这并不能说明 `OpenAI(...)` 创建错了，更常见的原因是：

- 当前供应商只实现了 `/chat/completions`，没有实现 `/embeddings`；
- `EMBEDDING_MODEL` 名称填错；
- 向量接口的批量大小、输入格式或权限不同；
- 对话和向量服务实际使用不同的 Base URL 或 API Key，却错误地复用了 `LLM_*` 配置。

## 5. 最小 Notebook

`01.basic.ipynb` 用三条短文本演示：

1. 文本向量化；
2. 写入 Chroma；
3. 问题向量化；
4. 相似度查询。

运行时重点观察向量维度，而不是打印完整向量。完整向量通常很长，打印它不会帮助理解。

下面的详细练习只发送三条文档和一条问题，适合写进 `01.basic.ipynb` 观察真实接口，不用于全量建库。

### Cell 1：加载环境变量

依赖：公共初始化 Cell。必须先加载环境变量，再导入 `Settings`。

```python
from dotenv import load_dotenv

env_path = PROJECT_ROOT / ".env"
loaded = load_dotenv(env_path, override=True)

print(".env 路径：", env_path)
print("是否加载：", loaded)
```

### Cell 2：创建 Embedding 客户端

依赖：Cell 1。

```python
from embedding_lab.config import Settings
from embedding_lab.embeddings import OpenAICompatibleEmbeddings

settings = Settings()
settings.require_embedding_config()

embeddings = OpenAICompatibleEmbeddings(
    api_key=settings.embedding_api_key,
    base_url=settings.embedding_base_url,
    model=settings.embedding_model,
    batch_size=2,
    timeout=60.0,
)

print("模型：", settings.embedding_model)
print("接口地址：", settings.embedding_base_url)
```

不要打印 `settings.embedding_api_key`。

### Cell 3：分别生成文档向量和问题向量

依赖：Cell 2。这个 Cell 会真实调用 Embedding 接口。

```python
documents = [
    "玻璃幕墙需要挂接到父墙体",
    "楼梯连接上下两个楼层",
    "屋顶覆盖建筑最上层空间",
]
question = "幕墙应该连接到什么构件？"

document_vectors = embeddings.embed_documents(documents)
query_vector = embeddings.embed_query(question)

dimension = len(query_vector)
assert len(document_vectors) == len(documents)
assert dimension > 0
assert all(len(vector) == dimension for vector in document_vectors)

print("文档向量数量：", len(document_vectors))
print("问题向量维度：", dimension)
print("问题向量前 5 维：", query_vector[:5])
```

`batch_size=2` 时，三条文档会分成两个请求批次；问题向量再单独产生一次请求。

### Cell 4：手动计算 cosine similarity

依赖：Cell 3。

```python
import numpy as np


def cosine_similarity(left: list[float], right: list[float]) -> float:
    left_array = np.asarray(left, dtype=float)
    right_array = np.asarray(right, dtype=float)
    denominator = np.linalg.norm(left_array) * np.linalg.norm(right_array)
    if denominator == 0:
        raise ValueError("零向量不能计算 cosine similarity")
    return float(np.dot(left_array, right_array) / denominator)


scores = [
    cosine_similarity(query_vector, vector)
    for vector in document_vectors
]
ranking = sorted(
    zip(documents, scores),
    key=lambda item: item[1],
    reverse=True,
)

for text, score in ranking:
    print(f"similarity={score:.4f} | {text}")
```

最高相似度预期是幕墙相关文本，但真实排序仍由当前模型决定。

### Cell 5：配置错误实验

依赖：Cell 2。这里只验证配置门禁，不发送错误请求。

```python
broken_settings = Settings(
    embedding_model="",
    embedding_base_url="",
    embedding_api_key="",
)

try:
    broken_settings.require_embedding_config()
except RuntimeError as exc:
    print("预期错误：", exc)
else:
    raise AssertionError("缺少模型、地址和密钥时应该被配置门禁阻止")
```

### Cell 6：用 Markdown 写总结

记录当前模型名、向量维度、最相似文本、请求次数，以及文档向量与问题向量为什么必须同源。

## 6. `OpenAICompatibleEmbeddings` 为什么能作为 `Embeddings`

先看 [vector_store.py](../embedding_lab/vector_store.py) 中的定义：

```python
from typing import Protocol


class Embeddings(Protocol):
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        ...

    def embed_query(self, text: str) -> list[float]:
        ...
```

这里的 `Embeddings` 不是具体对象，也不会负责发送请求。它是一份接口协议，表达 `ChromaVectorStore` 对传入对象的最低要求：

```text
必须有 embed_documents(texts)
必须有 embed_query(text)
```

[embeddings.py](../embedding_lab/embeddings.py) 中的 `OpenAICompatibleEmbeddings` 正好提供了这两个方法：

```python
class OpenAICompatibleEmbeddings:
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        ...

    def embed_query(self, text: str) -> list[float]:
        ...
```

它虽然没有写：

```python
class OpenAICompatibleEmbeddings(Embeddings):
    ...
```

但方法结构已经符合 `Embeddings Protocol`。这叫做结构化类型，也可以理解为 Python 鸭子类型在静态类型检查中的正式表达：

```text
不检查“你继承了谁”
只检查“你能不能提供我需要的方法”
```

### 6.1 完整调用链

CLI 中首先调用：

```python
embeddings = service.create_embeddings()
```

`create_embeddings()` 实际返回：

```python
OpenAICompatibleEmbeddings(...)
```

所以变量的真实运行时类型是：

```text
OpenAICompatibleEmbeddings
```

随后它被传入：

```python
stats = service.store.sync(
    chunks,
    embeddings,
)
```

而 `sync()` 的参数注解是：

```python
def sync(
    self,
    chunks: list[Chunk],
    embeddings: Embeddings,
) -> SyncStats:
    ...
```

`embeddings: Embeddings` 只是类型注解，不会创建新对象，也不会把原对象转换成 `Embeddings`。因此执行：

```python
vectors = embeddings.embed_documents(texts)
```

最终调用的仍然是：

```text
OpenAICompatibleEmbeddings.embed_documents()
```

完整过程如下：

```text
EmbeddingLabService.create_embeddings()
  → 创建 OpenAICompatibleEmbeddings 对象
  → 把同一个对象传给 ChromaVectorStore.sync()
  → sync() 按 Embeddings 协议使用它
  → Python 根据对象真实类型执行 OpenAICompatibleEmbeddings.embed_documents()
```

### 6.2 它不是继承，也不严格叫重写

| 概念 | 当前代码是否属于 | 原因 |
|---|---|---|
| 继承 | 否 | 类定义没有写 `(Embeddings)` |
| 方法重写 | 严格来说不是 | 没有父类方法被覆盖 |
| 实现协议 | 是 | 方法名称和签名满足 Protocol |
| 动态调用 | 是 | 运行时根据真实对象找到具体方法 |

如果用 Java 思维对比：

```java
class OpenAICompatibleEmbeddings implements Embeddings {
    // Java 通常要求显式 implements
}
```

Python `Protocol` 默认允许隐式满足：

```python
class OpenAICompatibleEmbeddings:
    # 不写继承，只要方法结构兼容即可
    ...
```

### 6.3 为什么要依赖 Protocol，而不是具体类

如果 `ChromaVectorStore` 直接要求：

```python
embeddings: OpenAICompatibleEmbeddings
```

它就和 OpenAI-compatible 实现绑定了。使用 Protocol 后，它可以接收：

```text
OpenAICompatibleEmbeddings
FakeEmbeddings
HashEmbeddings
以后新增的其他供应商实现
```

只要这些对象都提供相同的两个方法，向量库就不需要知道请求是怎样发送的。这就是面向接口编程和依赖倒置在 Python 中的一种轻量实现。

## 7. Notebook 分单元格练习：验证 Protocol 与动态调用

下面继续写在 `01.basic.ipynb` 的第 2 章区域。全部实验离线运行，不会请求向量接口。

### Cell 7：观察真实类型和参数注解

依赖：模块 README 的公共初始化 Cell。

```python
from typing import get_type_hints

from embedding_lab.embeddings import OpenAICompatibleEmbeddings
from embedding_lab.vector_store import ChromaVectorStore, Embeddings

adapter = OpenAICompatibleEmbeddings(
    api_key="not-used",
    base_url="https://example.com/v1",
    model="example-embedding-model",
)

sync_hints = get_type_hints(ChromaVectorStore.sync)

print("对象真实类型：", type(adapter).__name__)
print("sync 参数注解：", sync_hints["embeddings"])
print("是否显式继承 Embeddings：", Embeddings in type(adapter).__bases__)
```

预期观察：

```text
对象真实类型：OpenAICompatibleEmbeddings
sync 参数注解：Embeddings
是否显式继承 Embeddings：False
```

这三个结果可以同时成立：真实对象是具体类，函数只要求协议，而且具体类没有显式继承协议。

### Cell 8：不用继承也能满足协议

依赖：Cell 7。

```python
class RecordingEmbeddings:
    def __init__(self):
        self.calls: list[tuple[str, object]] = []

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(("embed_documents", texts))
        return [[1.0, 0.0] for _ in texts]

    def embed_query(self, text: str) -> list[float]:
        self.calls.append(("embed_query", text))
        return [1.0, 0.0]


def use_embeddings(embeddings: Embeddings) -> None:
    document_vectors = embeddings.embed_documents(["文档 A", "文档 B"])
    query_vector = embeddings.embed_query("问题")

    print("文档向量：", document_vectors)
    print("问题向量：", query_vector)


recording = RecordingEmbeddings()
use_embeddings(recording)

print("实际调用记录：", recording.calls)
print("是否显式继承 Embeddings：", Embeddings in RecordingEmbeddings.__bases__)
```

`RecordingEmbeddings` 没有继承 `Embeddings`，但 `use_embeddings()` 仍可以正常调用它，因为它提供了协议要求的方法。

### Cell 9：证明实际执行的是具体类方法

依赖：Cell 7。

```python
bound_method = adapter.embed_documents

print("绑定对象是否为 adapter：", bound_method.__self__ is adapter)
print("实际方法：", bound_method.__func__.__qualname__)
```

预期结果中的实际方法应该是：

```text
OpenAICompatibleEmbeddings.embed_documents
```

这里不要真正调用 `bound_method(...)`，因为那会发送真实 Embedding 请求。我们只观察 Python 已经把方法绑定到了哪个对象。

### Cell 10：主动传入缺少方法的对象

依赖：Cell 8。

```python
class IncompleteEmbeddings:
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0] for _ in texts]


incomplete = IncompleteEmbeddings()

try:
    use_embeddings(incomplete)
except AttributeError as exc:
    print("预期错误：", exc)
else:
    raise AssertionError("缺少 embed_query() 时应该调用失败")
```

Python 运行时不会因为参数写着 `Embeddings` 就提前拦截对象。代码执行到不存在的 `embed_query()` 时才会出现 `AttributeError`。Pyright、mypy 等静态类型检查器则可以在运行前发现它不满足协议。

### Cell 11：用 Markdown 写总结

用自己的话回答：

1. `embeddings` 变量的真实对象是什么？
2. `embeddings: Embeddings` 会不会改变对象类型？
3. 为什么没有继承也能传入 `sync()`？
4. 最终执行的是哪个类的 `embed_documents()`？
5. Protocol 给测试替身和供应商切换带来了什么好处？

## 8. 常见误区

- Embedding 模型不是聊天模型，不能拿它生成自然语言答案。
- 向量库不是大模型，它只存储并比较数据。
- “写入数据库成功”不等于“检索质量良好”。检索质量还受文档、切块、问题表达和 Top-K 影响。
- Hash 向量可以做离线管道测试，但不能代表真实语义检索质量。

## 9. 完成检查

- [ ] 我能分别调用 `embed_documents()` 和 `embed_query()`
- [ ] 我能验证返回数量和向量维度
- [ ] 我能自己计算 cosine similarity 并完成排序
- [ ] 我知道为什么要在导入 `Settings` 前加载 `.env`
- [ ] 我知道离线假向量不能评价真实召回质量
- [ ] 我能解释 `OpenAI(...)` 为什么不是一次模型调用
- [ ] 我能对比对话请求与 Embedding 请求的输入和返回结构
- [ ] 我能区分继承、重写、实现 Protocol 和动态调用
- [ ] 我能解释为什么 `OpenAICompatibleEmbeddings` 没有继承也能传给 `sync()`
- [ ] 我能证明最终执行的是具体对象自己的 `embed_documents()`

参考：[OpenAI Create embeddings](https://developers.openai.com/api/reference/resources/embeddings/methods/create)、[OpenAI Chat Completions](https://developers.openai.com/api/reference/resources/chat)
