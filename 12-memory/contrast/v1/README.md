# 实验 v1

独立实现，基于原版 `12-memory/v2` 的节点、来源和衰减结构，借鉴 GA 检索及反思。

```powershell
E:\AgentProject\studyAgent\.venv\Scripts\python.exe E:\AgentProject\studyAgent\12-memory\contrast\v1\main.py
```

阅读顺序：`models.py` → `engine.py` → `store.py` → `strategy.py` → `reflection.py` → `runtime.py` → `cli.py`。

`strategy.py` 进行相关性、重要性、近期性重排；`reflection.py` 每轮检查新事件积累，达到条件后一次归纳，形成带 filling 证据的 thought。
不建立 A-Mem 的 context/tags/links。不会导入 v2 或 v3 的代码。

每轮在当前调用中同步完成记忆写入、强化、反思条件检查，可以阻塞。全部完成后才返回菜单或结束网页请求。
进度通过同步 report 回调显示；没有后台工作线程、任务队列、独立客户端或等待菜单。

实验方法、菜单、数据位置和验证范围见 [总说明](../README.md)。

默认3条新事件，或至少2条且重要性合计达到15时触发，并要求来自至少两次不同观察。本轮没有新事件则不反思。引用使用 M1、M2 等临时编号，逐条校验后映射成真实 ID；错误认识跳过并记录，其他有效结果保留。
