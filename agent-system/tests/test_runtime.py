"""只在临时目录验证存储和编排，不请求真实文字或向量模型。"""
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient
from agent.api import create_app
from agent.application.runtime import Runtime, BusyError
from agent.application.reply_control.coordinator import ReplyCoordinator
from agent.infrastructure.persistence.database import Repository
from agent.infrastructure.llm.models import parse_object
from agent.systems.dialogue.domain.models import DialogueReply


class OfflineModel:
    """按服务提供的 JSON 契约输出，记录调用次序与实际上下文。"""
    observer = None

    def __init__(self):
        self.calls = []
        self.fail_at = None

    def ask(self, output_type, instructions, context, purpose):
        self.calls.append((purpose, context))
        if purpose == self.fail_at:
            raise RuntimeError("offline model failure")
        if purpose == "reply_planner":
            value = {"action": "reply", "reason": "用户已经表达完整", "reply_reference": "自然接话"}
        elif purpose == "emotion":
            value = {"reaction": {"joy": 0.8, "trust": 0.7},
                     "emotional_impact": 0.5, "reason": "测试一次正向反应"}
        elif purpose == "dialogue":
            memories = context["长期回忆"]
            value = {"answer": "收到，我会结合你说的情况来聊。",
                     "used_memory_ids": [memories[0]["node_id"]] if memories else []}
        elif purpose == "memory_formation":
            neighbors = context["候选邻居"]
            related = [neighbors[0]["node_id"]] if neighbors else []
            value = {"events": [{"description": context["实际用户原话"], "subject": "用户",
                                 "predicate": "表示", "object": "阅读经历", "importance": 8,
                                 "keywords": ["阅读"], "context": "用户真实交流", "tags": ["偏好"],
                                 "category": "阅读", "related_memory_ids": related}],
                     "neighbor_updates": [{"node_id": related[0], "context": "又一次谈到阅读",
                                           "tags": ["阅读", "多次交流"]}] if related else []}
        elif purpose == "reflection":
            evidence = [node["node_id"] for node in context["候选经历"]][:2]
            value = {"thoughts": [{"description": "用户可能喜欢通过阅读放松，仍需后续了解。",
                                    "evidence_memory_ids": evidence, "keywords": ["阅读"],
                                    "importance": 7}]}
        else:
            raise AssertionError(purpose)
        return output_type.model_validate(value)


