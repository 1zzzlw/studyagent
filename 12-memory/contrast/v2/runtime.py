"""纯 A-Mem 聊天适配：检索笔记 -> 回答 -> 分析新笔记 -> 演化 -> 存储。"""
import json
import os
from datetime import timedelta
from threading import RLock
from uuid import uuid4

from .association import analyze_content, process_memory
from .models import MemoryNote, RecallReply
from .strategy import retrieve


ANSWER_INSTRUCTIONS = (
    "你是与用户自然交流的小忆。根据本轮输入和提供的记忆笔记回答。"
    "content 是用户原文，context/keywords/tags 是语义辅助，不能覆盖正文。"
    "只有实际使用了笔记才返回 recalled，并在 used_memory_ids 列出笔记的 id。"
    "普通交流返回 answered，缺少依据返回 not_recalled，记忆互相矛盾或分不清则 uncertain；后三者 ID 为空。"
    "不编造未提供的事实，保留提问、邀请、条件、猜测、承诺与完成的区别。"
    "时间词相对笔记 timestamp 理解；时间经过本身不代表事情已经完成。"
    "笔记没有记忆强度或遗忘机制，不要仅因时间较久就假装记不清。"
    "不要向用户展示内部字段、ID 和评分。"
)


class Runtime:
    def __init__(self, store, gateway, now, run_dir, version="v2"):
        self.store, self.gateway = store, gateway
        self.now, self.run_dir, self.version = now, run_dir, version
        self.trace_lock = RLock()
        self.elapsed_path = run_dir / "state.json"
        self.elapsed_days = json.loads(self.elapsed_path.read_text(encoding="utf-8")).get("elapsed_days", 0) if self.elapsed_path.exists() else 0

    @property
    def model_calls(self):
        return self.gateway.calls

    def context_node(self, note, nodes=None):
        # 笔记结构直接进入提示词，不附加 GA 分类或用户引擎的强度参数。
        return note.model_dump(mode="json")

    def retrieve(self, query, limit=8):
        return retrieve(self.store, query, limit)

    def trace(self, data):
        self.run_dir.mkdir(parents=True, exist_ok=True)
        with self.trace_lock, (self.run_dir / "results.jsonl").open("a", encoding="utf-8") as output:
            output.write(json.dumps({"version": self.version, "experiment_now": self.now.isoformat(),
                                     "elapsed_days": self.elapsed_days,
                                     "llm_model": os.getenv("LLM_MODEL", ""),
                                     "embedding_model": os.getenv("EMBEDDING_MODEL", ""),
                                     "llm_calls_total": self.model_calls, **data}, ensure_ascii=False) + "\n")

    def add_note(self, content, report=print):
        """一条用户消息保存成一条笔记；不提炼 GA event，不存 AI 回答为用户事实。"""
        report("A-Mem：分析新笔记的关键词、背景和标签，等待文字模型")
        analysis = analyze_content(self, content)
        note = MemoryNote(content=content, timestamp=self.now, last_accessed=self.now, **analysis.model_dump())
        process_memory(self, note, report)
        report("A-Mem：向量化并保存新笔记")
        self.store.add([note])
        return note.id

    def chat(self, query, read_only=False, report=print):
        report("A-Mem：检索笔记与关联邻居")
        candidates = self.retrieve(query)
        notes = self.store.nodes
        context = {"当前时间": self.now.isoformat(),
                   "记忆笔记": [self.context_node(notes[item.id]) for item in candidates]}
        report("生成回答，等待文字模型")
        reply = self.gateway.ask(RecallReply, ANSWER_INSTRUCTIONS, context, query)
        if not set(reply.used_memory_ids).issubset({item.id for item in candidates}):
            raise ValueError("回答引用了未提供的笔记 ID")
        record = {"turn_id": uuid4().hex, "mode": "read_only" if read_only else "dialogue", "query": query,
                  "reply": reply.model_dump(), "retrieved": [item.model_dump() for item in candidates],
                  "context": context, "record_count_before": len(notes)}
        report(f"\n小忆：{reply.answer}")
        if read_only:
            self.trace({**record, "stage": "read_only_complete"})
            return reply
        self.trace({**record, "stage": "dialogue_processing"})
        try:
            # 访问统计只做记录。它不增加强度，也不参与检索评分或回答模糊程度控制。
            accessed = []
            for item in candidates:
                note = notes[item.id]
                note.retrieval_count += 1
                note.last_accessed = self.now
                accessed.append(note)
            self.store.update(accessed)
            note_id = self.add_note(query, report)
            self.trace({**record, "stage": "dialogue_complete", "new_ids": [note_id],
                        "record_count_after": len(self.store.nodes)})
            report("本轮回答、笔记写入与关联维护已同步完成。")
        except Exception as error:
            self.trace({**record, "stage": "post_answer_failed", "error_type": type(error).__name__, "error": str(error)})
            raise
        return reply

    def save_elapsed(self):
        self.elapsed_path.parent.mkdir(parents=True, exist_ok=True)
        self.elapsed_path.write_text(json.dumps({"elapsed_days": self.elapsed_days}), encoding="utf-8")

    def elapse(self, days, report=print):
        delta = timedelta(days=days)
        if delta.total_seconds() <= 0:
            raise ValueError("流逝天数必须大于零")
        notes = list(self.store.nodes.values())
        for note in notes:
            note.timestamp -= delta
            note.last_accessed -= delta
        self.store.update(notes)
        self.elapsed_days += days
        self.save_elapsed()
        report("A-Mem 只前移笔记时间，不计算衰减或遗忘状态。")
