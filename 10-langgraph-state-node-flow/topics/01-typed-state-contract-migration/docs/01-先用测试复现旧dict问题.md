# 第01章：先用测试复现旧 dict 问题

## 本章目标

从两个最小失败行为理解：旧问题来自缺少边界契约和字段所有权，不能简单归因于 Python dict。

源码锚点：[OldDictFailureTests](../tests/test_contract_pipeline.py)、[legacy_read_width 与 Reducer](../contract_pipeline.py)。WildAgent 对照：[graph_state.py](../../../../../WildAgent/wild-server/app/agent/graph_state.py)。

## 1. 第一项测试：拼错 key 为什么不报错

测试输入：

```python
old_plan = {"masssing": {"width": 20}}
```

生产者想写 `massing`，实际写成 `masssing`。`legacy_read_width()` 使用：

```python
massing = plan.get("massing")
```

结果是 `None`。错误没有在生产节点暴露，而是在更晚的消费者中变成默认值、回退值或缺失构件。

运行：

```powershell
uv run python -m unittest discover `
  -s 10-langgraph-state-node-flow/topics/01-typed-state-contract-migration/tests `
  -v -k typo
```

预期：测试通过，并证明旧读取会静默得到缺失值。

## 2. 第二项测试：Reducer 解决什么

`merge_component_fragments(left, right)` 使用顶层 `dict.update()`：

```text
left  = {door: [door_a], window: [window_a]}
right = {door: [door_b]}
结果  = {door: [door_b], window: [window_a]}
```

它适合不同组件类型各写自己的 key。两个分支同时拥有 `door` 时，后写覆盖前写。这个测试说明 Reducer 是并行合并规则，不是 schema 校验，也不是冲突检测。

## 3. 用 Given–When–Then 阅读测试

| 阶段 | 在测试中看什么 |
| --- | --- |
| Given | 构造了什么错误或边界输入 |
| When | 调用了哪个节点边界、编译器或 Reducer |
| Then | 是拒绝、保留、覆盖，还是生成可追溯产物 |

例如：

```text
Given：带 masssing 拼写错误的计划
When：旧消费者读取 massing.width
Then：得到 None，且没有异常
```

不要只看测试是绿是红，要用一句话写出它保护的业务不变量。

## 4. 为什么 giant dict 的利用率会越来越低

字段加入一个大 dict 的成本很低，真正接入以下五处的成本很高：

1. 生产节点输出；
2. 运行时 schema；
3. 确定性消费者；
4. 最终产物或 validator；
5. 回归测试。

如果只完成第1步，字段会出现在日志和 Prompt 中，却不会改变产物。专题后续使用 GenerationSpec 把第2～5步放进同一编译边界。

## 单元测试练习

### Step 1：增加一个只写日志的字段

在测试里构造 `{"design_note": "对称"}`，然后搜索 `contract_pipeline.py` 是否有消费者。不要立即修改实现，先记录“字段存在但利用率为0”的证据。

### Step 2：主动制造同 key 冲突

把 left 与 right 都改成 window key，预期右侧覆盖。再恢复测试原样，确保全部测试重新通过。

### Step 3：写出失败位置

为 typo 测试补一行注释，分别写出：

```text
理想失败位置：architecture 节点出口
旧实际暴露位置：下游消费者或最终校验
```

## 错误实验

把 `legacy_read_width()` 改成在缺失时返回 20。测试会失败或风险被掩盖。默认值只能表达合法缺省，不能吞掉生产者协议错误。

## 完成检查

- [ ] 我能区分 dict、Reducer 和运行时 schema 的职责
- [ ] 我能用 Given–When–Then 解释两个测试
- [ ] 我能说明为什么字段出现在 State 不代表被利用
- [ ] 我知道协议错误应尽量在生产节点出口失败