class OfflineIndex:
    """只检查记忆 ID 和更新传播；不把替代检索当作语义质量证据。"""
    def __init__(self, path):
        self.path = path
        self.nodes = {}
        self.fail = False

    def upsert(self, nodes):
        if self.fail:
            raise RuntimeError("offline embedding failure")
        self.nodes.update((node.node_id, node) for node in nodes)

    def search(self, query, character_id, limit=20):
        return [(key, 0.8) for key, node in self.nodes.items()
                if node.character_id == character_id][:limit]

    def info(self):
        return {"count": len(self.nodes), "path": str(self.path)}


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        path = Path(self.temp.name)
        self.repo = Repository(path / "history.sqlite3", ROOT / "init.sql")
        self.model = OfflineModel()
        self.index = OfflineIndex(path / "chroma")
        self.runtime = Runtime(self.repo, self.model, self.index)
        self.sender = ReplyCoordinator(self.runtime)
        self.conversation = self.repo.create_conversation(self.runtime.now())["conversation_id"]

    def send(self, index, text=None):
        return self.send_to(self.conversation, f"user_{index}", text or f"我第{index}次去图书馆看书了。")

    def send_to(self, conversation, key, text):
        self.sender.submit(conversation, key, text)
        pending = self.repo.pending_messages(conversation)
        if pending:
            self.runtime.process_pending(conversation, pending, lambda: True, lambda action: action(),
                                         {"唤醒原因": "new_messages"})
        return self.runtime.turn_result(key)

    def test_full_turns_sources_association_reflection_and_actual_recall(self):
        for index in range(1, 4):
            result = self.send(index)
            self.assertEqual(result["turn"]["status"], "completed", result)
        self.assertEqual(len(self.repo.messages(self.conversation)), 6)
        nodes = self.repo.nodes()
        counts = Counter(node.type for node in nodes.values())
        self.assertEqual(counts, {"chat": 3, "event": 3, "thought": 1})
        thought = next(node for node in nodes.values() if node.type == "thought")
        self.assertEqual(len(thought.evidence_memory_ids), 2)
        self.assertEqual(len(thought.source_message_ids), 2)
        for event in (node for node in nodes.values() if node.type == "event"):
            self.assertTrue(event.source_message_ids[0].startswith("user_"))
            self.assertNotIn("attention", event.model_dump())
            self.assertNotIn("emotional_impact", event.model_dump())
        self.assertTrue(any(node.related_memory_ids for node in nodes.values()))
        self.assertEqual(sum(state.recall_count for state in self.repo.retentions().values()), 2)
        self.assertEqual(Counter(purpose for purpose, _ in self.model.calls),
                         {"reply_planner": 3, "emotion": 3, "dialogue": 3, "memory_formation": 3, "reflection": 1})
        snapshot = self.runtime.snapshot()
        self.assertEqual({edge["type"] for edge in snapshot["edges"]}, {"source", "evidence", "related"})
        detail = self.runtime.memory_detail(thought.node_id)
        self.assertEqual(len(detail["source_messages"]), 2)
        with self.repo.connect() as db:
            self.assertEqual(db.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_idempotent_message_and_no_reuse_with_other_content(self):
        first = self.send(1)
        calls = len(self.model.calls)
        repeated = self.send(1)
        self.assertEqual(repeated["reply"], first["reply"])
        self.assertEqual(len(self.model.calls), calls)
        self.assertEqual(len(self.repo.messages(self.conversation)), 2)
        with self.assertRaises(ValueError):
            self.send(1, "同一个 ID 被换成不同正文")

    def test_time_decay_emotion_recovery_and_history_unchanged(self):
        self.send(1)
        before = self.runtime.snapshot()
        history = self.repo.messages(self.conversation)
        self.runtime.advance(60)
        after = self.runtime.snapshot()
        self.assertLess(after["memories"][1]["current_strength"], before["memories"][1]["current_strength"])
        self.assertEqual(history, self.repo.messages(self.conversation))
        self.assertEqual(after["offset_days"], 60)
        self.assertAlmostEqual(after["emotion"]["values"]["joy"], 0.1)
        self.assertIn("memory_changes", self.repo.events(1)[0]["payload"])
        reopened = Repository(self.repo.path, ROOT / "init.sql")
        self.assertEqual(reopened.offset_days(), 60)
        self.assertEqual(len(reopened.nodes()), 2)

    def test_state_changes_attention_and_recent_window_is_conversation_local(self):
        now = self.runtime.now()
        original = self.runtime.state.snapshot(now)
        lower = self.runtime.change_state({"energy": 0.1, "busyness": 0.9})
        altered = self.runtime.state.snapshot(now)
        emotions = {"fear": 0.1, "sadness": 0.1}
        self.assertLess(self.runtime.state.appraise(altered, emotions).attention,
                        self.runtime.state.appraise(original, emotions).attention)
        self.assertEqual(lower["energy"], 0.1)
        self.send(1)
        another = self.repo.create_conversation(now)["conversation_id"]
        self.send_to(another, "other_user", "你好")
        dialogue = [context for purpose, context in self.model.calls if purpose == "dialogue"][-1]
        self.assertEqual(dialogue["近期原话"], [])
        self.runtime.archive(self.conversation)
        self.assertEqual(len(self.repo.conversations()), 1)
        self.assertEqual(len(self.repo.messages(self.conversation)), 2)

    def test_index_failure_preserves_answer_and_can_retry(self):
        self.index.fail = True
        result = self.send(1)
        self.assertEqual(result["turn"]["status"], "partial")
        self.assertIsNotNone(result["reply"])
        self.assertEqual(len(self.repo.messages(self.conversation)), 2)
        node = next(node for node in self.repo.nodes().values() if node.type == "event")
        self.assertEqual(node.index_state, "failed")
        self.index.fail = False
        self.assertEqual(self.runtime.retry_index()["count"], 1)
        self.assertEqual(self.repo.nodes()[node.node_id].index_state, "ready")

    def test_pre_answer_failure_and_busy_mutations(self):
        self.model.fail_at = "dialogue"
        result = self.send(1)
        self.assertEqual(result["turn"]["status"], "failed")
        self.assertIsNone(result["reply"])
        self.assertEqual(len(self.repo.messages(self.conversation)), 1)
        self.runtime.lock.acquire()
        try:
            with self.assertRaises(BusyError):
                self.runtime.archive(self.conversation)
            with self.assertRaises(BusyError):
                self.runtime.advance(1)
        finally:
            self.runtime.lock.release()

    def test_api_validation_detail_and_safe_table_browser(self):
        import time
        with TestClient(create_app(self.runtime, quiet_seconds=0.01)) as client:
            self.assertEqual(client.get("/api/health").status_code, 200)
            result = client.post(f"/api/conversations/{self.conversation}/messages",
                                 json={"message_id": "api_1", "content": "我喜欢阅读"})
            self.assertEqual(result.status_code, 202)
            self.assertIn("active", client.get(f"/api/conversations/{self.conversation}/activity").json())
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                if client.get("/api/turns/api_1?summary=true").json()["status"] != "running":
                    break
                time.sleep(0.01)
            summary = client.get("/api/turns/api_1?summary=true").json()
            self.assertEqual(summary["status"], "completed", summary)
            self.assertEqual(summary["stage"], "本批回复与记忆整理完成")
            self.assertNotIn("events", summary)
            self.assertEqual(client.get("/api/storage/tables/messages").json()["count"], 2)
            self.assertEqual(client.get("/api/storage/tables/not_allowed").status_code, 404)
            self.assertEqual(client.post("/api/time/advance", json={"days": -1}).status_code, 422)
            self.assertEqual(client.get("/api/snapshot").json()["stats"]["event"], 1)
            calls_before = len(self.model.calls)
            status = client.get("/api/status").json()
            self.assertIn("attention", status)
            self.assertEqual(status["character"]["energy"], 0.7)
            self.assertEqual(status["emotion_change"]["reason"], "测试一次正向反应")
            self.assertIn("before", status["emotion_change"])
            self.assertEqual(len(self.model.calls), calls_before)

    def test_json_prefix_fence_and_invalid_result(self):
        reply = parse_object('answered\n```json\n{"answer":"你好","used_memory_ids":[]}\n```', DialogueReply)
        self.assertEqual(reply.answer, "你好")
        with self.assertRaises(ValueError):
            parse_object('{"answer":"你好"} another answer', DialogueReply)


if __name__ == "__main__":
    unittest.main()
