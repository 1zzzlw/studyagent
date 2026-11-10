"""离线行为测试：真实Pydantic/实验代码 + 替代向量、文字模型和Chroma客户端。

不访问API、不导入Chroma SDK，不等同于真实模型或SQLite运行验证。
运行：python -m unittest discover -s 12-memory/contrast/tests -v
"""
import ast
import builtins
import contextlib
import importlib
import io
import json
import math
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
NOW = datetime(2026, 11, 10, 4, tzinfo=timezone.utc)


class FakeEmbeddings:
    def __init__(self):
        self.documents = []
        self.queries = []

    @staticmethod
    def vector(text):
        return [float(word in text.lower()) for word in ("alpha", "beta", "gamma")] + [0.1]

    def embed_documents(self, texts):
        self.documents.extend(texts)
        return [self.vector(text) for text in texts]

    def embed_query(self, text):
        self.queries.append(text)
        return self.vector(text)


class FakeCollection:
    def __init__(self, metadata):
        self.metadata, self.records = metadata.copy(), {}
        self.updates = 0

    def add(self, ids, documents, embeddings, metadatas):
        for key, document, vector, metadata in zip(ids, documents, embeddings, metadatas, strict=True):
            if key in self.records:
                raise ValueError("duplicate")
            self.records[key] = (document, list(vector), metadata.copy())

    def get(self, include=None):
        return {"ids": list(self.records), "metadatas": [item[2] for item in self.records.values()]}

    def update(self, ids, metadatas):
        for key, metadata in zip(ids, metadatas, strict=True):
            document, vector, _ = self.records[key]
            self.records[key] = (document, vector, metadata.copy())
            self.updates += 1

    def query(self, query_embeddings, n_results, include, where=None):
        query = query_embeddings[0]
        found = []
        for key, (_, vector, metadata) in self.records.items():
            if where and metadata["node_type"] not in where["node_type"]["$in"]:
                continue
            similarity = sum(a * b for a, b in zip(query, vector)) / (
                math.sqrt(sum(a * a for a in query)) * math.sqrt(sum(b * b for b in vector)))
            found.append((key, 1 - similarity))
        found.sort(key=lambda item: (item[1], item[0]))
        return {"ids": [[key for key, _ in found[:n_results]]],
                "distances": [[distance for _, distance in found[:n_results]]]}


class FakeClient:
    def __init__(self):
        self.collections = {}

    def list_collections(self):
        return list(self.collections)

    def get_collection(self, name, embedding_function=None):
        return self.collections[name]

    def get_or_create_collection(self, name, embedding_function, metadata):
        return self.collections.setdefault(name, FakeCollection(metadata))

    def delete_collection(self, name):
        del self.collections[name]


class FakeGateway:
    def __init__(self, answers=None):
        self.answers, self.requests, self.calls = answers or {}, [], 0
        self.contexts = []

    def ask(self, output_type, instructions, context, message):
        name = output_type.__name__
        self.calls += 1
        self.requests.append(name)
        self.contexts.append(context)
        defaults = {
            "RecallReply": {"outcome": "answered", "answer": "离线测试回答", "used_memory_ids": []},
            "Appraisal": {"memories": []},
            "Insights": {"thoughts": []},
            "NoteEvolution": {"keywords": ["alpha"], "context": "资料中的偏好", "tags": ["偏好"],
                              "category": "生活", "links": [], "neighbor_updates": []},
        }
        defaults["NoteAnalysis"] = {"keywords": ["alpha"], "context": "用户提供的内容", "tags": ["偏好"]}
        if name == "NoteEvolution" and "should_evolve" in output_type.model_fields:
            defaults[name] = {"should_evolve": False, "actions": [], "suggested_connections": [],
                              "tags_to_update": [], "neighbor_updates": []}
        return output_type.model_validate(self.answers.get(name, defaults[name]))


def modules(version):
    return {name: importlib.import_module(f"{version}.{name}")
            for name in (("models", "store", "runtime", "strategy") if version == "v2" else
                         ("models", "engine", "store", "seed", "runtime", "strategy"))}


