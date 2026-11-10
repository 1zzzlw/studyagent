# 实验 v2：纯 A-Mem

记忆结构与流程只借鉴本地 A-Mem 项目；不包含 Ebbinghaus、GA event/thought/chat、证据 filling、反思或重要性排序。

```powershell
E:\AgentProject\studyAgent\.venv\Scripts\python.exe E:\AgentProject\studyAgent\12-memory\contrast\v2\main.py
```

阅读顺序：`models.py` → `store.py` → `association.py` → `strategy.py` → `runtime.py` → `cli.py`。

1. `MemoryNote` 使用 A-Mem 原字段名：id、content、keywords、context、tags、category、links、timestamp、last_accessed、retrieval_count、evolution_history。
2. 回答先检索既有笔记，再沿已有 links 补充邻居；不混入时间、强度、重要性评分。
3. 回答后对用户原文做 `analyze_content`，再由 `process_memory` 查邻居，决定建立 links 或更新邻居 context/tags，最后保存笔记。
4. 所有步骤同步执行。访问次数只是统计，不是回忆强化；模型输出里的 strengthen 是“建立语义链接”。
5. CLI 和网页都从空笔记开始，不自动导入300条。网页显示完整原始字段，不显示强度或 GA 分类。

与参考实现相比，时间使用带时区的 ISO 格式，邻居按真实 ID 更新、演化历史会落库，检索给链接邻居预留位置。模型接入仍用独立的 LangChain 文件，Chroma 本地持久化。
`category` 保留参考结构默认值 Uncategorized；不会为了填字段另外引入分类器。
原始 AI 回答保留在聊天日志里，不作为用户经历写成笔记。时间流逝只移动时间字段，不计算遗忘。

没有跨版本导入。数据路径不变；旧混合版 v2 结构不能直接加载到新笔记集合。
实验问题、预期和验证状态见 [总说明](../README.md)。
