import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "env"))
sys.path.insert(0, str(PROJECT / "tools"))

from new_case import create_case  # noqa: E402


class CaseCreationTests(unittest.TestCase):
    def test_creates_sequential_blank_cases(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            first = create_case("示例任务", root=root)
            second = create_case("next-case", root=root)
            self.assertEqual(first.name, "SIM01_示例任务")
            self.assertEqual(second.name, "SIM02_next-case")
            navigation = root / "README_任务导航.local.md"
            self.assertTrue(navigation.is_file())
            navigation.write_text("private navigation", encoding="utf-8")
            third = create_case("third", root=root)
            self.assertEqual(third.name, "SIM03_third")
            self.assertEqual(navigation.read_text(encoding="utf-8"), "private navigation")
            for case in (first, second):
                self.assertTrue((case / "01_建模" / "_建模说明.md").is_file())
                self.assertTrue((case / "02_过程代码" / "探针").is_dir())
                self.assertTrue((case / "02_过程代码" / "日志").is_dir())
                self.assertTrue((case / "03_结果" / "图片").is_dir())
                spec = json.loads((case / "quality_spec.json").read_text(encoding="utf-8"))
                self.assertEqual(spec["case"], case.name)
                self.assertEqual(spec["criteria"], [])
                self.assertEqual(spec["spec_sha256"], "")

    def test_cli_does_not_offer_broken_external_root(self):
        result = subprocess.run(
            [sys.executable, str(PROJECT / "tools" / "new_case.py"), "--help"],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0)
        self.assertNotIn("--root", result.stdout)

    def test_never_overwrites_existing_directory(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            existing = root / "SIM01_示例"
            existing.mkdir()
            marker = existing / "keep.txt"
            marker.write_text("keep", encoding="utf-8")
            created = create_case("示例", root=root)
            self.assertEqual(created.name, "SIM02_示例")
            self.assertEqual(marker.read_text(encoding="utf-8"), "keep")

    def test_rejects_path_traversal_and_empty_names(self):
        with tempfile.TemporaryDirectory() as td:
            for name in ("", "../escape", "a/b", "a\\b"):
                with self.subTest(name=name), self.assertRaises(ValueError):
                    create_case(name, root=Path(td))

    def test_template_has_no_default_cases_or_physics(self):
        with tempfile.TemporaryDirectory() as td:
            case = create_case("blank", root=Path(td))
            spec_path = case / "02_过程代码" / "case_spec.py"
            module_spec = importlib.util.spec_from_file_location("blank_case_spec", spec_path)
            module = importlib.util.module_from_spec(module_spec)
            module_spec.loader.exec_module(module)
            self.assertEqual(dict(module.CASES), {})
            self.assertEqual(module.RESET_PARAMS, ())
            self.assertEqual(module.case_names(), ())
            common = (case / "02_过程代码" / "model_common.py").read_text(encoding="utf-8")
            self.assertIn("NotImplementedError", common)


if __name__ == "__main__":
    unittest.main()
