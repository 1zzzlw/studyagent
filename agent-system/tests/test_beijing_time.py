"""验证旧 UTC 数据迁移、原文保留、备份及跨日北京时间。"""
import json
import math
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from agent.common.models import BEIJING, as_beijing
from agent.infrastructure.persistence.database import Repository
from agent.systems.memory.engines.ebbinghaus import EbbinghausMemoryEngine


class BeijingTimeTests(unittest.TestCase):
    old_time = "2026-11-11T23:30:00.123456+00:00"
    original = "原话中的 2026-11-11T23:30:00+00:00 不能被改写"

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "history.sqlite3"
        db = sqlite3.connect(self.path)
        try:
            db.executescript((ROOT / "init.sql").read_text(encoding="utf-8-sig"))
            with db:
                db.execute("INSERT INTO characters VALUES ('character_xiaoyi','小忆',?)", (self.old_time,))
                db.execute("INSERT INTO conversations(conversation_id,character_id,user_id,created_at) "
                           "VALUES ('c1','character_xiaoyi','local_user',?)", (self.old_time,))
                db.execute("INSERT INTO messages(message_id,conversation_id,role,content,created_at) "
                           "VALUES ('u1','c1','user',?,?)", (self.original, self.old_time))
                db.execute("""INSERT INTO memories(node_id,character_id,conversation_id,type,description,
                              created_at,subject,predicate,object,importance)
                              VALUES ('m1','character_xiaoyi','c1','event',?,?,'用户','表示','经历',7)""",
                           (self.original, self.old_time))
                db.execute("INSERT INTO memory_retention VALUES ('m1',0.7,0.7,30,?,2,?)",
                           (self.old_time, self.old_time))
                db.execute("INSERT INTO memory_processing(memory_id) VALUES ('m1')")
                db.execute("INSERT INTO character_states VALUES ('character_xiaoyi',?)", (
                    json.dumps({"updated_at": self.old_time, "environment": self.original}),))
                db.execute("INSERT INTO events(character_id,stage,message,created_at,payload_json) "
                           "VALUES ('character_xiaoyi','context','测试',?,?)", (
                               self.old_time, json.dumps({"当前时间": self.old_time,
                               "近期原话": [{"created_at": self.old_time, "content": self.original}]})))
                db.execute("INSERT INTO runtime_settings VALUES ('offset_days','5')")
        finally:
            db.close()

    def test_legacy_data_keeps_instants_content_decay_and_backup(self):
        repo = Repository(self.path, ROOT / "init.sql")
        expected = "2026-11-12T07:30:00.123456+08:00"
        message = repo.messages("c1")[0]
        self.assertEqual(message["created_at"], expected)
        self.assertEqual(datetime.fromisoformat(message["created_at"]), datetime.fromisoformat(self.old_time))
        self.assertEqual(message["content"], self.original)
        self.assertEqual(repo.nodes()["m1"].description, self.original)
        self.assertEqual(repo.get_snapshot("character")["updated_at"], expected)
        event = repo.events(1)[0]
        self.assertEqual(event["payload"]["当前时间"], expected)
        self.assertEqual(event["payload"]["近期原话"][0]["content"], self.original)
        self.assertEqual(repo.offset_days(), 5)
        later = datetime.fromisoformat(self.old_time) + timedelta(days=30)
        self.assertAlmostEqual(EbbinghausMemoryEngine().strength(repo.retentions()["m1"], later), 0.7 * math.exp(-1))
        backups = list(self.path.parent.glob("history.before_beijing_*.sqlite3"))
        self.assertEqual(len(backups), 1)
        db = sqlite3.connect(backups[0])
        try:
            self.assertEqual(db.execute("SELECT created_at FROM messages").fetchone()[0], self.old_time)
        finally:
            db.close()
        Repository(self.path, ROOT / "init.sql")
        self.assertEqual(len(list(self.path.parent.glob("history.before_beijing_*.sqlite3"))), 1)

    def test_migration_rolls_back_on_ambiguous_naive_time(self):
        db = sqlite3.connect(self.path)
        try:
            with db:
                db.execute("UPDATE messages SET created_at='2026-11-11T23:30:00'")
        finally:
            db.close()
        with self.assertRaisesRegex(ValueError, "缺少时区"):
            Repository(self.path, ROOT / "init.sql")
        db = sqlite3.connect(self.path)
        try:
            self.assertEqual(db.execute("SELECT created_at FROM characters").fetchone()[0], self.old_time)
            self.assertIsNone(db.execute("SELECT value FROM runtime_settings WHERE key='timestamp_timezone'").fetchone())
        finally:
            db.close()

    def test_sql_defaults_and_explicit_utc_writes_use_beijing(self):
        repo = Repository(self.path, ROOT / "init.sql")
        with repo.connect() as db:
            db.execute("INSERT INTO characters(character_id,name) VALUES ('other','另一角色')")
            value = db.execute("SELECT created_at FROM characters WHERE character_id='other'").fetchone()[0]
        self.assertTrue(value.endswith("+08:00"))
        utc_time = datetime.fromisoformat(self.old_time)
        conversation = repo.create_conversation(utc_time)
        self.assertEqual(conversation["created_at"], as_beijing(utc_time).isoformat())
        self.assertEqual(as_beijing(utc_time).tzinfo, BEIJING)


if __name__ == "__main__":
    unittest.main()
