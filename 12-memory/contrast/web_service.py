"""Web 适配层：复用三版 Runtime，不导入种子记忆，不改记忆算法。"""
import importlib
import json
import os
from collections import deque
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock, RLock
from time import monotonic


VERSIONS = {
    "v1": "GA + 衰减强化",
    "v2": "纯 A-Mem",
    "v3": "GA + A-Mem + 衰减强化",
}
ROOT = Path(__file__).resolve().parent


class BusyError(Exception):
    pass


def create_runtime(version, data_dir, now):
    """独立 Web 数据目录。已有 CLI 数据和 300 条 JSON 均不读取。"""
    llm = importlib.import_module(f"{version}.llm")
    store_module = importlib.import_module(f"{version}.store")
    runtime_module = importlib.import_module(f"{version}.runtime")
    store = store_module.ChromaStore(
        data_dir / "chromadb" / version, version, llm.create_embeddings(), llm.embedding_signature(),
    )
    return runtime_module.Runtime(store, llm.ModelGateway(), now,
                                  data_dir / version, version)


class Session:
    def __init__(self, version, runtime):
        self.version, self.runtime = version, runtime
        self.operation_lock, self.event_lock = Lock(), RLock()
        self.events = deque(maxlen=100)
        self.activity = ""
        self.current_query = None
        self.stage, self.started, self.last_error = "", None, ""

    def report(self, message):
        with self.event_lock:
            self.stage = message.strip()
            self.events.append({"time": datetime.now().strftime("%H:%M:%S"), "message": self.stage})

    @contextmanager
    def operation(self, label, query=None):
        # 一个版本的前台按顺序操作；状态读取不拿这把锁，模型等待时仍可刷新页面。
        if not self.operation_lock.acquire(blocking=False):
            raise BusyError("这个版本正在同步处理本轮操作，请完成后再试。")
        with self.event_lock:
            self.activity, self.current_query = label, query
            self.stage, self.started, self.last_error = label, monotonic(), ""
        try:
            yield
        except Exception as error:
            with self.event_lock:
                self.last_error = f"{type(error).__name__}: {error}"
            self.report(f"本次操作未全部完成：{self.last_error}")
            raise
        finally:
            with self.event_lock:
                self.activity, self.current_query = "", None
                self.started = None
            self.operation_lock.release()

    def turns(self):
        """从已有 trace 还原对话与本轮检索，不再另存一套聊天文件。"""
        turns = {}
        path = self.runtime.run_dir / "results.jsonl"
        with self.runtime.trace_lock:
            if not path.exists():
                return []
            for line in path.read_text(encoding="utf-8").splitlines():
                row = json.loads(line)
                key = row.get("turn_id")
                if key:
                    turns[key] = row
        return list(turns.values())

    def status(self):
        runtime = self.runtime
        nodes = runtime.store.nodes
        with self.event_lock:
            activity, query = self.activity, self.current_query
            events = list(self.events)
            processing = {"stage": self.stage, "seconds": round(monotonic() - self.started, 1) if self.started is not None else 0,
                          "last_error": self.last_error}
        return {
            "version": self.version, "title": VERSIONS[self.version],
            "now": runtime.now.isoformat(), "elapsed_days": runtime.elapsed_days,
            "activity": activity, "current_query": query,
            "processing": processing, "events": events,
            "counts": {"note": len(nodes)} if self.version == "v2" else
                      {kind: sum(node.type == kind for node in nodes.values()) for kind in ("event", "thought", "chat")},
            "model_calls": runtime.model_calls,
        }

    def memories(self):
        runtime, result = self.runtime, []
        nodes = runtime.store.nodes
        ordered = sorted(nodes.values(), key=lambda node: node.timestamp if self.version == "v2" else node.created, reverse=True)
        for node in ordered:
            if self.version == "v2":
                result.append({"node_id": node.id, "type": "note", "description": node.content,
                               "created": node.timestamp.isoformat(), "retrieval_count": node.retrieval_count})
                continue
            current = runtime.context_node(node, nodes)
            result.append({"node_id": node.node_id, "type": node.type,
                           "description": node.description, "created": node.created.isoformat(),
                           "current_strength": current["current_strength"],
                           "status": "superseded" if node.status == "superseded" else current["status"],
                           "recall_count": node.recall_count})
        return result

    def memory(self, node_id):
        nodes = self.runtime.store.nodes
        if node_id not in nodes:
            raise KeyError("这条记忆不存在或已经清空。")
        node = nodes[node_id]
        return {"stored": node.model_dump(mode="json"),
                "computed": self.runtime.context_node(node, nodes)}

    def graph(self):
        """只呈现已经存储的关系，不根据相似度造边，也不触发回忆或模型调用。"""
        nodes = self.runtime.store.nodes
        records, edges, seen = [], [], set()
        ordered = sorted(nodes.values(), key=lambda node: node.timestamp if self.version == "v2" else node.created)
        for node in ordered:
            if self.version == "v2":
                records.append({"id": node.id, "type": "note", "description": node.content,
                                "created": node.timestamp.isoformat(), "retrieval_count": node.retrieval_count})
                edges.extend({"source": node.id, "target": target, "type": "link", "directed": True}
                             for target in dict.fromkeys(node.links))
                continue
            current = self.runtime.context_node(node, nodes)
            records.append({"id": node.node_id, "type": node.type, "description": node.description,
                            "strength": current["current_strength"], "status": node.status,
                            "depth": node.depth, "recall_count": node.recall_count,
                            "created": node.created.isoformat()})
            relations = [(key, "evidence") for key in node.filling] if node.type != "chat" else []
            relations += [(key, "link") for key in getattr(node, "links", [])]
            if node.supersedes_id:
                relations.append((node.supersedes_id, "supersedes"))
            for target, kind in relations:
                # links 按双向语义关联展示；来源与纠正保留箭头方向。
                key = (kind, *sorted((node.node_id, target))) if kind == "link" else (kind, node.node_id, target)
                if key in seen:
                    continue
                seen.add(key)
                edges.append({"source": node.node_id, "target": target, "type": kind})
        return {**self.status(), "nodes": records, "edges": edges}

    def chat(self, message, read_only=False):
        with self.operation("正在检索并生成回答", message):
            reply = self.runtime.chat(message, read_only=read_only, report=self.report)
            return reply.model_dump(mode="json")

    def elapse(self, days):
        with self.operation("推进已有记忆时间"):
            self.runtime.elapse(days, report=self.report)
            self.report(f"已有笔记经过 {days:g} 天，未计算衰减。" if self.version == "v2" else
                        f"已有记忆经过 {days:g} 天；短期原话已清空。")
        return self.status()

    def reset(self):
        with self.operation("清空本版数据"):
            runtime = self.runtime
            runtime.store.reset()
            if self.version != "v2":
                runtime.history.clear()
            runtime.elapsed_days = 0
            runtime.elapsed_path.parent.mkdir(parents=True, exist_ok=True)
            runtime.elapsed_path.write_text('{"elapsed_days": 0}', encoding="utf-8")
            with runtime.trace_lock:
                (runtime.run_dir / "results.jsonl").unlink(missing_ok=True)
            with self.event_lock:
                self.events.clear()
            self.report("本版本的 Web 记忆和聊天已清空。")
        return self.status()


class MemoryLab:
    def __init__(self, data_dir=None, factory=create_runtime, now=None):
        self.data_dir = Path(data_dir) if data_dir else ROOT / "storge" / "web"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.factory, self.lock, self.sessions = factory, RLock(), {}
        # 固定共同实验时刻并保存，重启后仍使用同一时间基准。
        clock_path = self.data_dir / "clock.json"
        if clock_path.exists():
            self.now = datetime.fromisoformat(json.loads(clock_path.read_text(encoding="utf-8"))["now"])
        else:
            configured = os.getenv("EXPERIMENT_NOW")
            self.now = now or (datetime.fromisoformat(configured) if configured else datetime.now(timezone.utc))
            if self.now.tzinfo is None:
                raise ValueError("实验时间必须带时区")
            clock_path.write_text(json.dumps({"now": self.now.isoformat()}), encoding="utf-8")

    def session(self, version):
        if version not in VERSIONS:
            raise KeyError("未知实验版本")
        with self.lock:
            if version not in self.sessions:
                self.sessions[version] = Session(version, self.factory(version, self.data_dir, self.now))
            return self.sessions[version]

