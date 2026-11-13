"""SQLite 是正文、关联、状态、运行日志的主数据源；连接按调用创建。"""
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from ...common.models import new_id, as_beijing, beijing_now, beijing_record_times
from ...systems.memory.domain.models import MemoryNode, RetentionState
from .time_migration import migrate_beijing_time

TABLES = (
    "characters", "conversations", "messages", "memories", "memory_sources",
    "memory_evidence", "memory_links", "memory_retention", "memory_processing",
    "character_states", "emotion_states", "runtime_settings", "turns", "events",
)
NODE_COLUMNS = ("node_id", "character_id", "conversation_id", "type", "description",
                "created_at", "expires_at", "validity", "supersedes_id", "subject",
                "predicate", "object", "importance", "depth", "keywords_json",
                "context", "tags_json", "category", "index_state")


def encode(value):
    return json.dumps(value, ensure_ascii=False, default=str)


class Repository:
    character_id = "character_xiaoyi"
    character_name = "小忆"
    user_id = "local_user"

    def __init__(self, path: Path, schema: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            # 兼容上一版仅有三张历史表的初始化结果。
            columns = [row["name"] for row in db.execute("PRAGMA table_info(conversations)")]
            if columns and "is_archived" not in columns:
                db.execute("ALTER TABLE conversations ADD COLUMN is_archived INTEGER NOT NULL DEFAULT 0")
            db.executescript(schema.read_text(encoding="utf-8-sig"))
            columns = [row["name"] for row in db.execute("PRAGMA table_info(conversations)")]
            if "is_archived" not in columns:
                db.execute("ALTER TABLE conversations ADD COLUMN is_archived INTEGER NOT NULL DEFAULT 0")
            turn_columns = [row["name"] for row in db.execute("PRAGMA table_info(turns)")]
            if "reply_action" not in turn_columns:
                db.execute("ALTER TABLE turns ADD COLUMN reply_action TEXT")
            if "batch_leader_id" not in turn_columns:
                db.execute("ALTER TABLE turns ADD COLUMN batch_leader_id TEXT REFERENCES turns(turn_id)")
            db.execute("INSERT OR IGNORE INTO characters(character_id,name,created_at) VALUES (?,?,?)",
                       (self.character_id, self.character_name, beijing_now().isoformat()))
        with self.connect() as db:
            migrate_beijing_time(db, path)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA busy_timeout=5000")
        try:
            with db:
                yield db
        finally:
            db.close()

    def conversation(self, conversation_id):
        with self.connect() as db:
            row = db.execute("SELECT * FROM conversations WHERE conversation_id=? AND character_id=? AND user_id=?",
                             (conversation_id, self.character_id, self.user_id)).fetchone()
        if row is None:
            raise KeyError("会话不存在")
        return dict(row)

    def conversations(self):
        with self.connect() as db:
            rows = db.execute("""SELECT c.*,
                                        (SELECT count(*)
                                         FROM messages m
                                         WHERE m.conversation_id = c.conversation_id) AS message_count
                                 FROM conversations c
                                 WHERE character_id = ?
                                   AND user_id = ?
                                   AND is_archived = 0
                                 ORDER BY rowid DESC""", (self.character_id, self.user_id)).fetchall()
        return [dict(row) for row in rows]

    def create_conversation(self, now):
        key = new_id("conversation")
        with self.connect() as db:
            db.execute(
                "INSERT INTO conversations(conversation_id,character_id,user_id,title,created_at) VALUES (?,?,?,?,?)",
                (key, self.character_id, self.user_id, "新对话", as_beijing(now).isoformat()))
        return self.conversation(key)

    def archive(self, conversation_id):
        self.conversation(conversation_id)
        with self.connect() as db:
            db.execute("UPDATE conversations SET is_archived=1 WHERE conversation_id=?", (conversation_id,))

    def messages(self, conversation_id, limit=100, before_id=None):
        self.conversation(conversation_id)
        where, args = "conversation_id=?", [conversation_id]
        if before_id is not None:
            where += " AND id<?"
            args.append(before_id)
        with self.connect() as db:
            rows = db.execute(f"SELECT * FROM messages WHERE {where} ORDER BY id DESC LIMIT ?",
                              (*args, limit)).fetchall()
        return [dict(row) for row in reversed(rows)]

    def add_message(self, conversation_id, message_id, role, content, now, reply_to=None):
        self.conversation(conversation_id)
        with self.connect() as db:
            db.execute(
                """INSERT INTO messages(message_id, conversation_id, role, content, created_at, reply_to_message_id)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (message_id, conversation_id, role, content, as_beijing(now).isoformat(), reply_to))
            if role == "user":
                db.execute("UPDATE conversations SET title=? WHERE conversation_id=? AND title='新对话'",
                           (content.replace("\n", " ")[:22], conversation_id))
            row = db.execute("SELECT * FROM messages WHERE message_id=?", (message_id,)).fetchone()
        return dict(row)

    def get_snapshot(self, kind):
        table = {"character": "character_states", "emotion": "emotion_states"}[kind]
        with self.connect() as db:
            row = db.execute(f"SELECT payload_json FROM {table} WHERE character_id=?", (self.character_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def save_snapshot(self, kind, payload):
        table = {"character": "character_states", "emotion": "emotion_states"}[kind]
        with self.connect() as db:
            db.execute(
                f"INSERT INTO {table}(character_id,payload_json) VALUES (?,?) ON CONFLICT(character_id) DO UPDATE SET payload_json=excluded.payload_json",
                (self.character_id, encode(beijing_record_times(payload))))

    def offset_days(self):
        with self.connect() as db:
            row = db.execute("SELECT value FROM runtime_settings WHERE key='offset_days'").fetchone()
        return float(row[0]) if row else 0.0

    def set_offset(self, days):
        with self.connect() as db:
            db.execute(
                "INSERT INTO runtime_settings VALUES ('offset_days',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (str(days),))

    def nodes(self):
        with self.connect() as db:
            rows = db.execute("SELECT * FROM memories WHERE character_id=? ORDER BY rowid",
                              (self.character_id,)).fetchall()
            sources, evidence, related = {}, {}, {}
            for row in db.execute("SELECT * FROM memory_sources"):
                sources.setdefault(row["memory_id"], []).append(row["message_id"])
            for row in db.execute("SELECT * FROM memory_evidence"):
                evidence.setdefault(row["memory_id"], []).append(row["evidence_id"])
            for row in db.execute("SELECT * FROM memory_links"):
                related.setdefault(row["left_id"], []).append(row["right_id"])
                related.setdefault(row["right_id"], []).append(row["left_id"])
        result = {}
        for row in rows:
            payload = dict(row)
            payload["keywords"] = json.loads(payload.pop("keywords_json"))
            payload["tags"] = json.loads(payload.pop("tags_json"))
            key = payload["node_id"]
            payload.update(source_message_ids=sources.get(key, []),
                           evidence_memory_ids=evidence.get(key, []), related_memory_ids=related.get(key, []))
            result[key] = MemoryNode.model_validate(payload)
        return result

    def retentions(self):
        with self.connect() as db:
            rows = db.execute("SELECT * FROM memory_retention").fetchall()
        result = {}
        for row in rows:
            payload = dict(row)
            key = payload.pop("memory_id")
            result[key] = RetentionState.model_validate(payload)
        return result

    def processing(self):
        with self.connect() as db:
            return {row["memory_id"]: dict(row) for row in db.execute("SELECT * FROM memory_processing")}

    def add_memory(self, node: MemoryNode, retention: RetentionState):
        payload = node.model_dump(mode="json")
        payload["keywords_json"] = encode(payload.pop("keywords"))
        payload["tags_json"] = encode(payload.pop("tags"))
        with self.connect() as db:
            db.execute(f"INSERT INTO memories({','.join(NODE_COLUMNS)}) VALUES ({','.join('?' for _ in NODE_COLUMNS)})",
                       [payload[key] for key in NODE_COLUMNS])
            self._save_retention(db, node.node_id, retention)
            db.execute("INSERT INTO memory_processing(memory_id) VALUES (?)", (node.node_id,))
            db.executemany("INSERT INTO memory_sources VALUES (?,?)",
                           [(node.node_id, key) for key in dict.fromkeys(node.source_message_ids)])
            db.executemany("INSERT INTO memory_evidence VALUES (?,?)",
                           [(node.node_id, key) for key in dict.fromkeys(node.evidence_memory_ids)])
            for target in node.related_memory_ids:
                db.execute("INSERT OR IGNORE INTO memory_links VALUES (?,?)", sorted([node.node_id, target]))
            if node.supersedes_id:
                db.execute("UPDATE memories SET validity='superseded' WHERE node_id=?", (node.supersedes_id,))

    @staticmethod
    def _save_retention(db, key, retention):
        value = retention.model_dump(mode="json")
        columns = list(value)
        db.execute(
            f"INSERT INTO memory_retention(memory_id,{','.join(columns)}) VALUES ({','.join('?' for _ in range(len(columns) + 1))}) ON CONFLICT(memory_id) DO UPDATE SET "
            + ",".join(f"{col}=excluded.{col}" for col in columns), [key, *value.values()])

    def save_retention(self, key, retention):
        with self.connect() as db:
            self._save_retention(db, key, retention)

    def update_semantics(self, key, context, tags):
        with self.connect() as db:
            db.execute("UPDATE memories SET context=?,tags_json=?,index_state='pending' WHERE node_id=?",
                       (context, encode(tags), key))

    def index_state(self, ids, status):
        with self.connect() as db:
            db.executemany("UPDATE memories SET index_state=? WHERE node_id=?", [(status, key) for key in ids])

    def mark_processed(self, ids, field):
        if field not in ("association_ready", "reflected"):
            raise ValueError("无效的处理字段")
        with self.connect() as db:
            db.executemany(f"UPDATE memory_processing SET {field}=1 WHERE memory_id=?", [(key,) for key in ids])

    def begin_turn(self, key, conversation_id, content, now):
        """原话与处理记录一起提交，避免中途退出留下无处理记录的消息。"""
        with self.connect() as db:
            db.execute("""INSERT INTO messages(message_id,conversation_id,role,content,created_at)
                          VALUES (?,?,'user',?,?)""", (key, conversation_id, content, as_beijing(now).isoformat()))
            db.execute("UPDATE conversations SET title=? WHERE conversation_id=? AND title='新对话'",
                       (content.replace("\n", " ")[:22], conversation_id))
            db.execute("""INSERT INTO turns(turn_id, conversation_id, user_message_id, status, stage, started_at)
                          VALUES (?, ?, ?, 'running', '开始处理', ?)""",
                       (key, conversation_id, key, as_beijing(now).isoformat()))
            row = db.execute("SELECT * FROM messages WHERE message_id=?", (key,)).fetchone()
        return dict(row)

    def turn(self, key):
        with self.connect() as db:
            row = db.execute("SELECT * FROM turns WHERE turn_id=?", (key,)).fetchone()
        return dict(row) if row else None

    def pending_messages(self, conversation_id):
        with self.connect() as db:
            return [dict(row) for row in db.execute("""SELECT m.* FROM messages m
                     JOIN turns t ON t.user_message_id=m.message_id
                     WHERE m.conversation_id=? AND t.status='running'
                       AND t.assistant_message_id IS NULL ORDER BY m.id""", (conversation_id,))]

    def mark_batch(self, ids, leader, action=None):
        with self.connect() as db:
            db.executemany("UPDATE turns SET batch_leader_id=?,reply_action=? WHERE turn_id=?",
                           [(leader, action, key) for key in ids])

    def finish_batch(self, ids, status, assistant_id, error, stage, now):
        with self.connect() as db:
            db.executemany("""UPDATE turns SET status=?,assistant_message_id=?,error=?,stage=?,finished_at=?
                              WHERE turn_id=?""",
                           [(status, assistant_id, error, stage, as_beijing(now).isoformat(), key) for key in ids])

    def attach_reply(self, key, assistant_id):
        with self.connect() as db:
            db.execute("UPDATE turns SET assistant_message_id=? WHERE turn_id=?", (assistant_id, key))

    def recover_turns(self, now):
        with self.connect() as db:
            db.execute("""UPDATE turns
                          SET status=CASE WHEN assistant_message_id IS NULL THEN 'failed' ELSE 'partial' END,
                              error='服务在处理期间退出；已提交数据保留，未自动重复调用模型',
                              finished_at=?
                          WHERE status = 'running'""", (as_beijing(now).isoformat(),))

    def event(self, stage, message, payload, now, turn_id=None, conversation_id=None):
        with self.connect() as db:
            db.execute(
                "INSERT INTO events(turn_id,conversation_id,character_id,stage,message,created_at,payload_json) VALUES (?,?,?,?,?,?,?)",
                (turn_id, conversation_id, self.character_id, stage, message, as_beijing(now).isoformat(),
                 encode(beijing_record_times(payload))))
            if turn_id:
                db.execute("UPDATE turns SET stage=? WHERE turn_id=?", (message, turn_id))

    def events(self, limit=100, turn_id=None, stages=None):
        where, args = "character_id=?", [self.character_id]
        if turn_id:
            where += " AND turn_id=?"
            args.append(turn_id)
        if stages:
            where += " AND stage IN (" + ",".join("?" for _ in stages) + ")"
            args.extend(stages)
        with self.connect() as db:
            rows = db.execute(f"SELECT * FROM events WHERE {where} ORDER BY id DESC LIMIT ?", (*args, limit)).fetchall()
        result = []
        for row in rows:
            value = dict(row)
            value["payload"] = json.loads(value.pop("payload_json"))
            result.append(value)
        return result

    def recent_turns(self, conversation_id=None):
        with self.connect() as db:
            where = "WHERE conversation_id=?" if conversation_id else ""
            return [dict(row) for row in db.execute(f"SELECT * FROM turns {where} ORDER BY rowid DESC LIMIT 20",
                                                   (conversation_id,) if conversation_id else ())]

    def table(self, name, limit=30, offset=0):
        if name not in TABLES:
            raise KeyError("不允许查询该表")
        with self.connect() as db:
            rows = [dict(row) for row in
                    db.execute(f'SELECT * FROM "{name}" ORDER BY rowid DESC LIMIT ? OFFSET ?', (limit, offset))]
            count = db.execute(f'SELECT count(*) FROM "{name}"').fetchone()[0]
            schema = db.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone()[0]
        return {"name": name, "rows": rows, "count": count, "schema": schema}
