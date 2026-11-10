"""v1 对话流程：检索 -> 回答 -> 实际使用后强化 -> 原话/事件 -> 每轮检查反思条件。"""
import json
import os
from collections import deque
from copy import deepcopy
from threading import RLock
from datetime import timedelta
from uuid import uuid4

from .engine import EbbinghausMemoryEngine
from .models import Appraisal, ConceptNode, RecallReply, eligible
from .reflection import reflect
from .seed import atomic_json
from .strategy import retrieve


ANSWER_INSTRUCTIONS = (
    "你是与用户自然交流的小忆。根据最近原话和提供的长期记忆回答。"
    "只有实际采用长期记忆才返回 recalled，并列出实际使用的 used_memory_ids。"
    "普通交流或仅根据本轮输入/短期原话回答，返回 answered，ID 为空。"
    "相似事件分不清则 uncertain，缺少依据则 not_recalled；这两种情况 ID 为空。"
    "description是记忆正文，context/tags只是辅助归纳，不能用它们覆盖正文事实。"
    "记忆强度是清晰程度，不是真实性或重要性。低强度时自然表达模糊，不能编造缺失细节，"
    "也不要每句机械地说记不清。thought 是带依据的主观认识，不能当作已证实事实。"
    "保留邀请、条件、猜测、承诺与完成的区别。用户问题的预设不能直接当事实承认。"
    "旧记忆里的昨天/明天相对它的形成时间；时间经过本身不代表任务已完成。"
    "候选相似不等于全部想起，不要向用户展示 ID、评分和内部字段。"
)


