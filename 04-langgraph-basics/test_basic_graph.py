import unittest
from pathlib import Path
import sys

# IDE 可能从项目根目录启动测试。显式加入测试文件所在目录，确保可以导入
# 同目录的 basic_graph.py，不依赖当前工作目录。
MODULE_DIR = Path(__file__).resolve().parent
if str(MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(MODULE_DIR))

from basic_graph import graph


class BasicGraphTest(unittest.TestCase):
    def test_even_number_uses_double_branch(self):
        result = graph.invoke({"number": 4, "steps": []})

        self.assertEqual(result["result"], 8)
        self.assertEqual(result["steps"], ["收到数字 4", "偶数乘以 2"])

    def test_odd_number_uses_triple_branch(self):
        result = graph.invoke({"number": 5, "steps": []})

        self.assertEqual(result["result"], 15)
        self.assertEqual(result["steps"], ["收到数字 5", "奇数乘以 3"])


if __name__ == "__main__":
    unittest.main()
