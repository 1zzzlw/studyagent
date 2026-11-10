"""Web 适配层的离线检查定义；模型、向量与 Chroma 使用替代实现。"""
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from threading import Event, Thread

from test_contrast import FakeClient, FakeEmbeddings, FakeGateway, NOW, modules, new_node
from web_service import BusyError, MemoryLab


class WebServiceTests(unittest.TestCase):
    def lab(self, directory, gateways=None):
        clients = {version: FakeClient() for version in ("v1", "v2", "v3")}

        def factory(version, data_dir, now):
            mod = modules(version)
            store = mod["store"].ChromaStore(data_dir / "chromadb" / version, version,
                FakeEmbeddings(), "offline", clients[version])
            return mod["runtime"].Runtime(store, (gateways or {}).get(version, FakeGateway()),
                now, data_dir / version, version)

        return MemoryLab(directory, factory=factory, now=NOW)

    def test_empty_start_no_seed_import_and_versions_are_isolated(self):
        with tempfile.TemporaryDirectory() as directory:
            lab = self.lab(directory)
            for version in ("v1", "v2", "v3"):
                current = lab.session(version)
                self.assertEqual(current.memories(), [])
                self.assertEqual(current.runtime.model_calls, 0)
                self.assertEqual(current.turns(), [])
            first = lab.session("v1")
            first.chat("你好")
            self.assertEqual(first.status()["counts"]["chat"], 1)
            self.assertEqual(first.turns()[0]["stage"], "dialogue_complete")
            self.assertFalse(lab.session("v2").memories())
            self.assertFalse(lab.session("v3").memories())
            first.reset()
            self.assertFalse(first.memories())
            self.assertFalse(first.turns())

    def test_complete_stored_fields_match_each_version(self):
        for version in ("v1", "v2", "v3"):
            with self.subTest(version=version), tempfile.TemporaryDirectory() as directory:
                gateway = FakeGateway({"Appraisal": {"memories": [{
                    "description": "用户最近喜欢喝乌龙茶。", "subject": "用户", "predicate": "喜欢", "object": "乌龙茶",
                    "keywords": ["茶"], "poignancy": 5, "attention": 0.8, "emotional_impact": 0.2,
                }]}})
                session = self.lab(directory, {version: gateway}).session(version)
                session.chat("最近我喜欢喝乌龙茶。")
                kind = "note" if version == "v2" else "event"
                record = next(item for item in session.memories() if item["type"] == kind)
                detail = session.memory(record["node_id"])
                if version == "v2":
                    self.assertEqual(detail["stored"]["content"], "最近我喜欢喝乌龙茶。")
                    self.assertNotIn("current_strength", detail["computed"])
                    self.assertNotIn("filling", detail["stored"])
                    self.assertEqual(session.status()["counts"], {"note": 1})
                else:
                    self.assertIn("stability_days", detail["stored"])
                    self.assertIn("current_strength", detail["computed"])
                    source_id = detail["stored"]["filling"][0]
                    self.assertEqual(session.memory(source_id)["stored"]["type"], "chat")
                session.elapse(30)
                shifted = session.memory(record["node_id"])
                time_key = "timestamp" if version == "v2" else "created"
                self.assertEqual(datetime.fromisoformat(shifted["stored"][time_key]), NOW - timedelta(days=30))
                self.assertEqual(session.turns()[0]["stage"], "dialogue_complete")
                self.assertNotIn("background", session.status())

    def test_read_only_question_does_not_write_memory(self):
        for version in ("v1", "v2", "v3"):
            with self.subTest(version=version), tempfile.TemporaryDirectory() as directory:
                session = self.lab(directory).session(version)
                session.chat("你知道什么？", read_only=True)
                self.assertFalse(session.memories())
                self.assertEqual(session.runtime.gateway.requests, ["RecallReply"])
                self.assertEqual(session.turns()[0]["stage"], "read_only_complete")

    def test_reflection_blocks_round_but_status_still_available(self):
        started, release = Event(), Event()

        class PausedReflection(FakeGateway):
            def ask(self, output_type, instructions, context, message):
                if output_type.__name__ == "Insights":
                    started.set()
                    if not release.wait(5):
                        raise TimeoutError("controlled wait")
                return super().ask(output_type, instructions, context, message)

        with tempfile.TemporaryDirectory() as directory:
            lab = self.lab(directory, {"v1": PausedReflection({"Appraisal": {"memories": [{
                "description": "用户今天选择alpha", "subject": "用户", "predicate": "选择", "object": "alpha",
                "keywords": ["alpha"], "poignancy": 5, "attention": 0.8, "emotional_impact": 0.2,
            }]}})})
            session, failures = lab.session("v1"), []
            mod = modules("v1")
            session.runtime.store.add([new_node(mod, "a"), new_node(mod, "b", 2)])

            def chat():
                try:
                    session.chat("你好")
                except Exception as error:
                    failures.append(error)

            thread = Thread(target=chat)
            try:
                thread.start()
                self.assertTrue(started.wait(1))
                self.assertTrue(thread.is_alive())
                self.assertEqual(session.turns()[0]["stage"], "dialogue_processing")
                self.assertTrue(session.status()["activity"])
                with self.assertRaises(BusyError):
                    session.chat("第二问")
                self.assertEqual(lab.session("v2").status()["activity"], "")
                release.set()
                thread.join(3)
                self.assertFalse(thread.is_alive())
                self.assertEqual(session.turns()[0]["stage"], "dialogue_complete")
                self.assertEqual(failures, [])
            finally:
                release.set()
                thread.join(3)

    def test_clock_is_persisted_and_unknown_version_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            lab = self.lab(directory)
            self.assertEqual(lab.now, NOW)
            reloaded = MemoryLab(directory, factory=lab.factory, now=NOW + timedelta(days=1))
            self.assertEqual(reloaded.now, NOW)
            with self.assertRaises(KeyError):
                lab.session("../v1")
            self.assertTrue((Path(directory) / "clock.json").exists())


if __name__ == "__main__":
    unittest.main()
