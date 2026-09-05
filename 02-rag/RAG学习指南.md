# LangChain RAG 完整入门指南

这份文档面向刚开始学习 LangChain 的同学。目标不是先搭建一个复杂系统，而是让你能亲手跑通、看懂并观测一条完整的 RAG 链路。

完成本教程后，你将能回答下面几个问题：

1. RAG 为什么需要切块和向量化？
2. 用户提问后，系统到底检索了哪些内容？
3. 检索结果如何交给大模型？
4. 如何在 LangSmith 中分别观察检索和生成？
5. 回答错误时，怎样判断是“没检索到”还是“模型没用好资料”？

---

## 1. 先认识 RAG

RAG 是 Retrieval-Augmented Generation 的缩写，通常译为“检索增强生成”。

普通大模型问答只有一步：

```text
用户问题 → 大模型 → 回答
```

RAG 在大模型回答之前增加了检索：

```text
知识库文档
   ↓
切成多个小块（chunk）
   ↓
转换成向量（embedding）
   ↓
存入向量库

用户问题 → 问题向量化 → 检索相关文本块 → 连同问题一起交给大模型 → 回答
```

可以把它理解成“开卷考试”：

- 大模型是考生；
- 知识库是教材；
- Retriever 是负责翻教材的人；
- Prompt 把找到的教材内容放到考生面前；
- LangSmith 是考试过程的录像。

RAG 不会训练或修改大模型。它只是每次回答前，动态地把相关资料放进上下文。

---

## 2. 本教程选择的实现方式

LangChain 常见的 RAG 有两种：

| 方式 | 检索由谁决定 | 优点 | 适合场景 |
|---|---|---|---|
| 两步式 RAG | 程序固定先检索 | 简单、稳定、容易调试 | 学习、知识库问答、客服 FAQ |
| Agentic RAG | 模型决定是否调用检索工具 | 灵活，可组合多个工具 | 已掌握基础 RAG 后的复杂 Agent |

本教程先实现两步式 RAG。原因是它把检索和回答明确分开，更容易判断问题发生在哪一步。最后一节再将 Retriever 包装为 Agent 工具。

为了减少初学阶段的依赖，我们使用：

- Markdown 文件作为知识库；
- `RecursiveCharacterTextSplitter` 切块；
- 阿里云百炼 `text-embedding-v4` 生成向量；
- LangChain `InMemoryVectorStore` 保存向量；
- `qwen3.5-flash` 生成答案；
- LangSmith 观察完整过程。

`InMemoryVectorStore` 关闭程序后数据会消失，因此适合学习，不适合生产环境。

---

## 3. 安装依赖

在项目根目录 `E:\AgentProject\studyAgent` 执行：

```powershell
uv add langchain-text-splitters numpy
```

当前项目已经包含 `langchain`、`langchain-openai`、`langsmith` 和 `python-dotenv`，不需要重复安装。`numpy` 用于让内存向量库计算余弦相似度；缺少它时，写入向量可能成功，但执行 `similarity_search_with_score()` 会报错。

然后在 `.env` 中确认或补充：

```dotenv
# LangSmith 观测
LANGSMITH_TRACING=true
LANGSMITH_ENDPOINT=https://api.smith.langchain.com
LANGSMITH_API_KEY=你的_LangSmith_Key
LANGSMITH_PROJECT=study-rag

# 阿里云百炼 OpenAI 兼容接口
LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
LLM_API_KEY=你的百炼_API_Key

# qwen3.5-ocr 不支持 Function Calling；这里使用通用模型
LLM_MODEL=qwen3.5-flash
EMBEDDING_MODEL=text-embedding-v4
```

注意：Embedding 模型和聊天模型不是同一种模型。

- `qwen3.5-flash`：阅读问题和资料，生成自然语言答案；
- `text-embedding-v4`：把文字转换成数字向量，用来计算语义相似度。

---

## 4. 准备一份最小知识库

创建目录：

```text
02-rag/
├── RAG学习指南.md
└── knowledge/
    └── company-handbook.md
```

在 `company-handbook.md` 中写入下面的测试内容：

```markdown
# 星河公司的员工手册

## 年假制度

正式员工每年享有 10 天带薪年假。入职不满一年的员工，年假按照实际在职月份折算。年假申请需要至少提前 3 个工作日提交。

## 报销制度

单笔金额低于 500 元的普通办公费用由直属主管审批。单笔金额达到或超过 500 元时，还需要财务负责人审批。报销申请必须在费用发生后的 30 天内提交。

## 远程办公

员工每周最多可以申请 2 天远程办公。远程办公需要提前一天在内部系统提交申请，并获得直属主管批准。
```