class Runtime:
    def __init__(self, store, gateway, now, run_dir, version):
        self.store, self.gateway = store, gateway
        self.now, self.run_dir, self.version = now, run_dir, version
        self.assistant_name = "小忆"
        self.engine = EbbinghausMemoryEngine()
        self.history = deque(maxlen=2)
        self.trace_lock = RLock()
        self.progress = lambda message: None
        self.reflection_summary = {"status": "not_started"}
        self.elapsed_path = run_dir / "state.json"
        self.elapsed_days = json.loads(self.elapsed_path.read_text(encoding="utf-8")).get("elapsed_days", 0) if self.elapsed_path.exists() else 0

    def retrieve(self, query, limit=8):
        return retrieve(self.store, query, self.now, limit)

    def context_node(self, node, nodes=None):
        nodes = self.store.nodes if nodes is None else nodes
        value = {"node_id": node.node_id, "type": node.type,
                 "description": node.description[:1600], "formed_at": node.created.isoformat(),
                 "last_recalled_at": node.last_accessed.isoformat(),
                 "age_days": round((self.now - node.created).total_seconds() / 86400, 4),
                 "current_strength": self.engine.effective_strength(node, nodes, self.now),
                 "status": node.status, "evidence_ids": node.filling if node.type != "chat" else []}
        strength = value["current_strength"]
        value["status"] = "active" if strength > 0.6 else "fading" if strength > 0.2 else "forgotten"
        return value

    def after_dialogue(self, source_ids, report=print, new_ids=()):
        return reflect(self, source_ids, report=report, new_ids=new_ids)

    def trace(self, data):
        self.run_dir.mkdir(parents=True, exist_ok=True)
        with self.trace_lock, (self.run_dir / "results.jsonl").open("a", encoding="utf-8") as output:
            output.write(json.dumps({"version": self.version, "experiment_now": self.now.isoformat(),
                                     "elapsed_days": self.elapsed_days,
                                     "llm_model": os.getenv("LLM_MODEL", ""),
                                     "embedding_model": os.getenv("EMBEDDING_MODEL", ""),
                                     "llm_calls_total": self.model_calls, **data}, ensure_ascii=False) + "\n")

    @property
    def model_calls(self):
        return self.gateway.calls

    def chat(self, query, read_only=False, report=print):
        report("检索本轮相关记忆")
        search_query = query
        recent = [] if read_only else list(self.history)
        if recent:
            search_query += "\n最近一轮原话：" + json.dumps(recent[-1], ensure_ascii=False)
        view = self.store.view()
        candidates = retrieve(view, search_query, self.now, 8)
        context = {"当前时间": self.now.isoformat(),
                   "最近原话": recent,
                   "长期记忆": [self.context_node(view.nodes[item.node_id], view.nodes) for item in candidates]}
        report("生成回答，等待文字模型")
        reply = self.gateway.ask(RecallReply, ANSWER_INSTRUCTIONS, context, query)
        allowed = {item.node_id for item in candidates}
        if not set(reply.used_memory_ids).issubset(allowed):
            raise ValueError("回答引用了本轮没有提供的记忆 ID")
        trace = {"turn_id": uuid4().hex, "mode": "read_only" if read_only else "dialogue", "query": query,
                 "reply": reply.model_dump(), "retrieved": [item.model_dump() for item in candidates],
                 "context": context, "record_count_before": len(view.nodes)}
        report(f"\n{self.assistant_name}：{reply.answer}")
        report(f"  [{reply.outcome}] 上下文 {len(candidates)} 条，实际采用 {len(set(reply.used_memory_ids))} 条")
        if read_only:
            self.trace({**trace, "stage": "read_only_complete"})
            return reply
        # 一轮内顺序完成回答、记忆写入与反思；全部完成后才返回调用方。
        self.history.append({"user": query, "assistant": reply.answer})
        self.trace({**trace, "stage": "dialogue_processing"})
        self._postprocess(query, reply, deepcopy(context), candidates, trace, report)
        return reply

    def _postprocess(self, query, reply, context, candidates, trace, progress):
        self.progress = progress
        self.reflection_summary = {"status": "not_started"}
        # 写入前确认来源仍然有效，不能强化已失效的旧认识。
        nodes = self.store.nodes
        allowed = {item.node_id for item in candidates if item.node_id in nodes
                   and eligible(nodes[item.node_id], nodes, self.now)}
        context["长期记忆"] = [self.context_node(nodes[item.node_id], nodes)
                             for item in candidates if item.node_id in allowed]
        try:
            progress("登记实际回忆并保存本轮原话")
            skipped = [key for key in dict.fromkeys(reply.used_memory_ids) if key not in allowed]
            used = [nodes[key] for key in dict.fromkeys(reply.used_memory_ids) if key in allowed]
            for node in used:
                self.engine.recall(node, self.now)
            self.store.update(used)
            observation = f"obs_{uuid4().hex}"
            chat = ConceptNode(
                node_id=f"chat_{uuid4().hex}", **self.store.next_fields("chat"), type="chat",
                description=f"用户：{query}\n{self.assistant_name}：{reply.answer}",
                created=self.now, last_accessed=self.now, source_observation_id=observation,
                subject=self.assistant_name, predicate="chat with", object="用户",
                filling=[("用户", query), (self.assistant_name, reply.answer)],
            )
            self.engine.register(chat)
            self.store.add([chat])
            context["本轮原话节点ID"] = chat.node_id
            progress("提炼长期记忆，等待文字模型")
            appraisal = self.gateway.ask(
                Appraisal,
                "根据本轮真实交流提炼值得长期保存的新事件，可以返回空列表。"
                "正文从角色视角写，保留人称方向、条件和不确定性。"
                "只询问旧事、AI 自己的回答或猜测不是新的事实，不复制旧记忆以刷新强度。"
                "filling 只能使用提供的旧记忆 ID 或本轮原话节点 ID。"
                "仅用户明确纠正旧认识时设置 supersedes_id，不能把以前真实、后来变化的经历当成错误。"
                "不覆盖历史原话。poignancy 是重要性1～10，attention和emotional_impact为0～1。",
                context, json.dumps({"用户": query, "AI": reply.answer}, ensure_ascii=False),
            )
            evidence_ids = allowed | {chat.node_id}
            corrected = set()
            for draft in appraisal.memories:
                if not set(draft.filling).issubset(evidence_ids):
                    raise ValueError("记忆草稿引用了无效来源")
                old = draft.supersedes_id
                if old:
                    if old not in allowed or old in corrected:
                        raise ValueError("纠正目标无效或重复")
                    corrected.add(old)
            new_ids = []
            for index, draft in enumerate(appraisal.memories, 1):
                progress(f"写入新事件 {index}/{len(appraisal.memories)}")
                node = ConceptNode(
                    node_id=f"event_{uuid4().hex}", **self.store.next_fields("event"),
                    created=self.now, last_accessed=self.now, source_observation_id=observation,
                    **draft.model_dump(exclude={"filling"}),
                    filling=list(dict.fromkeys([chat.node_id, *draft.filling])),
                )
                self.engine.register(node)
                self.store.add([node])
                if node.supersedes_id:
                    old = self.store.nodes[node.supersedes_id]
                    old.status = "superseded"
                    self.store.update([old])
                new_ids.append(node.node_id)
            source_ids = [item.node_id for item in candidates] + new_ids + [chat.node_id]
            reflected = self.after_dialogue(source_ids, progress, new_ids=new_ids)
            self.trace({**trace, "stage": "dialogue_complete", "new_ids": new_ids,
                        "new_thoughts": reflected, "reflection": self.reflection_summary, "skipped_memory_ids": skipped,
                        "record_count_after": len(self.store.nodes)})
            progress(f"已保存原话，新增事件 {len(new_ids)} 条、新认识 {reflected} 条")
        except Exception as error:
            if self.reflection_summary["status"] == "running":
                self.reflection_summary.update(status="failed", reason=str(error))
            self.trace({**trace, "stage": "post_answer_failed", "error_type": type(error).__name__,
                        "error": str(error), "reflection": self.reflection_summary})
            raise

    def elapse(self, days, report=print):
        delta = timedelta(days=days)
        if delta.total_seconds() <= 0:
            raise ValueError("流逝天数必须大于零")
        shifted = []
        for node in self.store.nodes.values():
            data = node.model_dump()
            data.update(created=node.created - delta, last_accessed=node.last_accessed - delta,
                        expiration=node.expiration - delta if node.expiration else None)
            changed = ConceptNode.model_validate(data)
            self.engine.step(changed, self.now)
            shifted.append(changed)
        self.store.update(shifted)
        self.elapsed_days += days
        atomic_json(self.elapsed_path, {"elapsed_days": self.elapsed_days})
        self.history.clear()
