import sys
import tempfile
import unittest
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "tools"))

from check_public import scan_public_tree  # noqa: E402
from publish import validate_public_path  # noqa: E402


class PublicScanTests(unittest.TestCase):
    def test_clean_generic_file_passes(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "README.md").write_text("# generic framework", encoding="utf-8")
            self.assertEqual(scan_public_tree(root), [])

    def test_private_path_model_and_legacy_marker_fail(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            private_path = "C:" + "/" + "Users" + "/" + "private-user" + "/task/file.py"
            (root / "path.md").write_text(private_path, encoding="utf-8")
            (root / "model.mph").write_bytes(b"private")
            legacy = "comsol" + "-mcp-test"
            (root / "legacy.md").write_text(legacy, encoding="utf-8")
            problems = scan_public_tree(root)
            self.assertGreaterEqual(len(problems), 3)
            joined = "\n".join(problems)
            self.assertIn("私人路径", joined)
            self.assertIn("禁止公开的文件类型", joined)
            self.assertIn("历史项目标记", joined)

    def test_local_case_directories_are_not_public_candidates(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            case = root / "SIM01_private" / "01_建模"
            case.mkdir(parents=True)
            (case / "model.mph").write_bytes(b"private")
            (root / "README.md").write_text("generic", encoding="utf-8")
            self.assertEqual(scan_public_tree(root), [])

    def test_local_navigation_is_not_public_content(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            private_path = "C:" + "/" + "Users" + "/" + "private-user" + "/task"
            (root / "README_任务导航.local.md").write_text(private_path, encoding="utf-8")
            self.assertEqual(scan_public_tree(root), [])

    def test_work_and_local_directories_are_not_part_of_public_layout(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "work").mkdir()
            (root / "local").mkdir()
            problems = scan_public_tree(root)
            self.assertEqual(len(problems), 2)

    def test_secret_assignment_fails(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            secret = "api_key" + ' = "1234567890abcdef"'
            (root / "secret.txt").write_text(secret, encoding="utf-8")
            self.assertTrue(any("疑似密钥" in item for item in scan_public_tree(root)))


class PublishAllowlistTests(unittest.TestCase):
    def test_only_public_paths_are_publishable(self):
        allowed = [
            "README.md", "./README.md", "env/csol_kit.py", "templates/case/paths.py",
            "config/config.example.toml", "tools/new_case.py", "tests/test_gate.py",
        ]
        for path in allowed:
            self.assertTrue(validate_public_path(path), path)
        denied = [
            "SIM01_private/model.mph", "config/config.toml", ".runtime/state",
            "work/SIM01/task.md", "local/config.toml", "../outside.md",
            "/env/csol_kit.py", "../README.md", "./../README.md", "..\\README.md",
        ]
        for path in denied:
            self.assertFalse(validate_public_path(path), path)


if __name__ == "__main__":
    unittest.main()