这份知识库故意很小，这样你能直接看懂每个切块和每次召回是否合理。

---

## 5. 第一个完整的两步式 RAG

建议新建 Notebook：

```text
02-rag/01.basic-rag.ipynb
```

### 5.1 加载环境变量

第一个单元格：

```python
from dotenv import find_dotenv, load_dotenv

env_path = find_dotenv(".env", usecwd=True)
if not env_path:
    raise FileNotFoundError("从当前目录向上没有找到 .env")

# 必须在导入 LangChain 和 LangSmith 前加载
load_dotenv(env_path, override=True)

import os

required_env = [
    "LLM_MODEL",
    "LLM_BASE_URL",
    "LLM_API_KEY",
    "EMBEDDING_MODEL",
    "LANGSMITH_API_KEY",
]

missing = [name for name in required_env if not os.getenv(name)]
if missing:
    raise RuntimeError(f"缺少环境变量：{missing}")

print("已加载：", env_path)
print("聊天模型：", os.getenv("LLM_MODEL"))
print("向量模型：", os.getenv("EMBEDDING_MODEL"))
print("LangSmith 项目：", os.getenv("LANGSMITH_PROJECT"))
```

不要打印 API Key。

### 5.2 加载 Markdown 文档

第二个单元格：

```python
from pathlib import Path
from langchain_core.documents import Document

knowledge_dir = Path.cwd() / "knowledge"
if not knowledge_dir.exists():
    # 当 Notebook 内核工作目录是项目根目录时使用这个路径
    knowledge_dir = Path.cwd() / "02-rag" / "knowledge"

markdown_files = sorted(knowledge_dir.glob("*.md"))
if not markdown_files:
    raise FileNotFoundError(f"知识库目录中没有 Markdown 文件：{knowledge_dir}")

documents = []

for file_path in markdown_files:
    content = file_path.read_text(encoding="utf-8")
    documents.append(
        Document(
            page_content=content,
            metadata={"source": file_path.name},
        )
    )

print(f"加载了 {len(documents)} 份文档")
for document in documents:
    print(document.metadata, len(document.page_content), "字符")
```

`Document` 有两个最重要的字段：

- `page_content`：真正参与切块、向量化和回答的正文；
- `metadata`：来源、页码、标题等辅助信息，用于展示引用和过滤结果。

### 5.3 文本切块

第三个单元格：

```python
from langchain_text_splitters import RecursiveCharacterTextSplitter

text_splitter = RecursiveCharacterTextSplitter(
    chunk_size=300,
    chunk_overlap=50,
    length_function=len,
    separators=["\n## ", "\n### ", "\n\n", "\n", "。", "！", "？", " ", ""],
)

chunks = text_splitter.split_documents(documents)

for index, chunk in enumerate(chunks):
    chunk.metadata["chunk_id"] = index
    print(f"\n--- chunk {index} / {chunk.metadata['source']} ---")
    print(chunk.page_content)

print(f"\n共生成 {len(chunks)} 个文本块")
```

参数含义：

- `chunk_size=300`：每块尽量不超过 300 个字符；
- `chunk_overlap=50`：相邻文本块重复约 50 个字符，减少关键信息刚好被切断的问题；
- `separators`：优先按 Markdown 标题和自然段切分，再考虑句子和字符。

切块不是越小越好：

- 太小：一个规则可能被拆散，语义不完整；
- 太大：召回内容不够精确，还会浪费模型上下文；
- 重叠太大：知识重复，增加向量化和输入成本。

学习阶段不要急着寻找“完美参数”。先打印所有 chunk，肉眼确认每块是否包含完整意思。

### 5.4 创建 Embedding 模型

第四个单元格：

```python
from langchain_openai import OpenAIEmbeddings

embeddings = OpenAIEmbeddings(
    model=os.getenv("EMBEDDING_MODEL"),
    base_url=os.getenv("LLM_BASE_URL"),
    api_key=os.getenv("LLM_API_KEY"),
    # 百炼兼容接口只接受字符串或字符串列表。
    # 关闭后 LangChain 会发送原始文本，而不是 OpenAI token ID 数组。
    check_embedding_ctx_length=False,
    # 明确要求返回浮点数组，避免第三方兼容接口的 base64 差异。
    encoding_format="float",
)

test_vector = embeddings.embed_query("员工有多少天年假？")

print("向量维度：", len(test_vector))
print("前 5 个数字：", test_vector[:5])
```

