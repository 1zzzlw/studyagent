# 实验 v3

独立实现，将 GA 的记忆分类、证据、检索与反思，A-Mem 的关联维护，以及原版 v2/05 的衰减强化组合。

```powershell
E:\AgentProject\studyAgent\.venv\Scripts\python.exe E:\AgentProject\studyAgent\12-memory\contrast\v3\main.py
```

阅读顺序：`models.py` → `engine.py` → `strategy.py` → `association.py` → `reflection.py` → `runtime.py` → `store.py` → `cli.py`。

正常对话后先维护本轮相关节点的语义说明和 links，再检查反思积累条件；达到条件才一次归纳，新 thought 也会参与关联维护。
检索时先使用 GA 三因素重排，再在相同上下文预算内补充语义邻居和 thought 证据。
filling、links、supersedes_id 分别保存来源依据、语义相关、明确纠正关系。不会导入 v1 或 v2 的代码。

每轮在当前调用中同步完成记忆写入、强化、反思条件检查与关联维护，可以阻塞。全部完成后才返回菜单或结束网页请求。
进度通过同步 report 回调显示；没有后台工作线程、任务队列、独立客户端或等待菜单。

实验方法、菜单、数据位置和验证范围见 [总说明](../README.md)。

默认3条新事件，或至少2条且重要性合计达到15时触发，并要求来自至少两次不同观察。本轮没有新事件则不反思。引用使用 M1、M2 等临时编号，逐条校验后映射成真实 ID；错误认识跳过并记录，其他有效结果保留。
