# 第05章：DesignDocument 怎样成为设计事实

## 本章目标

理解新设计契约为什么不只是“大一点的 JSON”，以及知识库中的规则、某次设计决策、确定性派生数据应该分别放在哪里。

源码锚点：[contracts.py](../../../WildAgent/wild-server/app/design/contracts.py)、[resolver.py](../../../WildAgent/wild-server/app/design/resolver.py)、[repository.py](../../../WildAgent/wild-server/app/design/repository.py)、[test_design_document.py](../../../WildAgent/wild-server/tests/design/test_design_document.py)。

## 1. 顶层字段表达生命周期

`DesignDocument` 的核心结构：

| 字段 | 类型/约束 | 作用 |
| --- | --- | --- |
| `schema_version` | 固定为 `design/1.0` | 识别字段协议 |
| `design_id`、`session_id` | 非空字符串 | 关联设计与会话 |
| `revision` | `int >= 1` | 修改版本 |
| `status` | `draft/approved/compiled` | 设计生命周期 |
| `requirements` | `DesignRequirements` | 保留用户原始目标 |
| `decisions` | `ArchitectureDecisions` | 当前建筑决策 |
| `constraints` | `list[DesignConstraint]` | 当前设计必须满足的约束 |
| `locks` | JSON Pointer 列表 | 禁止修改的字段路径 |
| `rule_trace` | `list[RuleTrace]` | 规则来源、适用条件、执行位置 |

所有模型继承 `ContractModel`，其配置是：

```python
ConfigDict(extra="forbid", validate_assignment=True)
```

未知字段会被拒绝，赋值也会重新校验。

## 2. 跨字段规则比字段类型更关键

当前契约会检查：

- `modeled_floors <= floors`；
- full 表示模式下，两者必须相等；
- 立面 pattern 长度必须等于 bays；
- 楼上 pattern 不能放 door；
- 多层建筑不能选择 `vertical_strategy="none"`；
- 幕墙系统必须携带幕墙参数；
- `component_quota.max >= min`。

这些规则正是普通 `dict[str, Any]` 无法表达的建筑语义。

## 3. DesignDocument 与 ResolvedDesign

`DesignDocument` 保存“决定了什么”，例如建筑宽 20m、6 个开间、正立面模式为门窗组合。`resolve_design(document)` 再确定性推导：

- 总宽、总深、总高；
- 每层 `base_y/top_y`；
- 各立面门窗槽位；
- 组件目标数量；
- 当前 revision 的稳定 `design_hash`。

SVG 读取这份派生结果，Blueprint 在合并时写入相同 revision/hash。用户预览和最终产物因此有可验证联系。

## 4. 建筑知识应该怎样加工

你之前给出的“玻璃幕墙写字楼构件组成”不能整篇直接变成强制知识。应拆成五类：

| 原始内容 | 加工后归属 | 示例 |
| --- | --- | --- |
| WILD 引擎必须满足 | engine hard rule + validator | parentWall、合法组件类型 |
| 选中某系统后才适用 | conditional rule | 幕墙分格与楼层/开间对齐 |
| 本次用户明确选择 | DesignDocument decision | `envelope.system="curtain_wall"` |
| 可自由变化的审美方向 | preference | 银灰框、蓝灰玻璃 |
| 当前引擎不能表达 | reference/unsupported | 真实桩基计算、HVAC 设备联动 |

知识库维护“规则及来源”；DesignDocument 维护“本次选择和参数”；Resolver 把选择转成可计算数据。每种建筑可以有条件规则，但不应保存一份固定完整坐标蓝图。

## 5. 是否需要维护 JSON 字段类型

需要，而且要维护四类信息：

1. 类型与取值范围；
2. 跨字段不变量；
3. 字段所有者和可编辑范围；
4. schema 版本与迁移策略。

只写一份 JSON 示例不算 schema。当前 Pydantic 模型是后端权威定义，前端类型和编辑表单需要与它同步；`schema_version` 变化时应提供迁移，而不是悄悄改变旧字段含义。

## Notebook 分单元格练习

### Cell 1：从真实源码列出契约类

- 输入：`sources["contracts"]`；
- 前序依赖：第00章；
- 预期：列出 `DesignDocument`、`DesignPatch`、`ResolvedDesign` 等；
- 观察：一个大 dict 已拆成职责明确的小模型。

```python
import ast

contract_tree = ast.parse(sources["contracts"])
contract_classes = [
    node.name
    for node in contract_tree.body
    if isinstance(node, ast.ClassDef)
]
contract_classes
```

### Cell 2：做一个最小运行时校验对比

- 输入：studyAgent 环境中的 Pydantic；
- 前序依赖：无；
- 预期：负宽度或额外字段触发 `ValidationError`；
- 观察：错误在设计边界暴露。

```python
from pydantic import BaseModel, ConfigDict, Field, ValidationError

class MiniMassing(BaseModel):
    model_config = ConfigDict(extra="forbid")
    width: float = Field(gt=0, le=500)
    floors: int = Field(ge=1, le=200)

try:
    MiniMassing.model_validate({
        "width": -20,
        "floors": 3,
        "unknown": True,
    })
except ValidationError as exc:
    print(exc)
```

### Cell 3：把幕墙描述加工成规则记录

- 输入：玻璃幕墙写字楼描述；
- 前序依赖：本章分类表；
- 预期：亲手写三条小字典；
- 观察：每条都要有 `classification`、`applies_when`、`schema_targets`、`enforcement`。

```python
rule_trace_example = {
    "rule_id": "envelope.curtain-wall.floor-grid-alignment",
    "classification": "conditional",
    "applies_when": "envelope.system == curtain_wall",
    "schema_targets": ["/decisions/envelope", "/decisions/facades"],
    "enforcement": ["planner", "resolver", "validator"],
    "source": "rules-v2:glass-curtain-wall-assembly",
}
rule_trace_example
```

其余两条由你分别选择 preference 与 unsupported 内容填写，避免把百科描述全部标成 hard rule。

### Cell 4：检查真实回归证据

- 输入：只读测试文件；
- 前序依赖：第00章路径；
- 预期：找到 round trip、SVG path、revision conflict、locked patch 测试；
- 观察：测试证明的是契约行为，不等于完整模型生成质量。

```python
test_path = wildagent_root / "wild-server/tests/design/test_design_document.py"
test_source = test_path.read_text(encoding="utf-8")
for name in (
    "test_design_document_round_trip_and_resolution",
    "test_svg_is_derived_and_keeps_json_paths",
    "test_repository_patch_increments_revision_and_invalidates_approval",
    "test_repository_rejects_stale_or_locked_patch",
):
    print(name, "→", f"def {name}" in test_source)
```

## 错误实验

把“Low-E 玻璃通常节能”直接写成 `engine_hard`，却不给 schema target、编译器或 validator。此时它仍只是文字。规则必须能回答“何时适用、写入哪个字段、由哪一层执行”。

## 完成检查

- [ ] 我能解释 DesignDocument 与普通 JSON 示例的差别
- [ ] 我能区分设计决定和确定性派生值
- [ ] 我能把建筑描述分成 hard、conditional、preference、unsupported
- [ ] 我知道维护字段类型还包括不变量、所有权和版本