向量看起来类似：

```text
[0.012, -0.008, 0.031, ...]
```

每个数字本身没有适合人类阅读的含义。我们关心的是：语义越相近的文字，其向量通常也越接近。

如果百炼返回 `contents is neither str nor list of str`，说明请求中发送的是 token ID，而不是原始字符串。确认初始化参数中已经包含：

```python
check_embedding_ctx_length=False
```

不需要为此自己实现 `Embeddings`。

### 5.5 建立内存向量库

第五个单元格：

```python
from langchain_core.vectorstores import InMemoryVectorStore

vector_store = InMemoryVectorStore.from_documents(
    documents=chunks,
    embedding=embeddings,
)

print(f"已将 {len(chunks)} 个文本块写入内存向量库")
```

这里发生了两件事：

1. 每个 chunk 被 Embedding 模型转换成向量；
2. 文本、向量和 metadata 一起保存在向量库中。

### 5.6 先单独测试检索

第六个单元格：

```python
question = "普通办公费用 800 元需要谁审批？"

results = vector_store.similarity_search_with_score(question, k=3)

for rank, (document, score) in enumerate(results, start=1):
    print(f"\n--- 第 {rank} 名，score={score:.4f} ---")
    print("来源：", document.metadata)
    print(document.page_content)
```

现在先不要调用聊天模型。检查前几名是否包含“500 元”和“财务负责人审批”。

如果正确资料没有进入 Top-K，即使后面的模型再聪明，也无法依据正确资料回答。这属于检索问题，而不是生成问题。

不同向量库对 score 的定义可能不同，不要脱离当前实现，武断地认为“越大一定越好”或“低于某个固定值一定无关”。初学阶段优先观察正确文本是否稳定进入前几名。

### 5.7 将检索封装为可观测函数

第七个单元格：

```python
from langsmith import traceable


@traceable(run_type="retriever", name="retrieve_company_handbook")
def retrieve(question: str, k: int = 3):
    return vector_store.similarity_search(question, k=k)
```

与之前的 `@traceable(run_type="tool")` 一样，只有 `retrieve()` 真正运行时，LangSmith 才会出现这条记录。

### 5.8 创建聊天模型和 RAG Prompt

第八个单元格：

```python
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate

llm = ChatOpenAI(
    model=os.getenv("LLM_MODEL"),
    base_url=os.getenv("LLM_BASE_URL"),
    api_key=os.getenv("LLM_API_KEY"),
    temperature=0,
)

rag_prompt = ChatPromptTemplate.from_messages([
    (
        "system",
        """你是一个严格依据公司知识库回答问题的助手。

规则：
1. 只能依据下面提供的知识库上下文回答。
2. 如果上下文不足以回答，明确说“根据当前知识库无法确定”。
3. 不要用自己的常识补充公司制度。
4. 回答后列出使用到的来源文件。

知识库上下文：
{context}""",
    ),
    ("human", "{question}"),
])
```

Prompt 的核心任务是划清证据边界。它不能保证模型永远不犯错，但能显著减少模型脱离资料自由发挥。

### 5.9 完成 RAG 问答函数

第九个单元格：

```python
from langchain_core.tracers.langchain import wait_for_all_tracers


def format_context(retrieved_documents) -> str:
    sections = []

    for index, document in enumerate(retrieved_documents, start=1):
        source = document.metadata.get("source", "unknown")
        chunk_id = document.metadata.get("chunk_id", "unknown")
        sections.append(
            f"[资料 {index} | source={source} | chunk={chunk_id}]\n"
            f"{document.page_content}"
        )

    return "\n\n".join(sections)


@traceable(name="two_step_rag")
def ask_rag(question: str) -> dict:
    retrieved_documents = retrieve(question, k=3)
    context = format_context(retrieved_documents)
    messages = rag_prompt.invoke({
        "question": question,
        "context": context,
    })
    response = llm.invoke(messages)

    return {
        "answer": response.content,
        "sources": [document.metadata for document in retrieved_documents],
        "context": context,
    }


result = ask_rag("普通办公费用 800 元需要谁审批？")

print("回答：")
print(result["answer"])
print("\n检索来源：")
for source in result["sources"]:
    print(source)

# Notebook 退出或马上打开 LangSmith 查看时，等待后台 trace 上传完成
wait_for_all_tracers()
```

