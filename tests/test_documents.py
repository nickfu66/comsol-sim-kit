import json
import sys
import unittest
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "env" / "ctl"))
sys.path.insert(0, str(PROJECT / "env"))

import check  # noqa: E402
from quality import evaluate_gate  # noqa: E402


class DocumentationTests(unittest.TestCase):
    def test_three_layer_documents_and_navigation_exist(self):
        required = [
            "README.md", "开工指令.md", "env/_README_环境说明.md",
            "env/HANDOVER_环境交接卡.md", "env/docs/能力契约与扩展登记.md",
            "templates/README_任务导航.template.md",
        ]
        for name in required:
            self.assertTrue((PROJECT / name).is_file(), name)

    def test_kickoff_has_three_general_prompts_and_real_commands(self):
        text = (PROJECT / "开工指令.md").read_text(encoding="utf-8")
        first = text.split("## §1", 1)[1].split("## §2", 1)[0]
        second = text.split("## §2", 1)[1].split("## §3", 1)[0]
        third = text.split("## §3", 1)[1]
        for marker in ("preflight", "lint", "--freeze --emit", "--bundle --emit"):
            self.assertIn(marker, first)
        self.assertIn("只做仿真", first)
        self.assertIn("不得修改公共", first)
        self.assertIn("README/env/templates/tools/tests", first)
        self.assertIn("可复用方法候选", first)
        self.assertNotIn("publish.py", first)
        self.assertIn("反向更新与整理", second)
        self.assertIn("不得执行 git add/commit/push", second)
        self.assertIn("不得运行 publish.py", second)
        self.assertIn("已验证、可复用、物理中立", second)
        self.assertIn("上传§2", third)
        self.assertIn("python tools/check_public.py", third)
        self.assertIn("python tools/publish.py", third)
        self.assertIn("--yes", third)
        self.assertIn("git diff", third)

    def test_readme_defines_maintainer_only_updates_and_download_use(self):
        text = (PROJECT / "README.md").read_text(encoding="utf-8")
        self.assertIn("维护者", text)
        self.assertIn("下载", text)
        self.assertIn("不接受外部 Pull Request", text)
        self.assertNotIn("自用副本", text)

    def test_navigation_template_has_no_real_cases_or_results(self):
        text = (PROJECT / "templates" / "README_任务导航.template.md").read_text(encoding="utf-8")
        for heading in ("仿真任务总体结构", "仿真任务一览", "演进关系", "核心结果速查", "引用与封堵规则"):
            self.assertIn(heading, text)
        self.assertIn("<待填写>", text)
        for legacy_number in ("43." + "5207", "557." + "14", "215." + "44", "50." + "8 mm"):
            self.assertNotIn(legacy_number, text)

    def test_all_markdown_local_links_resolve(self):
        problems = []
        for path in check.public_markdown_files(PROJECT):
            problems.extend(check.markdown_link_problems(path))
        self.assertEqual(problems, [])

    def test_blank_template_is_blocked_by_gate(self):
        spec = json.loads((PROJECT / "templates" / "case" / "quality_spec.json").read_text(encoding="utf-8"))
        verdict = evaluate_gate(spec, {})
        self.assertFalse(verdict["admissible"])

    def test_no_work_or_local_directory_in_public_layout(self):
        self.assertFalse((PROJECT / "work").exists())
        self.assertFalse((PROJECT / "local").exists())


if __name__ == "__main__":
    unittest.main()
