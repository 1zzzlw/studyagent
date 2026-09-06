# LangSmith Datasets & Experiments 最小学习指南

本模块只做一件事：把一组标准问题交给第二模块写好的 RAG 批量运行，然后在 LangSmith 官网查看结果。

```text
手动上传 CSV → 得到 Dataset → 调用本地 ask_rag() → evaluate() → Experiment
```

## 1. Dataset 和知识库不是同一个东西

项目已经准备了两类文件：

```text
03-evaluation/knowledge/*.md
= RAG 回答时检索的 7 份公司制度

03-evaluation/data/rag-evaluation-cases.csv
= 28 道标准问题、参考答案和分类信息
```

知识文件是给 RAG 查资料，CSV Dataset 是给 RAG 出题。

## 2. 在官网手动上传 CSV

进入：

```text
Datasets & Experiments → New Dataset → CSV
```

上传：

```text
03-evaluation/data/rag-evaluation-cases.csv
```

Dataset 名称填写：

```text
rag-evaluation-cases
```

第一遍只映射两个字段：

| CSV 字段 | 映射位置 |
|---|---|
| `question` | Input |
| `reference_answer` | Reference Output |

上传后确认每条 Example 都有：

```text
Input.question
Reference Output.reference_answer
```

## 3. 官网配置模型和代码运行的区别

如果在 LangSmith Playground 中选择 Dataset、Prompt、大模型和 Evaluator，测试的是：

```text
官网 Prompt + 官网选择的模型
```

但是官网不能直接访问你电脑内存中的：

```python
vector_store
retrieve()
ask_rag()
```

因此，只在官网配置模型不能测试当前 Notebook 中完整的本地 RAG。

要测试第二模块的完整链路，只需用一个很薄的 Target 调用本地 `ask_rag()`。大模型仍然使用第二模块已经创建的 `llm`，测试代码中不用重复配置。

## 4. 准备本地 RAG

创建：

```text
03-evaluation/01.datasets-experiments.ipynb
```

复用第二模块代码，但将知识目录改成：

```python
from pathlib import Path

knowledge_dir = Path.cwd() / "03-evaluation" / "knowledge"
if not knowledge_dir.exists():
    knowledge_dir = Path.cwd() / "knowledge"
```

然后按照第二模块建立：

```text
documents → chunks → embeddings → vector_store → retrieve() → ask_rag()
```

先确认本地 RAG 可以回答：

```python
result = ask_rag("800元办公费用需要谁审批？")
print(result["answer"])
```

## 5. 最小 Experiment 代码

下面就是与官网示例对应的完整代码：

```python
from langsmith import evaluate


# 1. 选择手动上传的 Dataset
dataset_name = "rag-evaluation-cases"


# 2. 定义要测试的本地 RAG
def rag_target(inputs: dict) -> dict:
    result = ask_rag(inputs["question"])
    return {"answer": result["answer"]}


# 3. 定义最简单的评分规则
def exact_match(outputs: dict, reference_outputs: dict) -> bool:
    actual = outputs["answer"].strip()
    expected = reference_outputs["reference_answer"].strip()
    return actual == expected


# 4. 批量运行，结果会成为一个 Experiment
experiment_results = evaluate(
    rag_target,
    data=dataset_name,
    evaluators=[exact_match],
    experiment_prefix="rag-evaluation-cases experiment",
    max_concurrency=1,
)

print(experiment_results)
```

结构和官网示例完全相同：

```python
evaluate(
    target,
    data=dataset_name,
    evaluators=[evaluator],
    experiment_prefix="...",
)
```

官网示例的 Target 是一个演示用 `lambda`；这里把它换成真正的本地 RAG：

```python
def rag_target(inputs):
    return {"answer": ask_rag(inputs["question"])["answer"]}
```

这里只调用 `evaluate()`；CSV 已经由你在官网手动上传。

## 6. `evaluate()` 做了什么

```text
从 Dataset 取第 1 道题
→ 调用 rag_target(inputs)
→ 保存实际答案和 Trace
→ 调用 exact_match() 评分
→ 继续下一道题
→ 汇总成 Experiment
```

