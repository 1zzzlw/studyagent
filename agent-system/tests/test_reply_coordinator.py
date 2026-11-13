"""真实线程调度 + 离线模型：验证连发、等待唤醒、跳过和过时回复抑制。"""
import sys
import tempfile
import time
import unittest
from pathlib import Path
from threading import Event

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_runtime import OfflineModel, OfflineIndex, ROOT
from agent.application.runtime import Runtime
from agent.application.reply_control.coordinator import ReplyCoordinator, ConversationSchedule
from agent.infrastructure.persistence.database import Repository


class ControlledModel(OfflineModel):
    def __init__(self):
        super().__init__()
        self.decisions = []
        self.block_dialogue = False
        self.entered, self.release = Event(), Event()

    def ask(self, output_type, instructions, context, purpose):
        if purpose == "reply_planner" and self.decisions:
            self.calls.append((purpose, context))
            return output_type.model_validate(self.decisions.pop(0))
        if purpose == "dialogue" and self.block_dialogue:
            self.block_dialogue = False
            self.entered.set()
            if not self.release.wait(3):
                raise RuntimeError("测试没有及时释放模型")
        return super().ask(output_type, instructions, context, purpose)


class ReplyCoordinatorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        path = Path(self.temp.name)
        self.repo = Repository(path / "history.sqlite3", ROOT / "init.sql")
        self.model = ControlledModel()
        self.runtime = Runtime(self.repo, self.model, OfflineIndex(path / "chroma"))
        self.conversation = self.repo.create_conversation(self.runtime.now())["conversation_id"]
        self.coordinator = ReplyCoordinator(self.runtime, quiet_seconds=0.02)
        self.coordinator.start()
        self.addCleanup(self.coordinator.close)
        self.addCleanup(self.model.release.set)

    def wait_for(self, condition):
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            if condition():
                return
            time.sleep(0.005)
        self.fail("等待条件未满足")

    def submit(self, key, text):
        return self.coordinator.submit(self.conversation, key, text)

    def finished(self, key):
        return self.repo.turn(key)["status"] != "running"

    def test_continuous_messages_form_one_reply_and_keep_all_sources(self):
        self.submit("u1", "我最近很喜欢看书")
        self.submit("u1", "我最近很喜欢看书")
        self.submit("u2", "通常会去图书馆")
        self.submit("u3", "因为那里比较安静，说完了")
        self.wait_for(lambda: self.finished("u3"))
        messages = self.repo.messages(self.conversation)
        self.assertEqual([row["role"] for row in messages], ["user", "user", "user", "assistant"])
        self.assertEqual(sum(purpose == "reply_planner" for purpose, _ in self.model.calls), 1)
        assistant_ids = {self.repo.turn(key)["assistant_message_id"] for key in ("u1", "u2", "u3")}
        self.assertEqual(len(assistant_ids), 1)
        event = next(node for node in self.repo.nodes().values() if node.type == "event")
        self.assertEqual(set(event.source_message_ids), {"u1", "u2", "u3"})

    def test_wait_is_woken_by_new_message(self):
        self.model.decisions = [{"action": "wait", "reason": "用户还没说完", "wait_seconds": None},
                                {"action": "reply", "reason": "用户补充完毕", "reply_reference": "回应完整内容"}]
        self.submit("u1", "先别回，我还没说完")
        self.wait_for(lambda: self.coordinator.activity(self.conversation)["phase"] == "waiting")
        self.assertEqual(len(self.repo.messages(self.conversation)), 1)
        self.assertEqual([purpose for purpose, _ in self.model.calls], ["reply_planner"])
        self.submit("u2", "我说完了，现在可以回复")
        self.wait_for(lambda: self.finished("u2"))
        self.assertEqual(len(self.repo.messages(self.conversation)), 3)
        self.assertEqual(self.repo.turn("u1")["status"], "completed")

    def test_skip_has_no_fake_assistant_but_keeps_memory(self):
        self.model.decisions = [{"action": "skip", "reason": "用户明确不需要回答"}]
        self.submit("u1", "我喜欢阅读，记住就好，不用回")
        self.wait_for(lambda: self.finished("u1"))
        self.assertEqual(self.repo.turn("u1")["reply_action"], "skip")
        self.assertIsNone(self.repo.turn("u1")["assistant_message_id"])
        self.assertEqual([row["role"] for row in self.repo.messages(self.conversation)], ["user"])
        self.assertFalse(any(purpose == "dialogue" for purpose, _ in self.model.calls))
        self.assertTrue(any(node.type == "event" for node in self.repo.nodes().values()))

    def test_new_input_during_generation_discards_old_answer_and_emotion_commit(self):
        before = self.repo.get_snapshot("emotion")
        self.model.block_dialogue = True
        self.submit("u1", "我想跟你说一件事")
        self.assertTrue(self.model.entered.wait(2))
        self.assertEqual(self.repo.get_snapshot("emotion"), before)
        self.submit("u2", "等等，我还有一段补充")
        self.model.release.set()
        self.wait_for(lambda: self.finished("u2"))
        self.assertEqual(len(self.repo.messages(self.conversation)), 3)
        stages = [event["stage"] for event in self.repo.events(100)]
        self.assertIn("reply_superseded", stages)
        self.assertEqual(stages.count("emotion_updated"), 1)
        self.assertEqual(sum(purpose == "memory_formation" for purpose, _ in self.model.calls), 1)
        last = [context for purpose, context in self.model.calls if purpose == "dialogue"][-1]
        self.assertEqual([row["message_id"] for row in last["当前用户消息"]], ["u1", "u2"])

    def test_different_conversation_does_not_invalidate_current_reply(self):
        self.model.block_dialogue = True
        self.submit("u1", "第一个会话的问题")
        self.assertTrue(self.model.entered.wait(2))
        other = self.repo.create_conversation(self.runtime.now())["conversation_id"]
        self.coordinator.submit(other, "other_u1", "另一个会话的问题")
        self.model.release.set()
        self.wait_for(lambda: self.finished("other_u1"))
        self.assertEqual(len(self.repo.messages(self.conversation)), 2)
        self.assertEqual(len(self.repo.messages(other)), 2)

    def test_natural_debounce_has_batch_limit_and_active_start(self):
        schedule = ConversationSchedule()
        schedule.receive(0, 2)
        self.assertEqual(schedule.deadline, 2)
        for arrival in (1, 2, 3, 4, 5, 6, 7):
            schedule.receive(arrival, 2)
        self.assertEqual(schedule.deadline, 8)
        schedule.first_arrival, schedule.deadline = None, None
        schedule.receive(9, 2)
        self.assertEqual(schedule.deadline, 14)

    def test_repeated_timed_wait_parks_until_new_input(self):
        self.model.decisions = [{"action": "wait", "reason": "等补充", "wait_seconds": 1},
                                {"action": "wait", "reason": "继续等用户", "wait_seconds": 1}]
        self.submit("u1", "我还有一些要说的")
        self.wait_for(lambda: bool(self.repo.events(1, stages=("wait_parked",))))
        count = len(self.model.calls)
        time.sleep(1.05)
        self.assertEqual(len(self.model.calls), count)
        self.assertIsNone(self.coordinator.activity(self.conversation)["seconds_remaining"])


if __name__ == "__main__":
    unittest.main()
