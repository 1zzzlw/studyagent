"""真实本地 Chroma 持久化；向量由确定性替身生成，不连接外部接口。"""
import hashlib
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent.common.models import beijing_now
from agent.infrastructure.persistence.chroma_index import ChromaIndex
from agent.systems.memory.domain.models import MemoryNode


class DeterministicEmbeddings:
    def embed_query(self, text):
        return [value / 255.0 for value in hashlib.sha256(text.encode()).digest()[:8]]

    def embed_documents(self, texts):
        return [self.embed_query(text) for text in texts]


class ChromaTests(unittest.TestCase):
    def test_index_upsert_persistence_and_embedding_identity(self):
        with tempfile.TemporaryDirectory() as temp:
            index = ChromaIndex(Path(temp), DeterministicEmbeddings(), "offline-model-a")
            try:
                node = MemoryNode(node_id="event_1", character_id="character_1", conversation_id="conversation_1",
                                  type="event", description="用户喜欢读书", created_at=beijing_now(), keywords=["阅读"])
                index.upsert([node])
                self.assertEqual(index.search("喜欢读书", "character_1")[0][0], "event_1")
                node.context = "第二次补充背景"
                index.upsert([node])
                reopened = ChromaIndex(Path(temp), DeterministicEmbeddings(), "offline-model-a")
                info = reopened.info()
                self.assertEqual(info["count"], 1)
                self.assertEqual(info["vector_previews"][0]["dimensions"], 8)
                self.assertIn("第二次补充背景", info["sample"]["documents"][0])
                self.assertEqual(reopened.search("读书", "other_character"), [])
                with self.assertRaises(ValueError):
                    ChromaIndex(Path(temp), DeterministicEmbeddings(), "other-model-same-dimension")
            finally:
                # 释放 Windows 对临时持久化目录的文件占用。
                index.client._system.stop()
                from chromadb.api.shared_system_client import SharedSystemClient
                SharedSystemClient.clear_system_cache()


if __name__ == "__main__":
    unittest.main()