参数含义：

```python
evaluate(
    rag_target,                  # 要测试的程序
    data=dataset_name,           # 官网的测试题库
    evaluators=[exact_match],    # 阅卷规则
    experiment_prefix="...",    # 实验名称
    max_concurrency=1,           # 一次运行一道
)
```

## 7. 为什么不能直接照抄官网的 `exact_match`

官网示例是：

```python
def exact_match(outputs: dict, reference_outputs: dict) -> bool:
    return outputs == reference_outputs
```

我们的实际输出是：

```python
{"answer": "需要直属主管和财务负责人共同审批。"}
```

CSV 参考输出是：

```python
{"reference_answer": "需要直属主管和财务负责人审批。"}
```

整个字典直接比较一定不相等。因此需要明确比较两个文本字段：

```python
return (
    outputs["answer"].strip()
    == reference_outputs["reference_answer"].strip()
)
```

即便这样，自然语言多一个“共同”也会得到 `False`。第一次可以先用它跑通流程，但大量 `False` 不一定表示语义错误。

## 8. 可选：使用简单关键词评分

不想要求逐字相同时，上传 CSV 时再把 `required_answer_terms` 映射到 Reference Output：

```python
import re


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", "", text).lower()


def answer_contains_required_terms(
    outputs: dict,
    reference_outputs: dict,
) -> float:
    raw_terms = reference_outputs.get("required_answer_terms", "")
    terms = [term.strip() for term in raw_terms.split("|") if term.strip()]

    if not terms:
        return 1.0

    answer = normalize_text(outputs.get("answer", ""))
    matched = sum(normalize_text(term) in answer for term in terms)
    return matched / len(terms)
```

然后改成：

```python
evaluate(
    rag_target,
    data=dataset_name,
    evaluators=[answer_contains_required_terms],
    experiment_prefix="rag-keyword-evaluation",
    max_concurrency=1,
)
```

这是可选优化，不影响先用 `exact_match` 跑通最小流程。

## 9. 在官网查看结果

运行结束后会打印 Experiment 链接，也可以进入：

```text
Datasets & Experiments
→ rag-evaluation-cases
→ Experiments
```

页面中可以看到：

- 输入问题
- Reference Output
- RAG 实际答案
- Evaluator 分数
- 耗时和完整 Trace

点击某一道题，还能查看 Retriever 找到了什么、哪些内容进入 Prompt，以及模型如何回答。

## 10. 最终只需要记住

```python
from langsmith import evaluate


def rag_target(inputs: dict) -> dict:
    return {"answer": ask_rag(inputs["question"])["answer"]}


def exact_match(outputs: dict, reference_outputs: dict) -> bool:
    return (
        outputs["answer"].strip()
        == reference_outputs["reference_answer"].strip()
    )


evaluate(
    rag_target,
    data="rag-evaluation-cases",
    evaluators=[exact_match],
    experiment_prefix="rag experiment",
    max_concurrency=1,
)
```

一句话总结：

> CSV 在官网手动上传；本地 RAG 和大模型沿用第二模块；第三模块只定义 Target 和 Evaluator，然后调用 `evaluate()`。

## 11. 什么时候完全在官网配置模型

如果只测试 Prompt，不需要调用本地知识库和向量检索，可以完全使用 Playground：

```text
选择 Dataset → 编写 Prompt → 选择模型 → 添加 Evaluator → Start Experiment
```

如果测试本地 RAG，仍需要 `rag_target()`，因为官网无法直接访问本地 Python 内存中的向量库。

## 12. 官方文档

- [LangSmith Evaluation Quickstart](https://docs.langchain.com/langsmith/evaluation-quickstart)
- [定义 Target Function](https://docs.langchain.com/langsmith/define-target-function)
- [定义代码 Evaluator](https://docs.langchain.com/langsmith/code-evaluator-sdk)
- [RAG Evaluation Tutorial](https://docs.langchain.com/langsmith/evaluate-rag-tutorial)
