# 第08章：从批准设计到最终 Blueprint

## 本章目标

继续追踪批准后的数据，判断哪些设计字段已经形成确定性约束，哪些仍经过兼容 dict 和模型生成。

源码锚点：[design_review_node.py](../../../WildAgent/wild-server/app/agent/nodes/design_review_node.py)、[resolver.py](../../../WildAgent/wild-server/app/design/resolver.py)、[skeleton_node.py](../../../WildAgent/wild-server/app/agent/nodes/skeleton_node.py)、[merge_node.py](../../../WildAgent/wild-server/app/agent/nodes/merge_node.py)、[validate_node.py](../../../WildAgent/wild-server/app/agent/nodes/validate_node.py)。

## 1. 批准后先编译兼容协议

`design_review` confirm 分支不会直接把 Pydantic 对象传给 skeleton。它调用：

```python
architecture_plan_from_document(approved)
```

将批准文档编译为现有节点认识的 `architecture_plan: dict`，包括 massing、complexity、volumes、structural_grid、facades、roof、component_quota 等。

这是迁移适配层。它让新设计主线可以接入旧生成链，但也说明下游尚未完全改成直接消费类型化对象。

## 2. skeleton 产生几何实现层

`skeleton_generator` 读取 `architecture_plan` 和 `material_plan`：

1. 生成或回退到主体 Blueprint；
2. 应用已解析材质；
3. 计算墙体包围盒和空间不变量；
4. `resolve_facade_layout(blueprint, architecture_plan)` 将抽象开间映射到真实 wall id；
5. 产出 `design_brief`、组件建议和诊断。

`ResolvedDesign.facade_slots` 在审核前负责稳定预览；骨架完成后仍需根据实际 wall id 再生成 `design_brief.opening_slots`。这是两个不同坐标阶段，但两者之间目前仍通过兼容 `architecture_plan` 衔接。

## 3. Send 与组件 fan-in

`_dispatch_components(state)` 组合：

- `suggested_components`；
- 用户原始消息；
- `design_brief.component_quota`；
- 当前组件注册表。

然后返回若干 `Send(f"{type}_gen", state)`。每条分支运行 `gen → val`，结果写入带 `merge_state_mapping` 的 `component_fragments` 和 `component_diagnostics`，最后汇入 merge。

## 4. merge 与 final_validate

merge 会：

- 合并 skeleton 和组件分片；
- 按 `design_brief` 对齐门窗、阳台、栏杆和屋顶槽位；
- 执行校验与确定性修复；
- 检查设计配额；
- 写入 Blueprint meta：

```text
designSchemaVersion ← design_document.schema_version
designRevision      ← design_document.revision
designHash          ← resolved_design.design_hash
```

final_validate 再对当前 Blueprint 指纹运行或复用完整校验。交付保存后，DesignRepository 只有在 revision 和 designHash 匹配时才把文档标成 `compiled`。

## 5. 当前仍未完全收口的地方

| 位置 | 当前做法 | 风险/代价 |
| --- | --- | --- |
| State schema | 多数字段为 `dict` | 节点边界仍需各自 model_validate |
| approved → skeleton | 编译回 `architecture_plan` | 存在兼容转换层 |
| 预览槽位 → 真实墙槽位 | skeleton 后重建 `design_brief` | 需验证两阶段语义一致 |
| 最终设计约束 | validator 读取 `design_brief` | 尚未统一读取一个类型化 GenerationSpec |

更完整的下一阶段应建立一个由批准文档编译出的类型化 `GenerationSpec`，把抽象设计、真实墙映射、组件配额和 validator 输入连成一份协议。它应逐节点迁移，不能一次删除兼容字段。

## Notebook 分单元格练习

### Cell 1：建立字段血缘表

- 输入：本章链路；
- 前序依赖：第06章；
- 预期：亲手补全消费者；
- 观察：同一意图在抽象和几何阶段字段名不同。

```python
lineage = [
    {
        "fact": "正立面开间模式",
        "design_document": "/decisions/facades/front",
        "resolved_design": "facade_slots",
        "generation_state": "architecture_plan.facades / design_brief.opening_slots",
        "blueprint_effect": "TODO",
    },
    {
        "fact": "门窗配额",
        "design_document": "/decisions/component_quota",
        "resolved_design": "component_quantities",
        "generation_state": "design_brief.component_quota",
        "blueprint_effect": "TODO",
    },
]
lineage
```

### Cell 2：验证批准文档确实被重新编译

- 输入：`sources["design_review"]` 与 `sources["resolver"]`；
- 前序依赖：第00章；
- 预期：找到编译函数及其关键返回字段；
- 观察：不是继续信任审核前的 plan。

```python
checks = {
    "review_compiles": "architecture_plan_from_document(approved)" in sources["design_review"],
    "massing_compiled": '"massing": d.massing.model_dump' in sources["resolver"],
    "facades_compiled": '"facades": {' in sources["resolver"],
    "quota_compiled": '"component_quota": {' in sources["resolver"],
}
checks
```

### Cell 3：验证最终追溯字段

- 输入：`sources["merge"]` 与 `sources["ws"]`；
- 前序依赖：第00章；
- 预期：三项 meta 和 compiled 回写均存在；
- 观察：hash 证明内容对应关系，revision 证明版本关系。

```python
for token in ("designSchemaVersion", "designRevision", "designHash"):
    print(token, "→", token in sources["merge"])
print("mark_compiled →", "mark_compiled(" in sources["ws"])
```

### Cell 4：给每个关键字段分级

在 Notebook 中为 `facades`、`component_quota`、`materials`、`design_hash` 标记：

- A：类型化并由确定性代码执行；
- B：类型化后编译到兼容 dict 执行；
- C：只进入 Prompt；
- D：只用于诊断或展示。

每个结论附一处 producer 和一处 consumer 源码位置。

## 错误实验

看到 `resolved_design.facade_slots` 后直接断言 skeleton 使用了它。搜索 `state.get("resolved_design")` 的消费者，你会发现当前主要由审核预览和 merge 元数据使用；实际 wall id 槽位仍由 skeleton 结合 Blueprint 解析。这是判断“字段利用率”必须查消费者的实例。

## 完成检查

- [ ] 我能追踪批准文档怎样进入 skeleton
- [ ] 我能解释抽象预览槽位与真实 wall 槽位为何分两阶段
- [ ] 我能说明 Reducer 只解决并行分片合并
- [ ] 我能指出当前最需要继续类型化的兼容边界