def new_node(mod, key, count=1, **kwargs):
    cls = getattr(mod["models"], "ConceptNode", None) or mod["models"].MemoryNote
    if cls.__name__ == "MemoryNote":
        return cls(id=key, content=f"alpha {key}", timestamp=NOW - timedelta(days=30),
                   last_accessed=NOW - timedelta(days=30), **kwargs)
    values = dict(node_id=key, node_count=count, type_count=count, description=f"alpha {key}",
                  created=NOW - timedelta(days=30), last_accessed=NOW - timedelta(days=30))
    values.update(kwargs)
    return cls(**values)


def fixture(version, directory, gateway=None, client=None):
    mod = modules(version)
    embeddings = FakeEmbeddings()
    store = mod["store"].ChromaStore(Path(directory), version, embeddings, "test-space", client or FakeClient())
    runtime = mod["runtime"].Runtime(store, gateway or FakeGateway(),
                                      NOW, Path(directory), version)
    return mod, runtime, embeddings


class ContrastTests(unittest.TestCase):
    def test_menu_statistics_and_read_only_question(self):
        for version in ("v1", "v3"):
            with self.subTest(version=version), tempfile.TemporaryDirectory() as directory:
                cli = importlib.import_module(f"{version}.cli")
                root = Path(directory)
                (root / "storge").mkdir()
                (root / "storge" / "memories.json").write_bytes((ROOT / "storge" / "memories.json").read_bytes())
                original = {key: getattr(cli, key) for key in
                            ("__file__", "load_environment", "create_embeddings", "embedding_signature", "ChromaStore", "ModelGateway")}
                saved_input, saved_argv = builtins.input, sys.argv
                answers = iter(["3", "4", "alpha", "0"])
                gateway, client = FakeGateway(), FakeClient()
                actual_store = cli.ChromaStore
                output = io.StringIO()
                try:
                    cli.__file__ = str(root / version / "cli.py")
                    cli.load_environment = lambda: None
                    cli.create_embeddings = FakeEmbeddings
                    cli.embedding_signature = lambda: "test-space"
                    cli.ChromaStore = lambda path, name, embeddings, signature: actual_store(path, name, embeddings, signature, client)
                    cli.ModelGateway = lambda: gateway
                    builtins.input = lambda prompt: next(answers)
                    sys.argv = ["main.py"]
                    with contextlib.redirect_stdout(output):
                        cli.run(version)
                finally:
                    builtins.input, sys.argv = saved_input, saved_argv
                    for key, value in original.items():
                        setattr(cli, key, value)
                self.assertNotIn("操作未全部完成", output.getvalue())
                self.assertIn("总数 300", output.getvalue())
                self.assertEqual(gateway.requests, ["RecallReply"])

    def test_versions_are_independent(self):
        for version in ("v1", "v2", "v3"):
            for path in (ROOT / version).glob("*.py"):
                for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                    if isinstance(node, ast.ImportFrom) and node.level == 0:
                        first = (node.module or "").split(".")[0]
                        self.assertNotIn(first, {"common", "v1", "v2", "v3"} - {version})
            self.assertNotIn("手动构建", (ROOT / version / "cli.py").read_text(encoding="utf-8"))
        prompts = [modules(version)["runtime"].ANSWER_INSTRUCTIONS for version in ("v1", "v2", "v3")]
        self.assertEqual(prompts[0], prompts[2])
        self.assertNotEqual(prompts[1], prompts[2])

    def test_same_300_seeds_and_preserved_history(self):
        snapshots = []
        for version in ("v1", "v3"):
            with self.subTest(version=version), tempfile.TemporaryDirectory() as directory:
                mod, runtime, embeddings = fixture(version, directory)
                seeds = mod["seed"].load_seeds(ROOT / "storge" / "memories.json")
                count = mod["seed"].import_baseline(runtime.store, seeds, NOW, runtime.engine,
                    directory, "source", report=lambda value: None)
                self.assertEqual(count, 300)
                self.assertEqual(len(runtime.store.nodes), 300)
                self.assertEqual(runtime.gateway.calls, 0)
                record = runtime.store.nodes["demo_292"]
                self.assertGreater(record.recall_count, 0)
                saved = record.model_dump_json()
                self.assertEqual(mod["seed"].import_baseline(runtime.store, seeds, NOW, runtime.engine,
                    directory, "source", report=lambda value: None), 0)
                self.assertEqual(runtime.store.nodes["demo_292"].model_dump_json(), saved)
                snapshots.append([(n.node_id, n.description, n.created, n.last_accessed,
                                   n.initial_strength, n.strength_after_recall, n.recall_count, n.status)
                                  for n in runtime.store.nodes.values()])
        self.assertEqual(snapshots[0], snapshots[1])

    def test_read_only_never_mutates_memory_or_history(self):
        for version in ("v1", "v2", "v3"):
            with self.subTest(version=version), tempfile.TemporaryDirectory() as directory:
                gateway = FakeGateway({"RecallReply": {"outcome": "recalled", "answer": "alpha", "used_memory_ids": ["a"]}})
                mod, runtime, _ = fixture(version, directory, gateway)
                runtime.store.add([new_node(mod, "a")])
                snapshot = runtime.store.nodes["a"].model_dump_json()
                runtime.chat("alpha", read_only=True, report=lambda value: None)
                self.assertEqual(snapshot, runtime.store.nodes["a"].model_dump_json())
                self.assertEqual(runtime.store.collection.updates, 0)
                self.assertFalse(getattr(runtime, "history", []))
                self.assertEqual(gateway.requests, ["RecallReply"])

    def test_only_actual_unique_usage_is_reinforced(self):
        for version in ("v1", "v3"):
            with self.subTest(version=version), tempfile.TemporaryDirectory() as directory:
                gateway = FakeGateway({"RecallReply": {"outcome": "recalled", "answer": "alpha", "used_memory_ids": ["a", "a"]}})
                mod, runtime, _ = fixture(version, directory, gateway)
                runtime.store.add([new_node(mod, "a"), new_node(mod, "b", 2)])
                runtime.chat("alpha", report=lambda value: None)
                runtime.store.reload()
                self.assertEqual(runtime.store.nodes["a"].recall_count, 1)
                self.assertEqual(runtime.store.nodes["b"].recall_count, 0)

    def test_invented_answer_memory_id_is_rejected_before_writes(self):
        for version in ("v1", "v2", "v3"):
            with self.subTest(version=version), tempfile.TemporaryDirectory() as directory:
                gateway = FakeGateway({"RecallReply": {"outcome": "recalled", "answer": "alpha", "used_memory_ids": ["invented"]}})
                mod, runtime, _ = fixture(version, directory, gateway)
                runtime.store.add([new_node(mod, "a")])
                with self.assertRaises(ValueError):
                    runtime.chat("alpha", report=lambda value: None)
                self.assertEqual(len(runtime.store.nodes), 1)
                self.assertEqual(runtime.store.nodes["a"].retrieval_count if version == "v2" else runtime.store.nodes["a"].recall_count, 0)

    def test_dialogue_triggers_one_reflection_after_enough_new_events(self):
        for version in ("v1", "v3"):
            with self.subTest(version=version), tempfile.TemporaryDirectory() as directory:
                gateway = FakeGateway({
                    "Appraisal": {"memories": [{"description": "用户今天也选择了alpha。",
                        "subject": "用户", "predicate": "选择", "object": "alpha", "keywords": ["alpha"],
                        "poignancy": 5, "attention": 0.8, "emotional_impact": 0.2}]},
                    "Insights": {"thoughts": [{"description": "用户可能持续偏好alpha", "evidence_refs": ["M1", "M2"],
                                               "keywords": ["alpha"], "poignancy": 6}]}})
                mod, runtime, _ = fixture(version, directory, gateway)
                runtime.store.add([new_node(mod, "a"), new_node(mod, "b", 2)])
                runtime.chat("alpha", report=lambda value: None)
                self.assertEqual(gateway.requests.count("Insights"), 1)
                self.assertNotIn("FocalPoints", gateway.requests)
                thoughts = [node for node in runtime.store.nodes.values() if node.type == "thought"]
                self.assertEqual(len(thoughts), 1)
                self.assertEqual(set(thoughts[0].filling), {"a", "b"})
                self.assertEqual(thoughts[0].depth, 1)
                self.assertEqual(runtime.reflection_summary["status"], "complete")
                self.assertLessEqual(runtime.engine.effective_strength(thoughts[0], runtime.store.nodes, NOW),
                                     runtime.engine.strength(runtime.store.nodes["a"], NOW))
                if version == "v3":
                    self.assertTrue(thoughts[0].association_ready)

    def test_reflection_gate_uses_no_model_or_query_embedding(self):
        for version in ("v1", "v3"):
            with self.subTest(version=version), tempfile.TemporaryDirectory() as directory:
                mod, runtime, embeddings = fixture(version, directory)
                runtime.store.add([new_node(mod, "a"), new_node(mod, "b", 2)])
                reflection = importlib.import_module(f"{version}.reflection")
                self.assertEqual(reflection.reflect(runtime, ["a", "b"], report=lambda value: None, new_ids=["b"]), 0)
                self.assertEqual(runtime.gateway.calls, 0)
                self.assertFalse(embeddings.queries)
                self.assertEqual(runtime.reflection_summary["status"], "skipped")
                runtime.store.patch("a", poignancy=8)
                runtime.store.patch("b", poignancy=8)
                self.assertEqual(reflection.reflect(runtime, ["a", "b"], report=lambda value: None), 0)
                self.assertEqual(runtime.gateway.calls, 0)  # 无新事件时不重复尝试。
                runtime.store.patch("a", source_observation_id="same")
                runtime.store.patch("b", source_observation_id="same")
                self.assertEqual(reflection.reflect(runtime, ["a", "b"], report=lambda value: None, new_ids=["b"]), 0)
                self.assertEqual(runtime.gateway.calls, 0)  # 单次观察拆成两条不提前触发。

    def test_reflection_rejects_bad_refs_but_preserves_valid_thought(self):
        for version in ("v1", "v3"):
            with self.subTest(version=version), tempfile.TemporaryDirectory() as directory:
                draft = {"description": "用户可能持续偏好alpha", "evidence_refs": ["M1", "M2"],
                         "keywords": ["alpha"], "poignancy": 6}
                gateway = FakeGateway({"Insights": {"thoughts": [draft,
                    {**draft, "description": "无效引用", "evidence_refs": ["M1", "chat_source"]},
                    {**draft, "description": "重复引用", "evidence_refs": ["M1", "M1"]}]}})
                mod, runtime, embeddings = fixture(version, directory, gateway)
                runtime.store.add([new_node(mod, "a", source_observation_id="obs_a", poignancy=8),
                                   new_node(mod, "b", 2, source_observation_id="obs_b", poignancy=8)])
                reflection = importlib.import_module(f"{version}.reflection")
                added = reflection.reflect(runtime, ["a", "b"], report=lambda value: None, new_ids=["b"])
                self.assertEqual(added, 1)
                self.assertEqual(len(runtime.reflection_summary["rejected"]), 2)
                self.assertEqual(runtime.reflection_summary["evidence_map"], {"M1": "a", "M2": "b"})
                self.assertEqual(runtime.reflection_summary["status"], "complete_with_rejections")
                self.assertFalse(runtime.store.nodes["a"].reflected)
                supplied = gateway.contexts[0]["候选资料"]
                self.assertEqual([item["ref"] for item in supplied], ["M1", "M2"])
                self.assertTrue(all("node_id" not in item and "evidence_ids" not in item for item in supplied))

    def test_empty_reflection_consumes_batch_without_repeating_or_reinforcing(self):
        for version in ("v1", "v3"):
            with self.subTest(version=version), tempfile.TemporaryDirectory() as directory:
                mod, runtime, _ = fixture(version, directory)
                runtime.store.add([new_node(mod, "a", poignancy=8), new_node(mod, "b", 2, poignancy=8)])
                reflection = importlib.import_module(f"{version}.reflection")
                reflection.reflect(runtime, ["a", "b"], report=lambda value: None, new_ids=["b"])
                self.assertEqual(runtime.gateway.requests, ["Insights"])
                self.assertTrue(runtime.store.nodes["a"].reflected)
                self.assertEqual(runtime.store.nodes["a"].recall_count, 0)
                runtime.store.reload()
                reflection.reflect(runtime, ["a", "b"], report=lambda value: None, new_ids=["b"])
                self.assertEqual(runtime.gateway.requests, ["Insights"])

    def test_time_shift_persists_and_preserves_counts(self):
        for version in ("v1", "v3"):
            with self.subTest(version=version), tempfile.TemporaryDirectory() as directory:
                mod, runtime, embeddings = fixture(version, directory)
                node = new_node(mod, "a", recall_count=2)
                runtime.store.add([node])
                before = runtime.engine.strength(node, NOW)
                runtime.elapse(30)
                runtime.store.reload()
                node = runtime.store.nodes["a"]
                self.assertEqual(node.created, NOW - timedelta(days=60))
                self.assertEqual(node.recall_count, 2)
                self.assertLess(runtime.engine.strength(node, NOW), before)
                self.assertEqual(len(embeddings.documents), 1)

    def test_superseded_evidence_invalidates_thought(self):
        for version in ("v1", "v3"):
            mod = modules(version)
            old = new_node(mod, "old", status="superseded")
            thought = new_node(mod, "thought", 2, type="thought", filling=["old"])
            self.assertFalse(mod["models"].eligible(thought, {"old": old, "thought": thought}, NOW))

    def test_links_get_reserved_context_slots_and_ids_are_checked(self):
        for version in ("v3",):
            with self.subTest(version=version), tempfile.TemporaryDirectory() as directory:
                mod, runtime, _ = fixture(version, directory)
                nodes = [new_node(mod, str(i), i + 1) for i in range(12)]
                nodes[0].links = ["11"]
                runtime.store.add(nodes)
                association = importlib.import_module(f"{version}.association")
                ranked = [mod["models"].Candidate(node_id=str(i), score=1 - i / 20) for i in range(10)]
                selected = association.expand_links(runtime.store, ranked, NOW, 8)
                self.assertEqual(len(selected), 8)
                self.assertIn("11", [item.node_id for item in selected])
                snapshot = nodes[0].model_dump_json()
                runtime.gateway = FakeGateway({"NoteEvolution": {"keywords": [], "context": "x", "tags": [],
                    "category": "x", "links": ["invented"], "neighbor_updates": []}})
                with self.assertRaises(ValueError):
                    association.evolve(runtime, nodes[0])
                self.assertEqual(nodes[0].model_dump_json(), snapshot)

    def test_metadata_updates_do_not_reembed_and_space_mismatch_is_rejected(self):
        for version in ("v1", "v3"):
            with self.subTest(version=version), tempfile.TemporaryDirectory() as directory:
                client = FakeClient()
                mod, runtime, embeddings = fixture(version, directory, client=client)
                node = new_node(mod, "a")
                runtime.store.add([node])
                runtime.engine.recall(node, NOW)
                runtime.store.update([node])
                self.assertEqual(len(embeddings.documents), 1)
                with self.assertRaises(ValueError):
                    mod["store"].ChromaStore(Path(directory), version, embeddings, "other-space", client)
                self.assertEqual(client.collections[f"contrast_{version}"].metadata["embedding_signature"], "test-space")

    def test_amem_stores_plain_note_and_counts_retrieval_without_strength(self):
        with tempfile.TemporaryDirectory() as directory:
            mod, runtime, embeddings = fixture("v2", directory)
            runtime.store.add([new_node(mod, "a")])
            runtime.chat("alpha", report=lambda value: None)
            notes = runtime.store.nodes
            self.assertEqual(len(notes), 2)
            self.assertEqual(notes["a"].retrieval_count, 1)
            self.assertNotIn("initial_strength", notes["a"].model_dump())
            self.assertNotIn("type", notes["a"].model_dump())
            self.assertFalse(hasattr(runtime, "engine"))
            self.assertEqual(runtime.gateway.requests, ["RecallReply", "NoteAnalysis", "NoteEvolution"])
            runtime.elapse(30, report=lambda value: None)
            self.assertEqual(runtime.store.nodes["a"].timestamp, NOW - timedelta(days=60))
            self.assertEqual(len(embeddings.documents), 2)



if __name__ == "__main__":
    unittest.main()
