# 第03章：`Protocol` 与策略模式

## 本章目标

通过 WildAgent 的 `SearchClient(Protocol)` 理解：调用者依赖行为契约，不必依赖具体类，也不要求实现类显式继承接口。

## 前置知识

- 类、方法和类型注解；
- `async def` 与 Notebook 顶层 `await`；
- 第02章工厂负责选择具体实现。

## 1. WildAgent 的真实结构

只读源码：

- [`search_client.py`](../../../WildAgent/wild-server/app/agent/web/search_client.py)：`SearchClient(Protocol)`、`TavilySearchClient`、`MockSearchClient`；
- [`web/__init__.py`](../../../WildAgent/wild-server/app/agent/web/__init__.py)：`create_search_client()`；
- [`web_research_node.py`](../../../WildAgent/wild-server/app/agent/nodes/web_research_node.py)：调用工厂并使用客户端。

```text
web_research_node
→ create_search_client(config)
→ SearchClient | None
→ client.search(SearchQuery)
→ client.fetch_page(url)
```

`TavilySearchClient` 和 `MockSearchClient` 没有写 `class X(SearchClient)`。它们只要具有兼容的 `search()` 和 `fetch_page()` 方法，就满足结构化类型契约。这与 Python 的鸭子类型一致。

策略模式体现在：调用流程不变，客户端对象改变，搜索行为随之改变。

## 2. Notebook 分单元格观察

### Cell 1：声明行为契约

- 输入：无；
- 依赖：无；
- 预期：`Protocol` 只描述方法，不创建实现；
- 观察：方法体中的 `...` 表示接口占位。

```python
from dataclasses import dataclass
from typing import Protocol

@dataclass(frozen=True)
class MiniSearchQuery:
    query: str
    max_results: int = 4


class MiniSearchClient(Protocol):
    async def search(self, query: MiniSearchQuery) -> list[str]:
        ...

    async def fetch_page(self, url: str) -> str:
        ...
```

代码解释：`Protocol` 主要帮助类型检查器和阅读者。Python 运行时不会自动检查每个返回值是否符合注解。

### Cell 2：写两个不继承 Protocol 的策略

- 输入：固定结果；
- 依赖：Cell 1；
- 预期：两个类都提供相同方法名；
- 观察：实现细节完全不同。

```python
class MemorySearchClient:
    def __init__(self, documents: list[str]):
        self.documents = documents

    async def search(self, query: MiniSearchQuery) -> list[str]:
        matches = [item for item in self.documents if query.query in item]
        return matches[:query.max_results]

    async def fetch_page(self, url: str) -> str:
        return f"memory page:{url}"


class EmptySearchClient:
    async def search(self, query: MiniSearchQuery) -> list[str]:
        return []

    async def fetch_page(self, url: str) -> str:
        return ""
```

代码解释：两个类没有显式继承 `MiniSearchClient`，但方法形状兼容。它们分别模拟有数据和降级为空的策略。

### Cell 3：调用者只依赖协议

- 输入：任意符合协议的对象；
- 依赖：Cell 1、2；
- 预期：同一函数得到两种结果；
- 观察：调用者没有 `isinstance` 分支。

```python
async def collect_titles(client: MiniSearchClient, text: str) -> list[str]:
    query = MiniSearchQuery(text, max_results=2)
    return await client.search(query)

memory_strategy = MemorySearchClient(["住宅规范", "住宅采光", "办公建筑"])
empty_strategy = EmptySearchClient()

memory_result = await collect_titles(memory_strategy, "住宅")
empty_result = await collect_titles(empty_strategy, "住宅")

assert memory_result == ["住宅规范", "住宅采光"]
assert empty_result == []
print(memory_result, empty_result)
```

代码解释：策略被作为参数注入。调用者只发出 `search()`，不关心结果来自网络、内存还是测试替身。

### Cell 4：观察测试替身的价值

- 输入：可控内存结果；
- 依赖：Cell 2、3；
- 预期：没有网络也能验证筛选和数量；
- 观察：WildAgent 的 `MockSearchClient` 承担相同角色。

```python
controlled = MemorySearchClient(["A-住宅", "B-住宅", "C-住宅"])
limited = await collect_titles(controlled, "住宅")

assert limited == ["A-住宅", "B-住宅"]
print("可控结果：", limited)
```

代码解释：测试替身让上层节点测试不依赖网络稳定性，也不需要真实 API Key。

### Cell 5：主动传入不满足协议的对象

- 输入：缺少 `search()` 的类；
- 依赖：Cell 3；
- 预期：运行到调用点时出现 `AttributeError`；
- 排查方向：对象具体类型 → 协议要求的方法 → 工厂返回路径。

```python
class BrokenClient:
    pass

try:
    await collect_titles(BrokenClient(), "住宅")
except AttributeError as exc:
    print(type(exc).__name__, str(exc))
```

代码解释：类型注解没有拦住运行时错误。IDE、Pyright 或 mypy 可提前发现问题，但生产边界仍需测试和错误处理。

## 3. 补充知识点

策略模式关注“可替换算法/行为”，Protocol 只是表达契约的一种 Python 工具。没有 Protocol 也能使用鸭子类型；有 Protocol 后，调用关系更容易读懂和静态检查。

## 4. 完成检查

- [ ] 我能找到 WildAgent 三个搜索相关类及工厂
- [ ] 我能解释为什么实现类没有显式继承也能工作
- [ ] 我能区分工厂的“选择实现”和策略的“执行行为”
- [ ] 我能说明 Mock 策略为什么提高测试稳定性
- [ ] 我知道类型注解不会自动完成运行时校验
