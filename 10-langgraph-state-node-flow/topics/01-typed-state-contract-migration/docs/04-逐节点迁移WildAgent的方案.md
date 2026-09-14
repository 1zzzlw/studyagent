# 第04章：逐节点迁移 WildAgent 的方案

## 本章目标

把专题中的缩小实现映射回 WildAgent，形成以后可以执行的迁移顺序。这里只制定方案和测试边界，不修改 WildAgent。

源码锚点：[专题实现](../contract_pipeline.py)、[专题测试](../tests/test_contract_pipeline.py)。WildAgent 只读对照：[graph.py](../../../../../WildAgent/wild-server/app/agent/graph.py)、[graph_state.py](../../../../../WildAgent/wild-server/app/agent/graph_state.py)、[design_review_node.py](../../../../../WildAgent/wild-server/app/agent/nodes/design_review_node.py)、[skeleton_node.py](../../../../../WildAgent/wild-server/app/agent/nodes/skeleton_node.py)、[merge_node.py](../../../../../WildAgent/wild-server/app/agent/nodes/merge_node.py)。

## 1. 目标拓扑

当前兼容链：

```text
design_review confirm
→ architecture_plan_from_document()
→ architecture_plan: dict
→ skeleton
→ resolve_facade_layout()
→ design_brief: dict
→ component / merge / validator
```

建议目标链：

```text
design_review confirm
→ design_compile
→ generation_spec
→ skeleton
→ 将真实 wall id 写入 generation_realization
→ component / merge / validator 读取同一协议
```

`generation_spec` 保存审核前就能确定的设计事实；`generation_realization` 保存 skeleton 出现真实 wall id 后才能确定的映射。两者需要不同 schema，不能假装审核前已经知道最终 wall id。

## 2. 第一步：先建立消费者清单

对 `architecture_plan` 和 `design_brief` 的每个字段建立表：

| 字段 | 生产者 | 消费者 | 影响产物 | validator | 测试 |
| --- | --- | --- | --- | --- | --- |
| massing | architecture/review | skeleton | 主体尺寸 | dimensions | 待填写 |
| facades | architecture/review | layout resolver | 门窗模式 | design brief | 待填写 |
| component_quota | architecture/review | dispatch/merge | 构件数量 | design brief | 待填写 |
| opening_slots | skeleton | component/merge | parentWall 坐标 | opening fit | 待填写 |

没有消费者的字段先标为 unused；只进入 Prompt 的字段标为 weak；有确定性消费者和测试的字段才标为 enforced。

## 3. 第二步：并行引入 design_compile

不要立即删除 `architecture_plan`。先增加：

```text
GenerationState.generation_spec
design_compile 节点
DesignDocument → GenerationSpec 编译器
```

路由目标：

```text
design_review approved
→ design_compile
→ 普通模式 skeleton
→ Plan 模式 plan_executor
```

这一阶段的测试应先证明：

- draft/revise 文档不能编译；
- approved revision 能编译；
- 编译结果可 JSON 序列化；
- hash 与 revision 对应；
- 路由不会绕过 design_compile。

## 4. 第三步：迁移 skeleton，一个字段组一次

先让 skeleton 同时读取新旧协议，并增加对比诊断：

```text
legacy massing 与 generation_spec.bounds 是否一致
legacy floors 与 generation_spec.levels 是否一致
legacy quota 与 generation_spec.component_quantities 是否一致
```

对比的是语义不变量，不要求两个 JSON 完全相同。新路径稳定后，按字段组移除 skeleton 对 legacy plan 的读取。

每迁移一组，都需要测试：

```text
给定 approved design
→ 编译 GenerationSpec
→ skeleton 输出满足对应 bounds/levels
→ 改变该字段时输出发生可预测变化
```

最后一条是“利用率测试”：输入字段变化后产物必须变化，能防止字段虽然存在却被忽略。

## 5. 第四步：建立 GenerationRealization

真实墙体生成后，增加类型化实现映射：

```text
schema_version
design_id / revision / hash
wall_bindings
opening_slots(parent_wall_id + local coordinates)
component_quantities
roof_bindings
```

它逐步替换 `design_brief`。组件节点和 validator 读取相同槽位对象，避免一边生成、一边用另一份配额字典验收。

测试重点：

- 每个 opening slot 的 parent wall 存在；
- 局部坐标能落在宿主墙范围；
- slot 数量与 quota 一致；
- 同一 slot 不能被两个组件重复占用；
- realization 的 design hash 必须匹配 GenerationSpec。

## 6. 第五步：迁移并行组件与 Reducer

保留按组件类型分 key 的 `component_fragments` Reducer，但明确每个 key 只能有一个所有者。若同类型需要多个并行 worker，值应改为带稳定 fragment id 的映射，Reducer 在重复 id 时拒绝或显式覆盖，不能依赖调度顺序。

相应测试：

```text
不同 fragment id → 全部保留
重复 fragment id 且内容相同 → 幂等
重复 fragment id 且内容不同 → 冲突
```

## 7. 最后才删除兼容字段

只有以下条件全部满足，才删除 `architecture_plan` 或 `design_brief`：

- 源码搜索没有生产消费者；
- Graph checkpoint 升级策略已确定；
- API/前端不再读取；
- 新旧语义对比测试已稳定；
- 恢复旧任务时有明确拒绝或迁移提示；
- 全链路测试证明设计字段变化会影响产物。

这比“一次把所有 dict 改成 Pydantic”慢一些，但每一步都可回归、可定位、可回滚。

## 单元测试学习步骤

### Step 1：运行专题全部测试

先确认12项核心测试通过，LangGraph 适配按环境通过或跳过。

### Step 2：按未来节点顺序给测试排序

```text
RuntimeContractTests
→ NodeBoundaryTests
→ RevisionTests
→ CompilerContractTests
→ LangGraphAdapterTests
```

说明每组测试对应哪个节点边界。

### Step 3：添加一项“字段利用率测试”

复制成功编译测试，分别用 width=20 和 width=24 构建设计，断言 `generation_spec.bounds.width` 不同。不要比较无关字段。

### Step 4：设计一项 realization 测试

先只写测试名称和 Given–When–Then，不实现生产代码：

```python
def test_opening_slot_must_reference_an_existing_wall():
    # Given：GenerationSpec 和只有一面墙的 skeleton
    # When：把 facade slot 绑定到真实 wall
    # Then：未知 parent wall 必须被拒绝
    ...
```

这个待实现测试定义了下一专题的起点，不需要改 WildAgent。

## 错误实验

直接从 GenerationState 删除 `architecture_plan`，再用“类型更安全”解释大量失败。这样无法判断失败来自哪个消费者。正确迁移以字段消费者和测试为单位，旧字段在最后一个消费者完成迁移后才删除。

## 完成检查

- [ ] 我能区分 GenerationSpec 与 GenerationRealization
- [ ] 我能写出 design_compile 的路由和前置条件
- [ ] 我知道如何用输入变化证明字段利用率
- [ ] 我能为同类型并行 fragment 定义冲突语义
- [ ] 我能列出删除旧 State 字段前的六项条件
- [ ] 我没有把专题方案描述成 WildAgent 已实现功能

