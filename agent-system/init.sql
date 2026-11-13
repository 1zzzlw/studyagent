-- 四系统初版：历史、长期记忆、人物状态、情绪与运行记录。
--
-- 当前范围：一位用户与一个角色的单聊；不同角色、不同会话分别隔离。
-- 当前消息类型：用户文字原话、角色实际回复。
-- 建议数据库文件：agent-system/storge/sqllite/history.sqlite3。
--
-- 短期窗口从 messages 读取，不复制建表；长期记忆的正文与关系保存在本库。
-- Chroma 保存长期记忆的向量索引，通过 node_id 回到本库读取结构与强度。
--
-- 时间统一保存为北京时间 ISO 8601 文本，例如 2026-11-11T16:30:00.000+08:00。
-- 应用显式传入带时区时间；省略时使用固定 UTC+08:00，不依赖系统 localtime。
-- 窗口及分页按数据库 id 排序，避免时间相同或输入时间不单调造成排序歧义。
--
-- 可重复执行：不会清空已有数据；但 IF NOT EXISTS 不会升级既有表结构。
-- 后续修改已经投入使用的表时，应另外编写迁移。
--
-- foreign_keys、busy_timeout 为连接级设置：应用每次新建连接也需要设置。
-- foreign_keys 要在事务开始前开启。
PRAGMA foreign_keys = ON;
PRAGMA busy_timeout = 5000;
PRAGMA journal_mode = WAL;

BEGIN IMMEDIATE;

-- 1. 角色标识：只保存历史归属需要的基本信息。
-- 精力、活动、情绪等业务状态不放在这张表中。
CREATE TABLE IF NOT EXISTS characters (
    character_id TEXT NOT NULL PRIMARY KEY
        CHECK (length(trim(character_id)) > 0),
    name TEXT NOT NULL
        CHECK (length(trim(name)) > 0),
    created_at TEXT NOT NULL
        DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now', '+8 hours') || '+08:00')
);

-- 2. 会话：绑定一个角色与一位用户。
-- user_id 是应用提供的稳定用户标识，当前不设计账号、登录或群聊表。
-- 发送者可由 role + 本表的 user_id / character_id 确定。
CREATE TABLE IF NOT EXISTS conversations (
    conversation_id TEXT NOT NULL PRIMARY KEY
        CHECK (length(trim(conversation_id)) > 0),
    character_id TEXT NOT NULL,
    user_id TEXT NOT NULL
        CHECK (length(trim(user_id)) > 0),
    title TEXT NOT NULL DEFAULT '',
    is_archived INTEGER NOT NULL DEFAULT 0 CHECK (is_archived IN (0, 1)),
    created_at TEXT NOT NULL
        DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now', '+8 hours') || '+08:00'),

    FOREIGN KEY (character_id) REFERENCES characters(character_id)
        ON DELETE RESTRICT
        ON UPDATE RESTRICT
);

-- 查找某个角色与用户之间的会话，也覆盖 character_id 外键查询。
CREATE INDEX IF NOT EXISTS idx_conversations_character_user
    ON conversations(character_id, user_id, created_at DESC);

-- 3. 消息：一行保存一条实际发言，不把一整轮拼成一个 JSON 字段。
CREATE TABLE IF NOT EXISTS messages (
    -- 数据库内部顺序号。AUTOINCREMENT 防止已提交的旧序号被重新使用。
    -- 供滑动窗口、历史分页和增量读取使用；不要手动赋值。
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- 应用生成的稳定 ID，例如 UUID；未来长期记忆用它引用原话。
    -- 重试保存同一条消息时复用 ID，避免产生重复记录。
    message_id TEXT NOT NULL UNIQUE
        CHECK (length(trim(message_id)) > 0),

    conversation_id TEXT NOT NULL,

    -- 只存实际交流；系统提示词、工具结果、内部反思不伪装成用户发言。
    role TEXT NOT NULL
        CHECK (role IN ('user', 'assistant')),

    -- 保存原文，应用写入时不根据情绪或记忆强度改写内容。
    -- 初版只支持非空文字；后续多模态消息需要显式扩展结构。
    content TEXT NOT NULL
        CHECK (length(content) > 0),

    created_at TEXT NOT NULL
        DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now', '+8 hours') || '+08:00'),

    -- 回复或引用哪条消息。可为空，允许普通发言与未来主动发言。
    reply_to_message_id TEXT,

    -- 给下面的复合外键提供唯一父键，保证回复目标属于同一会话。
    UNIQUE (conversation_id, message_id),

    FOREIGN KEY (conversation_id) REFERENCES conversations(conversation_id)
        ON DELETE RESTRICT
        ON UPDATE RESTRICT,

    FOREIGN KEY (conversation_id, reply_to_message_id)
        REFERENCES messages(conversation_id, message_id)
        ON DELETE RESTRICT
        ON UPDATE RESTRICT,

    CHECK (reply_to_message_id IS NULL OR reply_to_message_id <> message_id)
);

-- 按会话读取最近 N 条、按游标翻页。id 是全库顺序号，不是会话内条数。
CREATE INDEX IF NOT EXISTS idx_messages_conversation_id
    ON messages(conversation_id, id DESC);

-- 查找一条消息的回复，同时支持回复目标的外键依赖查询。
CREATE INDEX IF NOT EXISTS idx_messages_reply_target
    ON messages(conversation_id, reply_to_message_id);

