"""三层语义指纹 + 逐点持久化续跑的离线测试（先写失败测试再实现）。

契约：
- layered_fingerprint(physics_files, calc, postproc_files, runtime) 返回
  {"physics": {...}, "calc": {...}, "postproc": {...}, "runtime": {...}}；
  编排文件不在任何层 -> 改它不作废结果。
- fingerprint_status(old, new) 分级判定：
  physics/calc 变 -> "rerun"；仅 postproc 变 -> "repost"；全同 -> "current"。
- ProgressLog：JSONL append/flush；坏行逐行跳过保留其余；
  按指纹过滤（fp 一致复用、fp 不符丢弃、无 fp 行按 legacy 约定接受）。
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "env"))

from csol_kit import (  # noqa: E402
    ProgressLog,
    fingerprint_status,
    layered_fingerprint,
)


class LayeredFingerprintTests(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.root = Path(self.td.name)
        self.phys = self.root / "physics.py"
        self.post = self.root / "postproc.py"
        self.orch = self.root / "runner.py"
        self.phys.write_text("a = 1\n", encoding="utf-8")
        self.post.write_text("b = 2\n", encoding="utf-8")
        self.orch.write_text("c = 3\n", encoding="utf-8")

    def tearDown(self):
        self.td.cleanup()

    def fp(self, calc=None):
        return layered_fingerprint(
            physics_files={"physics.py": self.phys},
            calc=calc or {"points": [1, 2]},
            postproc_files={"postproc.py": self.post},
            runtime={"comsol": "x"})

    def test_orchestration_change_invalidates_nothing(self):
        first = self.fp()
        self.orch.write_text("c = 999\n", encoding="utf-8")
        self.assertEqual(fingerprint_status(first, self.fp()), "current")

    def test_calc_change_only_reruns_that_case(self):
        base = self.fp()
        other = self.fp(calc={"points": [1, 2, 3]})
        self.assertEqual(fingerprint_status(base, other), "rerun")
        # 另一工况 calc 不变 -> 不受影响
        self.assertEqual(fingerprint_status(base, self.fp()), "current")

    def test_physics_change_invalidates_all(self):
        base = self.fp()
        self.phys.write_text("a = 42\n", encoding="utf-8")
        self.assertEqual(fingerprint_status(base, self.fp()), "rerun")

    def test_postproc_only_change_means_repost(self):
        base = self.fp()
        self.post.write_text("b = 99\n", encoding="utf-8")
        self.assertEqual(fingerprint_status(base, self.fp()), "repost")

    def test_missing_dependency_raises(self):
        from csol_kit import CsolError
        with self.assertRaises(CsolError):
            layered_fingerprint(
                physics_files={"gone.py": self.root / "gone.py"},
                calc={}, postproc_files={}, runtime={})


class ProgressLogTests(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.path = Path(self.td.name) / "progress.jsonl"

    def tearDown(self):
        self.td.cleanup()

    def test_roundtrip(self):
        log = ProgressLog(self.path)
        log.append({"point": {"x": 1}, "value": 0.5}, fp={"p": "A"})
        log.append({"point": {"x": 2}, "value": 0.6}, fp={"p": "A"})
        done = log.load(fp={"p": "A"})
        self.assertEqual(len(done), 2)
        self.assertEqual(done[json.dumps({"x": 1}, sort_keys=True)]["value"], 0.5)

    def test_truncated_last_line_skipped_others_kept(self):
        log = ProgressLog(self.path)
        log.append({"point": {"x": 1}, "value": 0.5}, fp={"p": "A"})
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write('{"point": {"x": 2}, "val')   # 截断的末行
        done = log.load(fp={"p": "A"})
        self.assertEqual(len(done), 1)   # 坏行跳过，好行保留

    def test_fingerprint_mismatch_dropped(self):
        log = ProgressLog(self.path)
        log.append({"point": {"x": 1}, "value": 0.5}, fp={"p": "OLD"})
        done = log.load(fp={"p": "NEW"})
        self.assertEqual(len(done), 0)

    def test_legacy_rows_without_fp_accepted(self):
        log = ProgressLog(self.path)
        log.append({"point": {"x": 1}, "value": 0.5}, fp=None)  # 无指纹行
        done = log.load(fp={"p": "NEW"})
        self.assertEqual(len(done), 1)   # 冻结版约定：接受


if __name__ == "__main__":
    unittest.main()