# 三层记忆与历史数据库

初版已实现 SQLite 主数据与 Chroma 索引：[运行说明](../../../README.md)。[init.sql](../../../init.sql) 包含完整历史、长期记忆、来源、证据、关联、保留状态、人物/情绪快照和运行日志。以下历史表说明及设计建议保留作参考。

## 1. 三层按职责划分

| 层 | 内容 | 初版存放位置 |
| --- | --- | --- |
| 完整历史记录 | 用户与角色实际说过的全部文字，保持来源与顺序 | SQLite 的 messages |
| 短期记忆 / 工作上下文 | 本轮选出的近期消息及其顺序 | 应用内的 Message 列表或 ShortTermContext，从历史重建 |
| 长期记忆 | 提炼的事件、反思、关联、证据和保留状态 | 建议 SQLite 保存主数据，Chroma 保存向量索引 |

三层不要求对应三套独立数据库。历史记录是交流档案，短期窗口是本轮的工作视图，长期记忆是整理后的内容。

## 2. 历史记录层的三张基础表

~~~mermaid
erDiagram
    characters ||--o{ conversations : owns
    conversations ||--o{ messages : contains

    characters {
        TEXT character_id PK
        TEXT name
        TEXT created_at
    }

    conversations {
        TEXT conversation_id PK
        TEXT character_id FK
        TEXT user_id
        TEXT title
        TEXT created_at
    }

    messages {
        INTEGER id PK
        TEXT message_id UK
        TEXT conversation_id FK
        TEXT role
        TEXT content
        TEXT created_at
        TEXT reply_to_message_id FK
    }
~~~

这是一个用户与一个角色单聊的初版。user_id 来自应用，不在这里扩展账号或群聊系统。

- `characters`：确定历史属于哪个角色，不混入精力和情绪状态。
- `conversations`：把用户与角色的一次持续会话绑定起来。
- `messages`：一条实际发言对应一行，用户和角色分开记录。
- `reply_to_message_id`：可关联具体被回复消息，数据库限制其属于同一会话。
- 所有时间统一写入北京时间 ISO 8601（+08:00）；旧时间在先备份后转换时区表示，实际时间点不变。模拟时间推进或遗忘不改写历史时间。

`role=user` 的发送者由会话的 user_id 确定，`role=assistant` 的发送者由会话的 character_id 确定。读取公共 Message 时可补出 speaker_id。

## 3. 两种 ID 不要混淆

| 字段 | 用途 |
| --- | --- |
| `messages.id` | SQLite 内部递增顺序，用于窗口、分页和增量游标 |
| `messages.message_id` | 应用提供的稳定消息 ID，用于跨系统引用原话 |

记忆的 `source_message_ids` 应引用 message_id，不引用当前窗口中的第几条。

messages 同时有全局 message_id 唯一约束和 `(conversation_id, message_id)` 唯一约束。后者用于复合外键，确保引用消息没有跨到其他会话。

## 4. 短期记忆先用滑动窗口

第一版可直接复用 Message 结构：

~~~text
ShortTermContext
    conversation_id
    recent_messages: list[Message]
~~~

不必把窗口中的消息再复制成一张短期记忆表。重启后可以从历史数据库重新读取。

最近 N 条的示意查询：

~~~sql
SELECT id, message_id, role, content, created_at, reply_to_message_id
FROM (
    SELECT id, message_id, role, content, created_at, reply_to_message_id
    FROM messages
    WHERE conversation_id = :conversation_id
    ORDER BY id DESC
    LIMIT :message_limit
) AS recent
ORDER BY id ASC;
~~~

内层先取最近消息，外层恢复正常阅读顺序。这里 N 计算的是消息条数，并不是对话轮数。

如果当前用户消息已经写入数据库，并且还会单独作为本轮输入传给模型，窗口查询需要加上：

~~~sql
AND id < :current_user_message_row_id
~~~

这行放在内层 WHERE 条件中，避免当前用户消息在提示词里出现两次。

窗口滑出只代表本轮不再提供，不删除历史，也不等于自动提升为长期记忆。是否形成长期记忆，由记忆形成流程单独判断。

实际接入长消息时，还应限制 token 预算：最近 10 条可能包含几万字，固定条数不是严格的模型上下文上限。

## 5. 历史消息分页

例如向前翻页：

~~~sql
SELECT id, message_id, role, content, created_at, reply_to_message_id
FROM messages
WHERE conversation_id = :conversation_id
  AND id < :oldest_loaded_id
ORDER BY id DESC
LIMIT :page_size;
~~~

显示前在应用中反转结果。第一次加载可省略游标条件。

使用命名参数绑定，禁止把用户输入直接拼进 SQL。后续仓库实现负责确认会话属于当前用户与角色，再读取消息。

## 6. 长期记忆为什么建议也把主数据放 SQLite

Chroma 可以同时保存正文和元数据，并不是只能保存向量。但对本项目，长期记忆还有：

- 记忆之间的反思证据与普通关联。
- 指向原始消息的来源。
- 强度、稳定性、实际回忆次数等独立更新的数据。
- 纠正、失效、时间及处理进度。

建议将这些主数据放在同一个 SQLite 文件的独立表中，并在 Chroma 中按 memory_id 建立索引。后续可以直接建立长期记忆表与 messages 的外键或映射表；历史消息和长期记忆仍保持不同的数据结构。

~~~text
查询文本
    ↓
Chroma 返回相关 memory_id
    ↓
SQLite 读取有效正文、来源、证据和保留状态
    ↓
组织本轮 RecallItem
~~~

只更新回忆次数或保留强度时，不需要重新生成正文向量。正文或用于嵌入的语义描述变化时，再更新对应向量。

init.sql 已创建长期记忆、来源、证据、关联、保留状态和处理进度表；具体对应关系见 [运行说明](../../../README.md)。领域对象与数据库表并非一一对应。

## 7. 写入与失败处理

应用实现时建议：

1. 注册或读取角色与会话。
2. 保存用户的真实消息。
3. 调用状态、情感、记忆与对话流程。
4. 得到实际回复后，保存 assistant 消息。
5. 再整理记忆与登记强化。

不要在等待整个模型请求的期间一直持有数据库写事务。回复失败时，用户消息仍然应保留；不要伪造一条成功的 assistant 消息。

SQL 使用 RESTRICT 保护仍有依赖的数据。原话按追加方式使用，强度衰减和窗口变化不修改原话正文。当前没有开发消息编辑、删除或其证据失效传播功能。

## 8. 初始化方式

后端启动会自动初始化。在 `E:\AgentProject\studyAgent` 目录下，如需单独初始化也可执行：

~~~powershell
@'
import sqlite3
from pathlib import Path

project = Path("agent-system")
db_path = project / "storge" / "sqllite" / "history.sqlite3"
db_path.parent.mkdir(parents=True, exist_ok=True)

connection = sqlite3.connect(db_path)
try:
    connection.executescript((project / "init.sql").read_text(encoding="utf-8-sig"))
finally:
    connection.close()

print(db_path.resolve())
'@ | .\.venv\Scripts\python.exe -
~~~

这里沿用你已经创建的 `storge/sqllite` 目录名称，没有重命名。

应用每次新建 SQLite 连接，还需要在事务之外执行：

~~~sql
PRAGMA foreign_keys = ON;
PRAGMA busy_timeout = 5000;
~~~

外键开关是连接级设置，不能以为初始化文件执行一次，所有后续连接就自动开启。[SQLite 外键说明](https://www.sqlite.org/foreignkeys.html)

初始化脚本选择 WAL，便于本地读写协作；它仍然不是多个写事务无限并行的机制。[SQLite WAL 说明](https://www.sqlite.org/wal.html)

重复执行 init.sql 不清空数据，但也不会迁移旧表。已经有正式数据后若修改结构，应编写迁移。
