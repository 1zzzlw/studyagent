"""一次交流顺序完成；进度写入数据库，读取界面可并行观察。"""
from datetime import timedelta
import logging
from threading import Lock
from ..common.models import new_id, beijing_now
from ..infrastructure.llm.models import ROOT, ModelGateway, create_embeddings, embedding_signature, load_settings
from ..infrastructure.persistence.database import Repository, TABLES
from ..infrastructure.persistence.chroma_index import ChromaIndex
from ..systems.character_state.application.service import CharacterStateService
from ..systems.emotion.application.service import EmotionService
from ..systems.memory.application.service import MemoryService
from ..systems.dialogue.application.service import DialogueService

logger = logging.getLogger(__name__)


class BusyError(RuntimeError):
    pass


class Runtime:
    def __init__(self, repository=None, model=None, index=None):
        self.settings = load_settings() if model is None else {"llm_model": "offline", "embedding_model": "offline"}
        self.repo = repository or Repository(ROOT / "storge/sqllite/history.sqlite3", ROOT / "init.sql")
        self.model = model or ModelGateway()
        self.index = index or ChromaIndex(ROOT / "storge/chromadb", create_embeddings(), embedding_signature())
        self.state = CharacterStateService(self.repo)
        self.emotion = EmotionService(self.repo, self.model)
        self.memory = MemoryService(self.repo, self.index, self.model)
        self.dialogue = DialogueService(self.model)
        self.lock = Lock()
        self.repo.recover_turns(self.now())
        if self.repo.get_snapshot("character") is None:
            self.state.update({}, self.now())
        if self.repo.get_snapshot("emotion") is None:
            self.repo.save_snapshot("emotion", self.emotion.snapshot(self.now()).model_dump(mode="json"))

    def now(self):
        return beijing_now() + timedelta(days=self.repo.offset_days())

    def process_pending(self, conversation_id, users, is_current, commit_if_current, wake_context):
        """处理一批已落库原话；是否仍适合发言由协调层的版本校验决定。"""
        from .reply_control.planner import decide_reply
        ids = [user["message_id"] for user in users]
        leader, assistant, published = ids[-1], None, False

        def report(stage, message, payload):
            self.repo.event(stage, message, payload, self.now(), leader, conversation_id)

        def superseded():
            report("reply_superseded", "收到新消息，旧批结果不发送，等待重新判断", {"message_ids": ids})
            return {"action": "superseded"}

        with self.lock:
            self.model.observer = report
            try:
                if not is_current():
                    return superseded()
                now = self.now()
                self.repo.mark_batch(ids, leader)
                state = self.state.snapshot(now)
                emotion = self.emotion.snapshot(now)
                recent = self.repo.messages(conversation_id, 12, users[0]["id"])
                budget, window = 12000, []
                for row in reversed(recent):
                    if budget <= 0:
                        break
                    value = {key: row[key] for key in ("message_id", "role", "content", "created_at")}
                    value["content"] = value["content"][-budget:]
                    budget -= len(value["content"])
                    window.insert(0, value)
                weekdays = "一二三四五六日"
                context = {
                    "角色名": self.repo.character_name, "当前时间": now.isoformat(),
                    "当前时区": "Asia/Shanghai（北京时间，UTC+08:00）",
                    "时间说明": f"{now:%Y年%m月%d日} 星期{weekdays[now.weekday()]} {now:%H:%M:%S}，北京时间",
                    "人物状态": state.model_dump(mode="json"), "当前情绪": emotion.model_dump(mode="json"),
                    "近期原话": window,
                    "当前用户消息": [{key: user[key] for key in ("message_id", "content", "created_at")} for user in users],
                }
                report("planner_start", f"Planner 判断本批 {len(users)} 条消息", {
                    "message_ids": ids, "context": context, **wake_context})
                decision = decide_reply(self.model, {**context, **wake_context})
                if not is_current():
                    return superseded()
                self.repo.mark_batch(ids, leader, decision.action)
                report("planner_decision", "Planner 已决定：" + {
                    "reply": "回复", "wait": "等待", "skip": "本轮不回复"}[decision.action],
                    decision.model_dump(mode="json"))
                if decision.action == "wait":
                    return decision.model_dump(mode="json")

                user_text = "\n".join(user["content"] for user in users)
                recalled = self.memory.recall(user_text + "\n近期话题：" + "\n".join(
                    row["content"][:500] for row in recent[-2:]), now, report)
                if not is_current():
                    return superseded()
                appraisal, before, after = self.emotion.appraise(user_text, state, recalled, now)
                report("emotion_appraised", "本批情感评价完成，尚未提交", {
                    "before": before.model_dump(mode="json"), "after": after.model_dump(mode="json"),
                    "appraisal": appraisal.model_dump(mode="json"), "committed": False})
                if not is_current():
                    return superseded()
                attention = self.state.appraise(state, after.values.model_dump())
                report("attention", "本批注意力已评价", attention.model_dump())
                context.update({"当前情绪": after.model_dump(mode="json"), "长期回忆": recalled,
                                "本轮回复方向": decision.reply_reference})
                reply = None
                if decision.action == "reply":
                    report("context", "回复上下文已组织", context)
                    reply = self.dialogue.generate(context)
                if not is_current():
                    return superseded()

                def publish():
                    # 与新消息接收互斥：版本检查和可见回复提交之间不留竞态。
                    self.repo.save_snapshot("emotion", after.model_dump(mode="json"))
                    report("emotion_updated", "本批角色情绪已提交", {
                        "before": before.model_dump(mode="json"), "after": after.model_dump(mode="json"),
                        "appraisal": appraisal.model_dump(mode="json")})
                    value = None
                    if reply is not None:
                        value = self.repo.add_message(conversation_id, new_id("assistant"), "assistant",
                                                      reply.answer, self.now(), leader)
                        for key in ids:
                            self.repo.attach_reply(key, value["message_id"])
                        report("reply_saved", "角色回复已保存，开始整理记忆", {
                            "message": value, "used_memory_ids": reply.used_memory_ids,
                            "source_message_ids": ids})
                    else:
                        report("reply_skipped", "本批不发言，原话仍保留并整理记忆",
                               {"reason": decision.reason, "message_ids": ids})
                    return {"assistant": value}

                committed = commit_if_current(publish)
                if committed is None:
                    return superseded()
                assistant, published = committed["assistant"], True
                if reply is not None:
                    self.memory.record_usage(reply.used_memory_ids,
                                             {item["node_id"] for item in recalled}, self.now(), report)
                self.memory.remember(conversation_id, users, assistant, attention,
                                     appraisal.emotional_impact, recalled, self.now(), report)
                stage = "本批回复与记忆整理完成" if assistant else "本批无需回复，记忆整理完成"
                self.repo.finish_batch(ids, "completed", assistant["message_id"] if assistant else None,
                                       None, stage, self.now())
                report("completed", stage, {"message_ids": ids})
                return {"action": decision.action, "reason": decision.reason}
            except Exception as error:
                logger.exception("交流处理失败 turn_id=%s", leader)
                if not published and not is_current():
                    report("obsolete_error", "旧批请求失败，已有新消息将重新判断", {"error": str(error)})
                    return {"action": "superseded"}
                status = "partial" if published else "failed"
                stage = ("回复已保留，但记忆整理失败" if assistant else
                         "本批未发言，记忆整理失败" if published else "本批处理失败")
                self.repo.finish_batch(ids, status, assistant["message_id"] if assistant else None,
                                       str(error), stage, self.now())
                report(status, stage, {"error": str(error), "message_ids": ids})
                return {"action": "failed", "error": str(error)}
            finally:
                self.model.observer = None

    def turn_result(self, key):
        turn = self.repo.turn(key)
        if turn is None:
            raise KeyError("处理记录不存在")
        with self.repo.connect() as db:
            row = db.execute("SELECT * FROM messages WHERE message_id=?", (turn["assistant_message_id"],)).fetchone()
            reply = dict(row) if row else None
        return {"turn": turn, "reply": reply, "events": self.repo.events(100, key)}

    def snapshot(self):
        now = self.now()
        memories = self.memory.views(now)
        edges, seen = [], set()
        chats = {message_id: value["node_id"] for value in memories if value["type"] == "chat"
                 for message_id in value["source_message_ids"]}
        for value in memories:
            key = value["node_id"]
            for target in value["evidence_memory_ids"]:
                edges.append({"source": key, "target": target, "type": "evidence"})
            for target in value["related_memory_ids"]:
                pair = tuple(sorted([key, target]))
                if pair not in seen:
                    edges.append({"source": pair[0], "target": pair[1], "type": "related"})
                    seen.add(pair)
            if value["type"] == "event":
                for target in {chats[source] for source in value["source_message_ids"] if source in chats}:
                    edges.append({"source": key, "target": target, "type": "source"})
        return {"now": now.isoformat(), "offset_days": self.repo.offset_days(), "busy": self.lock.locked(),
                "character": self.state.snapshot(now).model_dump(mode="json"),
                "emotion": self.emotion.snapshot(now).model_dump(mode="json"),
                "memories": memories, "edges": edges, "events": self.repo.events(100),
                "turns": self.repo.recent_turns(),
                "storage": {"sqlite_path": str(self.repo.path), "chroma_path": str(self.index.path),
                            "tables": list(TABLES), **self.settings},
                "stats": {"total": len(memories),
                          **{kind: sum(value["type"] == kind for value in memories) for kind in
                             ("chat", "event", "thought")},
                          "indexed": sum(value["index_state"] == "ready" for value in memories),
                          "index_failed": sum(value["index_state"] == "failed" for value in memories)}}

    def status(self):
        """聊天页的轻量观察接口，不加载整份记忆或触发模型调用。"""
        now = self.now()
        character, emotion = self.state.snapshot(now), self.emotion.snapshot(now)
        changes = self.repo.events(1, stages=("emotion_updated", "time_advanced"))
        change = None
        if changes:
            event = changes[0]
            payload = event["payload"]
            appraisal = payload.get("appraisal", {})
            change = {"id": event["id"], "created_at": event["created_at"],
                      "message": event["message"], "reason": appraisal.get("reason", event["message"]),
                      "emotional_impact": appraisal.get("emotional_impact"),
                      "before": payload.get("before", payload.get("emotion_before")),
                      "after": payload.get("after", payload.get("emotion_after"))}
        turns = self.repo.recent_turns()
        return {"now": now.isoformat(), "busy": self.lock.locked(),
                "phase": turns[0]["stage"] if turns else "等待交流",
                "character": character.model_dump(mode="json"),
                "emotion": emotion.model_dump(mode="json"),
                "attention": self.state.appraise(character, emotion.values.model_dump()).model_dump(),
                "emotion_change": change}

    def memory_detail(self, key):
        value = next((item for item in self.memory.views(self.now()) if item["node_id"] == key), None)
        if value is None:
            raise KeyError("记忆不存在")
        with self.repo.connect() as db:
            sources = [dict(row) for row in db.execute("""SELECT m.*
                                                          FROM messages m
                                                                   JOIN memory_sources s
                                                                        ON s.message_id = m.message_id
                                                          WHERE s.memory_id = ?
                                                          ORDER BY m.id""", (key,))]
        return {"memory": value, "source_messages": sources,
                "stored_in": {"content": "SQLite.memories", "retention": "SQLite.memory_retention",
                              "source": "SQLite.memory_sources", "evidence": "SQLite.memory_evidence",
                              "related": "SQLite.memory_links",
                              "vector": "Chroma.agent_system_memories" if value[
                                                                              "type"] != "chat" else "chat 节点不向量化"}}

    def change_state(self, changes):
        if not self.lock.acquire(False):
            raise BusyError("请等待本轮完成后修改状态")
        try:
            before = self.state.snapshot(self.now())
            after = self.state.update(changes, self.now())
            self.repo.event("state_changed", "人物状态已手动更新",
                            {"before": before.model_dump(mode="json"), "after": after.model_dump(mode="json")},
                            self.now())
            return after.model_dump(mode="json")
        finally:
            self.lock.release()

    def advance(self, days):
        if not self.lock.acquire(False):
            raise BusyError("请等待本轮完成后推进时间")
        try:
            before_time = self.now()
            before = {value["node_id"]: value["current_strength"] for value in self.memory.views(before_time)}
            emotion_before = self.emotion.snapshot(before_time).model_dump(mode="json")
            self.repo.set_offset(self.repo.offset_days() + days)
            now = self.now()
            emotion_after = self.emotion.snapshot(now).model_dump(mode="json")
            self.repo.save_snapshot("emotion", emotion_after)
            changes = [{"memory_id": value["node_id"], "before": before[value["node_id"]],
                        "after": value["current_strength"], "clarity": value["clarity"]}
                       for value in self.memory.views(now)]
            self.repo.event("time_advanced", f"模拟时间推进 {days:g} 天",
                            {"days": days, "now": now.isoformat(), "memory_changes": changes,
                             "emotion_before": emotion_before, "emotion_after": emotion_after,
                             "note": "原始消息和记忆创建时间均未改写"}, now)
            return {"now": now.isoformat()}
        finally:
            self.lock.release()

    def archive(self, conversation_id):
        if not self.lock.acquire(False):
            raise BusyError("处理期间不能隐藏会话")
        try:
            self.repo.archive(conversation_id)
            return {"archived": True}
        finally:
            self.lock.release()

    def retry_index(self):
        if not self.lock.acquire(False):
            raise BusyError("请等待本轮完成后重建索引")
        try:
            nodes = [node for node in self.repo.nodes().values()
                     if node.type != "chat" and node.index_state in ("pending", "failed")]

            def report(stage, message, payload):
                self.repo.event(stage, message, payload, self.now())

            self.memory.index_nodes(nodes, report)
            return {"count": len(nodes)}
        finally:
            self.lock.release()
