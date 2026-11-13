"""参考 MaiBot 私聊：固定防抖 → Planner → reply / wait / 不发言。

接收消息不等待模型；一个工作线程串行处理角色行为。新输入只取消过时结果的发送，
不会声称已经中断远端同步模型请求。
"""
import logging
import time
from dataclasses import dataclass, field
from threading import Condition, Thread
from ..runtime import BusyError

logger = logging.getLogger(__name__)


@dataclass
class ConversationSchedule:
    revision: int = 0
    first_arrival: float | None = None
    last_arrival: float | None = None
    deadline: float | None = None
    phase: str = "idle"
    decision: dict = field(default_factory=dict)
    wake_reason: str = "new_messages"
    timeout_rechecks: int = 0
    leader: str | None = None

    def receive(self, now, quiet):
        # natural 档：安静开批 2s、活跃开批 5s、同人续发 2s、整批最多 8s。
        if self.first_arrival is None:
            self.first_arrival = now
            wait = quiet * 2.5 if self.last_arrival is not None and now - self.last_arrival <= 30 else quiet
            self.deadline = now + wait
        elif self.deadline > now:
            self.deadline = min(now + quiet, self.first_arrival + quiet * 4)
        self.last_arrival = now
        self.revision += 1
        self.phase, self.wake_reason, self.timeout_rechecks = "collecting", "new_messages", 0


class ReplyCoordinator:
    def __init__(self, runtime, quiet_seconds=2.0):
        self.runtime, self.quiet_seconds = runtime, quiet_seconds
        self.condition = Condition()
        self.schedules = {}
        self.closed = False
        self.thread = Thread(target=self._run, name="reply-coordinator", daemon=True)

    def start(self):
        self.thread.start()

    def close(self):
        with self.condition:
            self.closed = True
            self.condition.notify_all()
        self.thread.join(timeout=1)

    def submit(self, conversation_id, message_id, content):
        self.runtime.repo.conversation(conversation_id)
        with self.condition:
            if self.closed:
                raise BusyError("服务正在停止，请稍后重新发送")
            existing = self.runtime.repo.turn(message_id)
            if existing:
                with self.runtime.repo.connect() as db:
                    old = db.execute("SELECT content FROM messages WHERE message_id=?", (message_id,)).fetchone()
                if existing["conversation_id"] != conversation_id or old["content"] != content:
                    raise ValueError("同一消息 ID 不能提交不同会话或正文")
                return self.runtime.turn_result(message_id)

            self.runtime.repo.begin_turn(message_id, conversation_id, content, self.runtime.now())
            schedule = self.schedules.setdefault(conversation_id, ConversationSchedule())
            schedule.receive(time.monotonic(), self.quiet_seconds)

            self.runtime.repo.event("message_buffered", "原话已保存，等待本批输入收齐", {
                "message_id": message_id, "revision": schedule.revision,
                "quiet_seconds": round(max(0, schedule.deadline - time.monotonic()), 2)},
                                    self.runtime.now(), message_id, conversation_id)

            self.condition.notify_all()
            return self.runtime.turn_result(message_id)

    def activity(self, conversation_id):
        self.runtime.repo.conversation(conversation_id)
        with self.condition:
            schedule = self.schedules.get(conversation_id, ConversationSchedule())
            pending = self.runtime.repo.pending_messages(conversation_id)
            turns = self.runtime.repo.recent_turns(conversation_id)
            latest = turns[0] if turns else None
            leader = self.runtime.repo.turn(schedule.leader) if schedule.leader else latest
            phase = schedule.phase
            if phase == "collecting":
                progress = f"正在等你说完，本批已收到 {len(pending)} 条消息"
            elif phase == "waiting":
                progress = "Planner 决定等待：" + schedule.decision.get("reason", "等待新消息")
            elif phase == "idle" and schedule.decision.get("action") == "skip":
                progress = "本批不回复：" + schedule.decision.get("reason", "本轮无需发言")
            else:
                progress = leader["stage"] if leader else "等待交流"
            messages = self.runtime.repo.messages(conversation_id, 1)
            return {"phase": phase, "active": phase in ("collecting", "processing", "waiting"),
                    "progress": progress, "pending_count": len(pending),
                    "seconds_remaining": None if schedule.deadline is None else round(
                        max(0, schedule.deadline - time.monotonic()), 1),
                    "decision": schedule.decision, "last_turn": latest,
                    "last_message_id": messages[-1]["message_id"] if messages else None}

    def _run(self):
        while True:
            with self.condition:
                while not self.closed:
                    due = [(state.deadline, key) for key, state in self.schedules.items()
                           if state.deadline is not None]
                    if not due:
                        self.condition.wait()
                        continue
                    deadline, conversation_id = min(due)
                    remaining = deadline - time.monotonic()
                    if remaining > 0:
                        self.condition.wait(timeout=remaining)
                        continue
                    schedule = self.schedules[conversation_id]
                    users = self.runtime.repo.pending_messages(conversation_id)
                    schedule.first_arrival, schedule.deadline = None, None
                    if not users:
                        schedule.phase = "idle"
                        continue
                    revision = schedule.revision
                    schedule.phase, schedule.leader = "processing", users[-1]["message_id"]
                    wake_context = {"唤醒原因": schedule.wake_reason, "上次决策": schedule.decision}
                    break
                if self.closed:
                    return

            def is_current():
                with self.condition:
                    return not self.closed and self.schedules[conversation_id].revision == revision

            def commit_if_current(action):
                with self.condition:
                    return action() if is_current() else None

            try:
                result = self.runtime.process_pending(conversation_id, users, is_current,
                                                      commit_if_current, wake_context)
            except Exception as error:
                logger.exception("回复协调层处理失败 conversation_id=%s", conversation_id)
                self.runtime.repo.finish_batch([user["message_id"] for user in users], "failed", None,
                                               str(error), "回复协调层处理失败", self.runtime.now())
                result = {"action": "failed", "error": str(error)}
            with self.condition:
                schedule = self.schedules[conversation_id]
                if schedule.revision != revision:
                    continue
                action = result["action"]
                if action == "wait":
                    schedule.decision, schedule.phase = result, "waiting"
                    seconds = result.get("wait_seconds")
                    # 同一批最多超时复判一次，之后等待新消息，避免无人聊天时反复请求。
                    if seconds is not None and schedule.timeout_rechecks < 1:
                        schedule.deadline = time.monotonic() + seconds
                        schedule.wake_reason = "wait_timeout"
                        schedule.timeout_rechecks += 1
                    elif seconds is not None:
                        self.runtime.repo.event("wait_parked", "已超时复判一次，继续等待新消息唤醒", result,
                                                self.runtime.now(), users[-1]["message_id"], conversation_id)
                else:
                    schedule.phase = "failed" if action == "failed" else "idle"
                    schedule.decision = result