-- 以下为四系统初版的长期记忆、快照和可观察运行记录。
-- 记忆正文不保存 attention / emotional_impact；形成时评价可在 events 追溯。
CREATE TABLE IF NOT EXISTS memories (
    node_id TEXT PRIMARY KEY NOT NULL,
    character_id TEXT NOT NULL REFERENCES characters(character_id),
    conversation_id TEXT NOT NULL REFERENCES conversations(conversation_id),
    type TEXT NOT NULL CHECK (type IN ('chat', 'event', 'thought')),
    description TEXT NOT NULL CHECK (length(description) > 0),
    created_at TEXT NOT NULL,
    expires_at TEXT,
    validity TEXT NOT NULL DEFAULT 'active' CHECK (validity IN ('active', 'superseded')),
    supersedes_id TEXT REFERENCES memories(node_id),
    subject TEXT NOT NULL,
    predicate TEXT NOT NULL,
    object TEXT NOT NULL,
    importance REAL NOT NULL CHECK (importance BETWEEN 1 AND 10),
    depth INTEGER NOT NULL DEFAULT 0 CHECK (depth >= 0),
    keywords_json TEXT NOT NULL DEFAULT '[]',
    context TEXT NOT NULL DEFAULT '',
    tags_json TEXT NOT NULL DEFAULT '[]',
    category TEXT NOT NULL DEFAULT '',
    index_state TEXT NOT NULL DEFAULT 'pending'
        CHECK (index_state IN ('none', 'pending', 'ready', 'failed'))
);
CREATE INDEX IF NOT EXISTS idx_memories_character ON memories(character_id, created_at);

CREATE TABLE IF NOT EXISTS memory_sources (
    memory_id TEXT NOT NULL REFERENCES memories(node_id),
    message_id TEXT NOT NULL REFERENCES messages(message_id),
    PRIMARY KEY(memory_id, message_id)
);
CREATE INDEX IF NOT EXISTS idx_memory_sources_message ON memory_sources(message_id);

CREATE TABLE IF NOT EXISTS memory_evidence (
    memory_id TEXT NOT NULL REFERENCES memories(node_id),
    evidence_id TEXT NOT NULL REFERENCES memories(node_id),
    PRIMARY KEY(memory_id, evidence_id),
    CHECK (memory_id <> evidence_id)
);
CREATE INDEX IF NOT EXISTS idx_memory_evidence_target ON memory_evidence(evidence_id);

-- 一条普通双向关联只保存一次，按 ID 排序存入；它不等于证据。
CREATE TABLE IF NOT EXISTS memory_links (
    left_id TEXT NOT NULL REFERENCES memories(node_id),
    right_id TEXT NOT NULL REFERENCES memories(node_id),
    PRIMARY KEY(left_id, right_id),
    CHECK (left_id < right_id)
);

CREATE TABLE IF NOT EXISTS memory_retention (
    memory_id TEXT PRIMARY KEY REFERENCES memories(node_id),
    initial_strength REAL NOT NULL CHECK (initial_strength BETWEEN 0 AND 1),
    strength_after_recall REAL NOT NULL CHECK (strength_after_recall BETWEEN 0 AND 1),
    stability_days REAL NOT NULL CHECK (stability_days > 0),
    anchor_at TEXT NOT NULL,
    recall_count INTEGER NOT NULL DEFAULT 0 CHECK (recall_count >= 0),
    last_recalled_at TEXT
);
CREATE TABLE IF NOT EXISTS memory_processing (
    memory_id TEXT PRIMARY KEY REFERENCES memories(node_id),
    association_ready INTEGER NOT NULL DEFAULT 0 CHECK (association_ready IN (0,1)),
    reflected INTEGER NOT NULL DEFAULT 0 CHECK (reflected IN (0,1))
);

CREATE TABLE IF NOT EXISTS character_states (
    character_id TEXT PRIMARY KEY REFERENCES characters(character_id),
    payload_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS emotion_states (
    character_id TEXT PRIMARY KEY REFERENCES characters(character_id),
    payload_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS runtime_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS turns (
    turn_id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(conversation_id),
    user_message_id TEXT NOT NULL UNIQUE REFERENCES messages(message_id),
    assistant_message_id TEXT REFERENCES messages(message_id),
    status TEXT NOT NULL CHECK (status IN ('running','completed','partial','failed')),
    stage TEXT NOT NULL,
    reply_action TEXT,
    batch_leader_id TEXT REFERENCES turns(turn_id),
    error TEXT,
    started_at TEXT NOT NULL,
    finished_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_turns_conversation ON turns(conversation_id, started_at);

-- payload_json 记录可观察的评价结果、输入来源、字段变化和模型输出，
-- 不记录 API Key，也不索取模型隐藏的思维链。
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    turn_id TEXT REFERENCES turns(turn_id),
    conversation_id TEXT REFERENCES conversations(conversation_id),
    character_id TEXT NOT NULL REFERENCES characters(character_id),
    stage TEXT NOT NULL,
    message TEXT NOT NULL,
    created_at TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_events_turn ON events(turn_id, id);

COMMIT;

-- 应用写入顺序：
-- 1. 确保 characters 与 conversations 已存在。
-- 2. 模型调用前 INSERT 用户消息。
-- 3. 生成并实际展示回复后 INSERT assistant 消息，可关联用户 message_id。
-- 4. 记忆整理失败不回滚已经保存的实际对话。
--
-- 本脚本不插入任何示例角色、消息或长期记忆。
