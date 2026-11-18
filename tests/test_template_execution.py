import importlib.util
import json
import shutil
import sys
import tempfile
import types
import unittest
from pathlib import Path
from types import MappingProxyType
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "env"))
sys.path.insert(0, str(PROJECT / "env" / "ctl"))
sys.path.insert(0, str(PROJECT / "tools"))

import check  # noqa: E402
from csol_kit import aggregate_case_results, result_is_current, sha256_file  # noqa: E402
from new_case import create_case  # noqa: E402
from quality import freeze_spec  # noqa: E402


class FakeStat:
    def getNumElem(self):
        return 8


class FakeMesh:
    def run(self):
        pass

    def stat(self):
        return FakeStat()


class FakeModel:
    def __init__(self):
        self.solved = []

    def save(self, path):
        Path(path).write_text(f"model:{len(self.solved)}", encoding="utf-8")

    def solve(self, study):
        self.solved.append(study)

    def evaluate(self, expr, unit=None):
        return [0.5]

    def version(self):
        return "6.3.0.290"


class FakeClient:
    def __init__(self):
        self.removed = []

    def remove(self, model):
        self.removed.append(model)


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TemplateExecutionTests(unittest.TestCase):
    def test_fake_comsol_case_to_default_gate(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            case = create_case("demo", root=root)
            (root / "env").mkdir()
            for name in ("csol_kit.py", "comsol_boot.py", "api_registry.py"):
                shutil.copyfile(PROJECT / "env" / name, root / "env" / name)
            (root / "config").mkdir()
            (root / "config" / "config.toml").write_text(
                'comsol_root = "fake"\nversion = "6.3"\nbuild = 290\ncores = 1\n',
                encoding="utf-8",
            )
            code = case / "02_过程代码"
            sys.path.insert(0, str(root / "env"))
            sys.path.insert(0, str(code))
            self.addCleanup(sys.path.remove, str(root / "env"))
            self.addCleanup(sys.path.remove, str(code))

            case_spec = load_module("case_spec_under_test", code / "case_spec.py")
            case_spec.CASES = MappingProxyType({"C0": MappingProxyType({"p": "2"})})
            case_spec.RESET_PARAMS = (("p", "1"),)

            model = FakeModel()
            client = FakeClient()
            calls = {}
            model_common = types.ModuleType("model_common")

            def build_model(client_arg, case_name, parameters, reset_params):
                calls.update({"case": case_name, "parameters": parameters, "reset": reset_params})
                return {"model": model, "mesh": FakeMesh(), "study": "std1", "probes": {"K1": "K1"}}

            model_common.build_model = build_model
            with patch.dict(sys.modules, {"case_spec": case_spec, "model_common": model_common}):
                with patch("comsol_boot.start_client", return_value=client):
                    runner = load_module("runner_under_test", code / "run_case_one.py")
                    with patch.object(sys, "argv", ["run_case_one.py", "--case", "C0"]):
                        self.assertEqual(runner.main(), 0)

            self.assertEqual(calls["reset"], (("p", "1"),))
            self.assertEqual(calls["parameters"], {"p": "2"})
            main_model = case / "01_建模" / "main_C0.mph"
            solved_model = case / "01_建模" / "solved_C0.mph"
            self.assertTrue(main_model.is_file())
            self.assertTrue(solved_model.is_file())
            result_path = case / "03_结果" / "数据" / "工况_C0.json"
            result = json.loads(result_path.read_text(encoding="utf-8"))
            self.assertEqual(result["model_files"]["main"]["path"], "01_建模/main_C0.mph")
            self.assertEqual(result["model_files"]["main"]["sha256"], sha256_file(main_model))
            self.assertEqual(result["runtime"]["comsol_version"], "6.3")
            self.assertEqual(client.removed, [model])

            current = case_spec.fingerprint("C0")
            self.assertEqual(result_is_current(result_path, current, require_models=True), (True, "指纹一致"))
            kit_path = root / "env" / "csol_kit.py"
            original_kit = kit_path.read_bytes()
            kit_path.write_bytes(original_kit + b"\n# changed\n")
            self.assertFalse(result_is_current(result_path, case_spec.fingerprint("C0"), require_models=True)[0])
            kit_path.write_bytes(original_kit)

            spec_path = case / "quality_spec.json"
            quality = json.loads(spec_path.read_text(encoding="utf-8"))
            quality["source"] = {"type": "任务书", "ref": "§1", "confirmed_by": "测试"}
            quality["criteria"] = [{
                "id": "C0.K1", "metric": "测试判据", "op": "<=", "value": 1,
                "unit": "", "blocking": True, "source": "§1", "category": "other",
            }]
            spec_path.write_text(json.dumps(quality, ensure_ascii=False), encoding="utf-8")
            frozen = freeze_spec(spec_path)
            self.assertEqual(result["_fingerprints"], case_spec.fingerprint("C0"))
            aggregate_case_results(
                case / "03_结果" / "数据",
                expected_cases=case_spec.case_names(),
                validator=lambda path, case: result_is_current(
                    path, case_spec.fingerprint(case), require_models=True
                ),
                spec_sha256=frozen["spec_sha256"],
            )
            values = json.loads((case / "03_结果" / "数据" / "values.json").read_text(encoding="utf-8"))
            self.assertEqual(values["values"], {"C0.K1": 0.5})
            manifest = json.loads((case / "03_结果" / "数据" / "results_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["cases"][0]["model_files"]["main"]["sha256"], result["model_files"]["main"]["sha256"])
            self.assertEqual(check.main(["gate", "--sim", str(case), "--bundle", "--emit"]), 0)
            bundles = list((case / "03_结果" / "数据" / "证据快照").iterdir())
            self.assertEqual(len(bundles), 1)

            result["_fingerprints"] = {"stale": True}
            result_path.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
            from csol_kit import CsolError
            with self.assertRaises(CsolError):
                aggregate_case_results(
                    case / "03_结果" / "数据",
                    expected_cases=case_spec.case_names(),
                    validator=lambda path, case: result_is_current(
                        path, case_spec.fingerprint(case), require_models=True
                    ),
                    spec_sha256=frozen["spec_sha256"],
                )
            self.assertEqual(check.main(["gate", "--sim", str(case)]), 1)


if __name__ == "__main__":
    unittest.main()