合理答案应该指出：800 元达到或超过 500 元，因此需要直属主管和财务负责人审批。

---

## 6. 在 LangSmith 中应该看到什么

进入 `study-rag` 项目后，一次请求应大致形成下面的调用树：

```text
two_step_rag
├── retrieve_company_handbook
└── ChatOpenAI
```

重点检查：

### 6.1 `two_step_rag`

- Input 是否是用户真实问题；
- Output 是否同时包含答案和来源；
- 整次调用耗时是否合理。

### 6.2 `retrieve_company_handbook`

- 返回了几个 Document；
- Top-1 是否是最相关文本；
- metadata 中能否看出来源和 chunk；
- 是否召回了很多重复或无关内容。

### 6.3 `ChatOpenAI`

- Prompt 中是否真的包含检索上下文；
- 模型是否使用了资料中的具体规则；
- 当资料不足时，模型是否按要求拒绝猜测；
- 输入和输出 Token 是否过多。

LangSmith 记录调用，但不会自动证明 RAG 的答案正确。最终仍需要测试用例和人工检查。

---

## 7. 用三个问题验证 RAG

依次运行：

```python
questions = [
    "员工每年有多少天带薪年假？",
    "800 元办公费需要谁审批？",
    "公司是否提供免费午餐？",
]

for question in questions:
    result = ask_rag(question)
    print("\n问题：", question)
    print("回答：", result["answer"])

wait_for_all_tracers()
```

预期行为：

| 问题 | 应检索到 | 回答要求 |
|---|---|---|
| 年假天数 | 年假制度 | 10 天 |
| 800 元报销 | 报销制度 | 直属主管和财务负责人审批 |
| 免费午餐 | 没有对应资料 | 明确表示无法根据知识库确定 |

第三个问题非常重要，它用于测试模型是否会在没有证据时编造答案。

---

## 8. 最重要的排错顺序

回答不正确时，按照下面的顺序检查：

```text
原始文档里有答案吗？
  ↓ 有
切块后答案仍然完整吗？
  ↓ 是
正确 chunk 进入 Top-K 了吗？
  ↓ 是
正确 chunk 被放进 Prompt 了吗？
  ↓ 是
模型是否依据它回答？
```

对应的问题分类：

| 现象 | 所属环节 | 优先检查 |
|---|---|---|
| 文档本来就没有答案 | 知识源 | 补充或修正文档 |
| 一条规则被切成两半 | 切块 | 标题结构、chunk size、overlap |
| 正确块排不到前几名 | 检索 | 问题表达、Embedding、Top-K、文档质量 |
| Prompt 中没有检索文本 | 组装 | `context` 格式和变量名 |
| Prompt 有正确证据但回答错误 | 生成 | Prompt、聊天模型、上下文噪声 |
| LangSmith 没有 retriever trace | 观测 | 函数是否调用、环境变量是否先加载 |

不要一看到错误答案就立刻修改 Prompt。很多 RAG 问题实际发生在切块或检索阶段。

---

## 9. 把 Retriever 接入 Agent

掌握两步式 RAG 后，可以让 Agent 自己决定是否查询知识库。

```python
from langchain.agents import create_agent
from langchain.tools import tool


@tool
def search_company_handbook(query: str) -> str:
    """查询公司年假、报销和远程办公制度。"""
    documents = retrieve(query, k=3)
    return format_context(documents)


rag_agent = create_agent(
    model=llm,
    tools=[search_company_handbook],
    system_prompt=(
        "你是公司制度助手。遇到公司年假、报销或远程办公问题时，"
        "必须先调用 search_company_handbook。"
        "如果检索内容不足，明确表示无法根据知识库确定。"
    ),
)

agent_result = rag_agent.invoke({
    "messages": [
        {"role": "user", "content": "800 元办公费需要谁审批？"}
    ]
})

for message in agent_result["messages"]:
    print(type(message).__name__)
    print("content:", message.content)
    print("tool_calls:", getattr(message, "tool_calls", None))

wait_for_all_tracers()
```

这段代码要求聊天模型支持 Function Calling。你之前使用的 `qwen3.5-ocr` 不支持，必须使用 `qwen3.5-flash`、`qwen3.5-plus` 等支持工具调用的模型。

Agentic RAG 的成功消息序列通常是：

```text
HumanMessage
AIMessage(tool_calls=[search_company_handbook])
ToolMessage(检索结果)
AIMessage(最终回答)
```

