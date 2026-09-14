# 第04章：旧 dict 为什么利用率低

## 本章目标

不把问题简化成“dict 不好”。你要能定位：哪一类 dict 适合 State 传输，哪一类数据需要运行时契约，以及旧设计为何出现“字段生成了，下游却没有兑现”。

源码锚点：[graph_state.py](../../../WildAgent/wild-server/app/agent/graph_state.py)、[skeleton_node.py](../../../WildAgent/wild-server/app/agent/nodes/skeleton_node.py)、[merge_node.py](../../../WildAgent/wild-server/app/agent/nodes/merge_node.py)。

## 1. 三个概念先分开

| 对象 | 能做什么 | 做不到什么 |
| --- | --- | --- |
| Python `dict` | 灵活、易序列化、适合临时 payload | 自动检查字段拼写、范围和跨字段关系 |
| `TypedDict` | 给编辑器和静态检查器字段提示 | 运行时拒绝错误数据 |
| Pydantic Model | 运行时解析、校验、限制额外字段 | 自动保证每个下游真的消费字段 |

`GenerationState(TypedDict, total=False)` 中的 `total=False` 表示所有字段都允许缺省。它适合多分支 Graph，因为 chat 分支不需要 Blueprint 字段；它也意味着代码必须在需要字段的边界显式校验。

## 2. 旧方案的五个具体失效点

### 2.1 字段存在不代表形状正确

```python
old_plan = {
    "masssing": {"width": -20},  # key 拼错，数值也无效
    "facades": {"front": {"bays": 6}},
}
```

只要后续使用 `plan.get("massing", {})`，错误就会被安静地变成默认值，而不是在 architecture 边界失败。

### 2.2 Prompt 注入不等于约束执行

把完整 `architecture_plan` 写进 skeleton Prompt，只能提高模型遵循概率。模型仍可能漏掉 14 扇窗、改变对称关系或输出错误坐标。只有 resolver/compiler/validator 实际读取字段并拒绝偏差，才算执行。

### 2.3 下游只读取了计划的一部分

判断字段“利用率”不能看它是否出现在 State，要看：

```text
有生产者
→ 有运行时校验
→ 有明确消费者
→ 影响可观测产物
→ 有回归测试
```

旧 `architecture_plan` 中部分字段只参与 Prompt 或候选诊断；真正布局仍要等 skeleton 生成 Blueprint 后，再由 `resolve_facade_layout()` 建立 `design_brief`。同一设计意图跨了多份字典。

### 2.4 多份表示会漂移

```text
architecture_plan.component_quota
→ skeleton 后的 design_brief.component_quota
→ 实际 Blueprint components 数量
```

任何转换遗漏都会导致最终 `validate_design_brief` 才报“door/window 数量不足”。报错发生得晚，修复节点又只能从最终几何倒推设计意图。

### 2.5 没有版本身份

若用户在 SVG 上改了宽度，同时旧审核请求又提交，普通 dict 无法说明基于哪个版本。`revision`、`base_revision` 和 `design_hash` 解决的是并发与追溯，不只是类型提示。

## 3. 浅合并不是深合并

WildAgent 的 `merge_state_mapping`：

```python
merged = dict(left or {})
merged.update(right or {})
```

适合并行结果使用不同顶层 key：

```text
{"door": [...]} + {"window": [...]} → 两者都保留
```

若两个分支都写 `{"door": ...}`，右侧覆盖左侧；若写嵌套配置，也不会递归保留内部 key。Reducer 解决并行 channel 的合并规则，不解决设计 schema。

## Notebook 分单元格练习

### Cell 1：证明 TypedDict 不做运行时校验

- 输入：无；
- 前序依赖：无；
- 预期：错误 key 和负数仍能构造；
- 观察：编辑器警告与 Python 运行时行为不同。

```python
from typing import TypedDict

class OldPlan(TypedDict, total=False):
    massing: dict
    facades: dict

bad_plan: OldPlan = {
    "masssing": {"width": -20},
    "facades": {"front": {"bays": 6}},
}
print(bad_plan)
```

### Cell 2：观察静默默认值

- 输入：`bad_plan`；
- 前序依赖：Cell 1；
- 预期：打印 `unknown`；
- 观察：错误没有在产生位置暴露。

```python
width = bad_plan.get("massing", {}).get("width", "unknown")
print("下游读到的 width：", width)
```

### Cell 3：观察浅合并丢失嵌套字段

- 输入：两个局部设计字典；
- 前序依赖：无；
- 预期：`width` 消失；
- 观察：顶层 `massing` 被整体替换。

```python
left = {"massing": {"width": 20, "depth": 12}}
right = {"massing": {"floors": 3}}
merged = {**left, **right}
print(merged)
```

### Cell 4：从真实节点统计 State 读取

- 输入：第00章的 `sources`；
- 前序依赖：第00章；
- 预期：列出每个关键节点显式 `state.get(...)` 的字段；
- 观察：静态统计只能证明“代码尝试读取”，还需继续追踪读取值是否影响输出。

```python
import re

for node in ("architecture", "material", "design_review", "skeleton", "merge"):
    keys = sorted(set(re.findall(r'state\.get\("([^"]+)"', sources[node])))
    print(f"{node:14} → {keys}")
```

### Cell 5：建立字段利用率审计表

在 Notebook 创建五列：`field`、`producer`、`runtime_validator`、`consumer`、`artifact_effect`。先填写 `component_quota`、`facades`、`resolved_design.design_hash` 三行。

## 错误实验

仅因为 Cell 4 找到了某个 `state.get`，就把它标成“已充分使用”。继续检查它是只写日志、只拼 Prompt，还是进入确定性 resolver/compiler/validator。只有最后一类能形成强约束。

## 完成检查

- [ ] 我能解释 TypedDict 和 Pydantic 的运行时差别
- [ ] 我能说明 Prompt 约束为什么不是确定性约束
- [ ] 我能复现浅合并的覆盖行为
- [ ] 我会用生产、校验、消费、产物、测试五步判断字段利用率
