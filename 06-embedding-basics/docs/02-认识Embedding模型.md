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
uv run python 06-embedding-basics\run.py sync --rebuild
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

## 4. 最小 Notebook

`01.basic.ipynb` 用三条短文本演示：

1. 文本向量化；
2. 写入 Chroma；
3. 问题向量化；
4. 相似度查询。

运行时重点观察向量维度，而不是打印完整向量。完整向量通常很长，打印它不会帮助理解。

## 5. 常见误区

- Embedding 模型不是聊天模型，不能拿它生成自然语言答案。
- 向量库不是大模型，它只存储并比较数据。
- “写入数据库成功”不等于“检索质量良好”。检索质量还受文档、切块、问题表达和 Top-K 影响。
- Hash 向量可以做离线管道测试，但不能代表真实语义检索质量。