如果模型只是把 JSON 打印在 `content` 中，而 `tool_calls` 为空，说明并没有真正调用检索工具。

---

## 10. 从演示升级到真实项目

当前示例故意保持最小。学习完成后，可以按实际需求逐步升级：

### 10.1 更多文档格式

- Markdown/TXT：可以直接读取；
- PDF：需要 PDF Loader，并检查解析后的文本顺序；
- Word：需要 DOCX Loader；
- 网页：需要 HTML/Web Loader，并过滤导航栏等噪声。

重点不是“Loader 有没有成功返回”，而是打印 `Document.page_content` 后内容是否干净、完整。

### 10.2 持久化向量库

`InMemoryVectorStore` 每次重启都要重新向量化。需要保存索引时，可以换成 Chroma、Qdrant、PGVector 等。

切换向量库通常不会改变主流程：

```text
Document → chunks → embeddings → vector store → retriever
```

但需要额外考虑：

- 文档更新后如何增量同步；
- 如何避免重复写入；
- 如何删除已经下线的文档；
- Embedding 模型或向量维度变化后如何重建索引；
- 测试环境是否会误改生产索引。

### 10.3 增加引用

生产回答不要只让模型“自己写来源”。应该由程序保存每个检索结果的 metadata，再把真实来源与回答一起返回。

### 10.4 增加检索评测

至少准备一组带标准来源的问题：

```python
evaluation_cases = [
    {
        "question": "员工每年有多少天带薪年假？",
        "expected_source": "company-handbook.md",
        "required_text": "10 天",
    },
    {
        "question": "800 元办公费需要谁审批？",
        "expected_source": "company-handbook.md",
        "required_text": "财务负责人",
    },
]
```

评测时分开观察：

- Retrieval Hit@K：正确来源是否进入前 K 名；
- Recall@K：所有应该召回的来源中，前 K 名找回了多少；
- MRR：第一个正确结果排得有多靠前；
- Answer correctness：最终答案是否包含关键事实；
- Groundedness：答案中的结论是否都能从检索文本找到证据。

只有“平均相似度”或“返回结果不为空”不能证明 RAG 有效。

---

## 11. 常见误区

### `@traceable` 会自动执行检索吗？

不会。它只记录被装饰函数的实际执行。

### RAG 必须使用 Agent 吗？

不必须。固定的两步式 RAG 更简单，也经常更适合生产知识库问答。

### 聊天模型可以同时充当 Embedding 模型吗？

通常不可以。聊天模型生成文本，Embedding 模型生成向量，它们的接口和任务不同。

### 文档全部塞进 Prompt，不做向量检索行不行？

文档很少时可以，但随着资料增多，会遇到上下文长度、成本、噪声和延迟问题。

### Top-K 越大越好吗？

不是。K 太小可能漏掉证据，K 太大会把无关内容送给模型。应该通过真实问题集评测。

### Chunk 越小越精确吗？

不是。过小会破坏完整语义。切块质量需要通过打印 chunk 和检索测试共同判断。

### LangSmith 有 trace 就说明 RAG 正确吗？

不是。Trace 证明代码运行并记录了过程，正确性仍需要标准问题和预期证据来评测。

---

## 12. 推荐学习顺序

建议按下面的顺序练习，每一步都确认输出后再继续：

1. 加载并打印原始文档；
2. 切块并打印所有 chunk；
3. 对一句话执行 `embed_query()`，观察向量维度；
4. 建立内存向量库；
5. 只测试检索，不调用聊天模型；
6. 把检索结果手动放入 Prompt；
7. 在 LangSmith 中查看 retriever 和 model；
8. 测试“知识库中没有答案”的问题；
9. 准备标准问题集评测 Top-K；
10. 最后再学习 Agentic RAG 和持久化向量库。

只要始终把“检索”和“生成”分开观察，RAG 就不会是一个难以理解的黑盒。

---

## 13. 延伸阅读

- [LangChain Retrieval 总览](https://docs.langchain.com/oss/python/langchain/retrieval)
- [LangChain 构建语义搜索知识库](https://docs.langchain.com/oss/python/langchain/knowledge-base)
- [LangChain Vector Store 接口](https://docs.langchain.com/oss/python/integrations/vectorstores)
- [阿里云百炼 OpenAI 兼容 Embedding 接口](https://help.aliyun.com/zh/model-studio/embedding-interfaces-compatible-with-openai/)
- [LangSmith 追踪 LangChain 应用](https://docs.langchain.com/langsmith/trace-with-langchain)
