# 技术基础设施

实现模型与存储能力，供应用初始化时传给各系统服务。

初版已实现 `llm/models.py`、`persistence/database.py` 与 `persistence/chroma_index.py`。下面的进一步拆分仍是规划；启动方式见 [运行说明](../../README.md)。

## llm 目录规划

| 文件 | 职责 |
| --- | --- |
| `models.py` | 读取明确配置，创建 LangChain 文字模型和向量模型 |
| `structured.py` | 为情感评价、记忆草稿、反思等返回结构化结果 |

第一版沿用 studyAgent 已有 LangChain 依赖和配置习惯。具体厂商由你配置，业务系统不依赖某个厂商客户端。

对话回复、情绪评价、记忆形成分别标记调用用途。回复模型的“一次调用”不会掩盖整轮实际调用量。

## persistence 目录规划

| 文件 | 职责 |
| --- | --- |
| `conversation_repository.py` | SQLite 保存实际消息，按会话读取近期窗口和历史分页 |
| `memory_repository.py` | SQLite 保存长期记忆正文、来源、证据与普通关联；初版合在 database.py |
| `retention_repository.py` | 独立 SQLite 表保存每条记忆的保留状态和处理进度；初版合在 database.py |
| `state_repository.py` | 保存人物状态快照 |
| `emotion_repository.py` | 保存情绪快照 |
| `chroma_index.py` | 向量化可检索内容，返回候选记忆 ID 与相似度 |

正文是主数据，向量索引用于查候选。只更新回忆次数、情绪或状态时，不应无条件重新向量化全部正文。

SQLite 节点及其引用在本地事务内保存；Chroma 在提交后单独更新。索引失败会标记 failed，界面可补建；两种数据库之间没有分布式事务。

## 计划数据布局

~~~text
agent-system/
├── init.sql
├── agent/              本框架代码和设计文档
└── storge/
    ├── sqllite/
    │   └── history.sqlite3    启动时初始化
    ├── chromadb/              已创建的向量索引目录
    └── 状态与情绪快照          初版统一保存在 SQLite，不另建文件目录
~~~

沿用已有目录名称，不在本次重命名。短期窗口保存在应用内存，从 SQLite 历史恢复，不额外复制一份持久化聊天数据。

本次提供 [init.sql](../../init.sql) 和 [存储设计说明](persistence/README.md)，包含三层记忆与运行记录所需表。初始化读取 agent-system 下已有 .env，不把密钥或原始配置复制进文档。
