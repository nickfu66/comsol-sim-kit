import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "tools"))

from check_public import run_offline_tests, scan_public_tree  # noqa: E402
import publish  # noqa: E402
from publish import staged_content_problems, target_branch_matches, validate_public_path  # noqa: E402


class CredentialRecognitionTests(unittest.TestCase):
    def test_unquoted_yaml_common_tokens_and_private_keys_fail(self):
        samples = [
            "api_" + "key=1234567890abcdef",
            "to" + "ken: abcdef1234567890",
            "gh" + "p_abcdefghijklmnop",
            "github" + "_pat_abcdefghijklmnop",
            "-----BEGIN " + "PRIVATE KEY-----",
        ]
        for sample in samples:
            with self.subTest(sample=sample):
                with tempfile.TemporaryDirectory() as td:
                    root = Path(td)
                    (root / "note.txt").write_text(sample, encoding="utf-8")
                    self.assertTrue(scan_public_tree(root))

    def test_sensitive_filename_is_rejected_even_with_safe_content(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "env").mkdir()
            (root / "env" / "credentials.txt").write_text("placeholder", encoding="utf-8")
            self.assertTrue(any("敏感文件名" in item for item in scan_public_tree(root)))


class StagedContentTests(unittest.TestCase):
    def test_staged_blob_scan_catches_secret_and_tracked_runtime_file(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            (root / "env" / ".runtime").mkdir(parents=True)
            secret = "api_" + "key=1234567890abcdef"
            (root / "env" / "credentials.txt").write_text(secret, encoding="utf-8")
            (root / "env" / ".runtime" / "tracked.py").write_text("x = 1\n", encoding="utf-8")
            subprocess.run(["git", "add", "env/credentials.txt"], cwd=root, check=True)
            subprocess.run(["git", "add", "-f", "env/.runtime/tracked.py"], cwd=root, check=True)
            problems = staged_content_problems(root)
            joined = "\n".join(problems)
            self.assertIn("credentials.txt", joined)
            self.assertIn(".runtime", joined)

    def test_allowlist_rejects_forbidden_directories_and_sensitive_files(self):
        denied = [
            "env/.runtime/tracked.py", "env/__pycache__/tracked.py",
            "env/credentials.txt", "env/model.mph", "env/nested/work/file.py",
        ]
        for path in denied:
            self.assertFalse(validate_public_path(path), path)

    def test_offline_test_runner_does_not_create_bytecode(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "tests").mkdir()
            (root / "tests" / "test_ok.py").write_text(
                "import unittest\nclass T(unittest.TestCase):\n"
                "    def test_ok(self): self.assertTrue(True)\n",
                encoding="utf-8",
            )
            result = run_offline_tests(root)
            self.assertEqual(result.returncode, 0)
            self.assertFalse((root / "tests" / "__pycache__").exists())


class FullIndexAndTemplateBoundaryTests(unittest.TestCase):
    def test_full_index_catches_preexisting_sensitive_files(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=root, check=True)
            (root / "config").mkdir()
            secret = "api_" + "key=1234567890abcdef"
            (root / "config" / "config.toml").write_text(secret, encoding="utf-8")
            (root / "SIM01_private").mkdir()
            (root / "SIM01_private" / "task.md").write_text("private", encoding="utf-8")
            (root / "README.md").write_text("v1", encoding="utf-8")
            subprocess.run(["git", "add", "."], cwd=root, check=True)
            subprocess.run(["git", "commit", "-qm", "baseline"], cwd=root, check=True)
            (root / "README.md").write_text("v2", encoding="utf-8")
            subprocess.run(["git", "add", "README.md"], cwd=root, check=True)
            problems = staged_content_problems(root)
            joined = "\n".join(problems)
            self.assertIn("config/config.toml", joined)
            self.assertIn("SIM01_private/task.md", joined)

    def test_sensitive_file_deletion_is_allowed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=root, check=True)
            (root / "config").mkdir()
            (root / "config" / "config.toml").write_text("private", encoding="utf-8")
            (root / "README.md").write_text("safe", encoding="utf-8")
            subprocess.run(["git", "add", "."], cwd=root, check=True)
            subprocess.run(["git", "commit", "-qm", "baseline"], cwd=root, check=True)
            subprocess.run(["git", "rm", "-q", "config/config.toml"], cwd=root, check=True)
            self.assertEqual(staged_content_problems(root), [])
            self.assertEqual(publish.main(["--root", str(root), "--skip-tests"]), 0)

    def test_env_log_pdf_and_unknown_assets_are_default_denied(self):
        samples = ["env/.env.production", "env/private.log", "env/docs/private.pdf"]
        for sample in samples:
            with self.subTest(sample=sample):
                with tempfile.TemporaryDirectory() as td:
                    root = Path(td)
                    target = root / sample
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(b"not empty")
                    self.assertTrue(scan_public_tree(root))
                    self.assertFalse(validate_public_path(sample))

    def test_template_results_are_rejected_but_blank_structure_is_allowed(self):
        denied = [
            "templates/case/03_结果/数据/values.json",
            "templates/case/03_结果/数据/工况_C0.json",
            "templates/case/03_结果/数据/证据快照/x/verdict.json",
            "templates/case/03_结果/图片/C0.png",
            "templates/case/02_过程代码/探针/result.json",
        ]
        for path in denied:
            self.assertFalse(validate_public_path(path), path)
        allowed = [
            "templates/case/03_结果/数据/results_manifest.json",
            "templates/case/03_结果/_结果说明.md",
            "templates/case/03_结果/图片/.gitkeep",
        ]
        for path in allowed:
            self.assertTrue(validate_public_path(path), path)
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            result = root / "templates/case/03_结果/数据/values.json"
            result.parent.mkdir(parents=True)
            result.write_text('{"values": {"C0.K1": 1}}', encoding="utf-8")
            self.assertTrue(any("templates" in item for item in scan_public_tree(root)))

    def test_push_target_must_be_current_branch(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            subprocess.run(["git", "init", "-q", "-b", "dev"], cwd=root, check=True)
            self.assertFalse(target_branch_matches(root, "main"))
            self.assertTrue(target_branch_matches(root, "dev"))


if __name__ == "__main__":
    unittest.main()
