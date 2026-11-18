import json
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "env"))
sys.path.insert(0, str(PROJECT / "env" / "ctl"))

import comsol_boot as boot  # noqa: E402
import check  # noqa: E402
from csol_kit import atomic_write_json  # noqa: E402


class ConfigTests(unittest.TestCase):
    def make_config(self, root):
        config_dir = root / "config"
        config_dir.mkdir(parents=True)
        path = config_dir / "config.toml"
        comsol_root = root / "fake_comsol" / "Multiphysics"
        path.write_text(
            f'comsol_root = {json.dumps(str(comsol_root))}\n'
            'version = "6.3"\n'
            'build = 290\n'
            'cores = 4\n'
            'state_dir = ".runtime/comsol_home"\n',
            encoding="utf-8",
        )
        return path

    def test_load_config_resolves_relative_state_from_project_root(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            path = self.make_config(root)
            config = boot.load_config(path, project_root=root)
            self.assertEqual(config["cores"], 4)
            self.assertEqual(config["state_dir"], root / ".runtime" / "comsol_home")
            self.assertEqual(
                config["jvm_dll"],
                root / "fake_comsol" / "Multiphysics" / "java/win64/jre/bin/server/jvm.dll",
            )

    def test_all_relative_install_paths_use_project_root(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            path = root / "config" / "config.toml"
            path.parent.mkdir()
            path.write_text(
                'comsol_root = "fake_comsol"\njvm_dll = "jvm/custom.dll"\n'
                'server = "bin/custom-server"\nstate_dir = "state"\n',
                encoding="utf-8",
            )
            config = boot.load_config(path, project_root=root)
            self.assertEqual(config["comsol_root"], root / "fake_comsol")
            self.assertEqual(config["jvm_dll"], root / "jvm" / "custom.dll")
            self.assertEqual(config["server"], root / "bin" / "custom-server")
            self.assertEqual(config["state_dir"], root / "state")

    def test_missing_config_has_actionable_error(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaisesRegex(boot.BootConfigError, "config.example.toml"):
                boot.load_config(Path(td) / "missing.toml", project_root=Path(td))

    def test_module_import_is_comsol_lazy(self):
        self.assertFalse(hasattr(boot, "mph"))
        self.assertFalse(hasattr(boot, "jpype"))

    def test_runtime_metadata_includes_numpy_platform_and_actual_build(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            path = self.make_config(root)
            metadata = boot.runtime_metadata(path)
            self.assertIn("numpy", metadata)
            self.assertIn("platform", metadata)
            verified = boot.runtime_metadata(path, actual_version="6.3.0.290")
            self.assertEqual(verified["comsol_actual"], "6.3.0.290")
            short = boot.runtime_metadata(path, actual_version="6.3")
            self.assertFalse(short["comsol_build_verified"])
            with self.assertRaises(boot.BootConfigError):
                boot.runtime_metadata(path, actual_version="6.3.0.291")

    def test_validate_config_checks_jvm_and_writable_state(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            path = self.make_config(root)
            config = boot.load_config(path, project_root=root)
            problems = boot.validate_config(config)
            self.assertTrue(any("jvm" in item.lower() for item in problems))
            jvm = config["jvm_dll"]
            jvm.parent.mkdir(parents=True)
            jvm.write_bytes(b"placeholder")
            self.assertEqual(boot.validate_config(config), [])
            self.assertTrue(config["state_dir"].is_dir())


class LintAndCliTests(unittest.TestCase):
    def test_lint_rejects_literal_and_dynamic_create_but_allows_guard(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "bad.py").write_text(
                'mesh.create("swe1", "Sweep")\n'
                'mesh.create(tag, dynamic_type)\n'
                'mesh.create("ft1", "Free" + "Tet")\n',
                encoding="utf-8",
            )
            (root / "good.py").write_text(
                'create_checked(mesh, "swe1", "Sweep", "mesh")\n',
                encoding="utf-8",
            )
            problems = check.lint_tree(root)
            self.assertEqual(len(problems), 3)
            self.assertTrue(all("bad.py" in problem for problem in problems))

    def test_public_markdown_files_exclude_local_cases_and_runtime(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "public.md").write_text("# public", encoding="utf-8")
            private = root / "SIM01_private"
            private.mkdir()
            (private / "bad.md").write_text("[bad](missing.md)", encoding="utf-8")
            runtime = root / ".runtime"
            runtime.mkdir()
            (runtime / "bad.md").write_text("[bad](missing.md)", encoding="utf-8")
            (root / "README_任务导航.local.md").write_text("[bad](missing.md)", encoding="utf-8")
            self.assertEqual(
                [path.name for path in check.public_markdown_files(root)],
                ["public.md"],
            )

    def test_markdown_links_skip_external_and_anchor(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "doc.md").write_text(
                "[ok](other.md) [web](https://example.com) [anchor](#part) [bad](missing.md)",
                encoding="utf-8",
            )
            (root / "other.md").write_text("# ok", encoding="utf-8")
            problems = check.markdown_link_problems(root / "doc.md")
            self.assertEqual(len(problems), 1)
            self.assertIn("missing.md", problems[0])

    def valid_case(self, root):
        case = root / "SIM01_test"
        case.mkdir()
        spec = {
            "case": "SIM01_test",
            "source": {"type": "任务书", "ref": "§1"},
            "criteria": [{
                "id": "C0.K1", "metric": "误差", "op": "<=", "value": 1,
                "blocking": True, "source": "§1", "category": "other", "unit": "",
            }],
            "spec_sha256": "", "frozen_at": "",
        }
        atomic_write_json(case / "quality_spec.json", spec)
        atomic_write_json(case / "values.json", {"K1": 0.0})
        return case

    def test_gate_cli_freeze_then_formal_acceptance(self):
        with tempfile.TemporaryDirectory() as td:
            case = self.valid_case(Path(td))
            values = case / "values.json"
            rc = check.main(["gate", "--sim", str(case), "--values", str(values)])
            self.assertEqual(rc, 1)
            rc = check.main(["gate", "--sim", str(case), "--freeze"])
            self.assertEqual(rc, 2)
            rc = check.main(["gate", "--sim", str(case), "--freeze", "--emit"])
            self.assertEqual(rc, 0)
            spec = json.loads((case / "quality_spec.json").read_text(encoding="utf-8"))
            self.assertTrue(spec["spec_sha256"])
            atomic_write_json(values, {
                "values": {"C0.K1": 0.0},
                "provenance": {
                    "complete": True, "spec_sha256": spec["spec_sha256"], "cases": ["C0"],
                },
            })
            rc = check.main(["gate", "--sim", str(case), "--values", str(values)])
            self.assertEqual(rc, 0)
            self.assertEqual(list(case.glob("03_结果/**/*")), [])

    def test_bundle_requires_emit(self):
        with tempfile.TemporaryDirectory() as td:
            case = self.valid_case(Path(td))
            rc = check.main(["gate", "--sim", str(case), "--bundle"])
            self.assertEqual(rc, 2)


if __name__ == "__main__":
    unittest.main()
