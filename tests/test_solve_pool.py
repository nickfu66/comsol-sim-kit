"""SolvePool 求解去重池的离线测试（先失败后实现）。

契约：
- SolvePool(directory)：目录由调用方注入，不含任何案例路径。
- key(physics, calc, geom, freq_list)：四要素规范化 JSON 的 sha256 前缀；
  任一要素变 -> 键变；要素顺序/浮点表示规范化（dict 序无关）。
- put/get：原子落盘；未命中返回 None；损坏文件返回 None（不抛）。
- 物理中立：键只含传入要素，不 import 任何案例模块。
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "env"))

from csol_kit import SolvePool  # noqa: E402


class SolvePoolTests(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.pool = SolvePool(Path(self.td.name) / "pool")
        self.phys = {"files": {"m.py": "abc"}, "rev": "r1"}
        self.calc = {"study": "frequency", "mesh": "medium"}
        self.geom = {"g": 1.0, "w": 2.0}
        self.freq = "range(1,0.1,2)[THz]"

    def tearDown(self):
        self.td.cleanup()

    def test_key_stable_and_order_independent(self):
        k1 = self.pool.key(self.phys, self.calc, self.geom, self.freq)
        k2 = self.pool.key(self.phys, dict(reversed(list(self.calc.items()))),
                           dict(reversed(list(self.geom.items()))), self.freq)
        self.assertEqual(k1, k2)

    def test_any_element_changes_key(self):
        base = self.pool.key(self.phys, self.calc, self.geom, self.freq)
        self.assertNotEqual(base, self.pool.key({"rev": "r2"}, self.calc, self.geom, self.freq))
        self.assertNotEqual(base, self.pool.key(self.phys, {"study": "eigen"}, self.geom, self.freq))
        self.assertNotEqual(base, self.pool.key(self.phys, self.calc, {"g": 9.0}, self.freq))
        self.assertNotEqual(base, self.pool.key(self.phys, self.calc, self.geom, "other"))

    def test_put_get_roundtrip(self):
        k = self.pool.key(self.phys, self.calc, self.geom, self.freq)
        self.assertIsNone(self.pool.get(k))
        self.pool.put(k, "spectrum", {"spectrum": {"A": [0.1, 0.9]}}, {"geom": self.geom})
        hit = self.pool.get(k)
        self.assertEqual(hit["kind"], "spectrum")
        self.assertEqual(hit["spectrum"]["A"], [0.1, 0.9])

    def test_corrupt_entry_returns_none(self):
        k = self.pool.key(self.phys, self.calc, self.geom, self.freq)
        self.pool.put(k, "spectrum", {"spectrum": {}})
        p = self.pool.dir / (k + ".json")
        p.write_text("{corrupt", encoding="utf-8")
        self.assertIsNone(self.pool.get(k))

    def test_no_case_imports(self):
        import inspect
        import csol_kit
        src = inspect.getsource(csol_kit.SolvePool)
        self.assertNotIn("case_spec", src)
        self.assertNotIn("paths", src)


if __name__ == "__main__":
    unittest.main()