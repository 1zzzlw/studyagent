# 第03章：把批准设计编译为 GenerationSpec

## 本章目标

理解 DesignDocument、GenerationSpec 和 Blueprint 的职责区别，并用测试证明只有批准设计才能进入确定性编译。

源码锚点：[compile_generation_spec](../contract_pipeline.py)、[CompilerContractTests](../tests/test_contract_pipeline.py)。WildAgent 当前对照：[resolver.py](../../../../../WildAgent/wild-server/app/design/resolver.py)、[skeleton_node.py](../../../../../WildAgent/wild-server/app/agent/nodes/skeleton_node.py)。

## 1. 为什么还需要 GenerationSpec

DesignDocument 适合用户编辑：

- 20m × 12m；
- 3层；
- 正立面3开间；
- ground pattern 包含入口；
- window 配额20～40。

生成节点更需要已经算好的数据：

- 每层 base_y/top_y；
- 每个门窗槽位的 facing、floor、bay、offset、尺寸；
- 最终组件数量；
- 输入设计的 revision 与 hash。

如果每个节点各自从 DesignDocument 推导，就会产生多套计算逻辑。GenerationSpec 把这一步集中为一个确定性编译器。

## 2. 编译前置条件

`compile_generation_spec()` 首先执行：

```python
if doc.status != "approved":
    raise ValueError("只有 approved 设计才能编译 GenerationSpec")
```

它阻止 architecture 刚生成的 draft 绕过用户审核直接进入骨架。

运行：

```powershell
uv run python -m unittest discover `
  -s 10-langgraph-state-node-flow/topics/01-typed-state-contract-migration/tests `
  -v -k compiler_rejects_unapproved
```

## 3. 编译输出

学习版 GenerationSpec 包含：

| 字段 | 来源 |
| --- | --- |
| `design_id`、`design_revision` | DesignDocument 身份 |
| `design_hash` | schema、id、revision、decisions 的稳定序列化 |
| `bounds` | massing |
| `levels` | floors × floor_height |
| `facade_slots` | facade bays + pattern + level |
| `component_quantities` | 对生成槽位计数 |

编译器还对实际槽位数量和批准配额做比较。这样“至少20扇窗”不再只是 Prompt，而是编译不变量。

## 4. hash 证明什么

相同的设计 id、revision 和 decisions 会生成相同 hash。它可用于：

- 证明 SVG 与 Blueprint 是否基于同一设计；
- 拒绝用旧编译结果标记新 revision；
- 在测试中检测编译输入漂移。

hash 不能证明建筑美观，也不能代替 geometry validator。它只证明数据来源一致。

## 5. compiler 节点仍然只返回局部更新

`compiler_node_update(state)`：

```python
document = DesignDocument.model_validate(state.get("design_document"))
spec = compile_generation_spec(document)
return {"generation_spec": spec.model_dump(mode="json")}
```

它不修改 DesignDocument，不复制 request_id，也不生成 Blueprint。一个节点只完成一个状态转换。

## 单元测试练习

### Step 1：运行全部编译测试

- 输入：`-k CompilerContractTests`；
- 预期：3项通过；
- 观察：分别覆盖未批准拒绝、成功编译、稳定 hash。

### Step 2：观察确定性槽位

在 `test_approved_design_compiles_to_traceable_generation_spec` 中临时打印 `spec["facade_slots"][:3]`，记录 floor、bay、offset。完成后删掉打印。

### Step 3：制造配额冲突

把 sample document 的 window.min 改为 35。当前设计只有29个 window 槽位，编译应拒绝。记录错误发生在 compiler，而不是最终 Blueprint validator。

### Step 4：验证 revision 改变 hash

使用 `apply_width_patch()` 生成 revision 2，重新批准并编译。比较 revision 1 与 revision 2 的 hash，应不同。

## 错误实验

为了“让测试先通过”而在编译器里自动把 window 数量补到 min，却没有对应 facade slot。这样数量字段与空间布局会互相矛盾。编译器只能输出可由同一输入推导的一致事实，不能伪造计数。

## 完成检查

- [ ] 我能解释 DesignDocument 和 GenerationSpec 面向的消费者不同
- [ ] 我能证明 draft 无法进入编译
- [ ] 我能说明配额如何从文字要求变成编译不变量
- [ ] 我知道 design hash 的能力和边界

