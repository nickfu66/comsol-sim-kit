import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "env"))
sys.path.insert(0, str(PROJECT / "env" / "ctl"))

from csol_kit import (  # noqa: E402
    CsolError,
    aggregate_case_results,
    atomic_write_json,
    result_is_current,
    sha256_file,
)
from quality import canonical_spec_sha256, evaluate_gate  # noqa: E402


def spec_with_ids(ids=("C0.K1",)):
    spec = {
        "case": "SIM01_test",
        "source": {"type": "任务书", "ref": "§1"},
        "criteria": [{
            "id": identifier, "metric": identifier, "op": "<=", "value": 1,
            "unit": "", "blocking": True, "source": "§1", "category": "other",
        } for identifier in ids],
        "frozen_at": "2026-01-01T00:00:00+00:00",
    }
    spec["spec_sha256"] = canonical_spec_sha256(spec)
    return spec


def valid_values(spec, cases=("C0",)):
    return {
        "values": {f"{case}.K1": 0.5 for case in cases},
        "provenance": {
            "complete": True,
            "spec_sha256": spec["spec_sha256"],
            "cases": list(cases),
        },
    }


class ProvenanceGateTests(unittest.TestCase):
    def test_formal_gate_requires_current_complete_provenance(self):
        spec = spec_with_ids()
        self.assertTrue(evaluate_gate(spec, valid_values(spec), require_provenance=True)["admissible"])
        for mutation in ("flat", "incomplete", "stale_spec", "missing_case"):
            with self.subTest(mutation=mutation):
                if mutation == "flat":
                    values = {"C0.K1": 0.5}
                else:
                    values = valid_values(spec)
                    if mutation == "incomplete":
                        values["provenance"]["complete"] = False
                    elif mutation == "stale_spec":
                        values["provenance"]["spec_sha256"] = "0" * 64
                    elif mutation == "missing_case":
                        values["provenance"]["cases"] = []
                self.assertFalse(evaluate_gate(spec, values, require_provenance=True)["admissible"])

    def test_missing_declared_case_blocks_aggregate(self):
        with tempfile.TemporaryDirectory() as td:
            data = Path(td) / "case" / "03_结果" / "数据"
            data.mkdir(parents=True)
            atomic_write_json(data / "工况_C0.json", {
                "case": "C0", "status": "OK", "values": {"K1": 0.5},
                "model_files": {}, "_fingerprints": {},
            })
            spec = spec_with_ids(("C0.K1", "C1.K1"))
            with self.assertRaises(CsolError):
                aggregate_case_results(
                    data, expected_cases=("C0", "C1"),
                    validator=lambda path, case: (case == "C0", "missing"),
                    spec_sha256=spec["spec_sha256"],
                )
            payload = json.loads((data / "values.json").read_text(encoding="utf-8"))
            self.assertFalse(payload["provenance"]["complete"])
            self.assertEqual(payload["values"], {})

    def test_aggregate_validates_every_declared_case(self):
        with tempfile.TemporaryDirectory() as td:
            data = Path(td) / "case" / "03_结果" / "数据"
            data.mkdir(parents=True)
            spec = spec_with_ids(("C0.K1", "C1.K1"))
            for case in ("C0", "C1"):
                model = data.parents[1] / "01_建模" / f"main_{case}.mph"
                model.parent.mkdir(parents=True, exist_ok=True)
                model.write_text(case, encoding="utf-8")
                solved = model.parent / f"solved_{case}.mph"
                solved.write_text(case + "solved", encoding="utf-8")
                fingerprint = {"case": case}
                atomic_write_json(data / f"工况_{case}.json", {
                    "case": case, "status": "OK", "params": {}, "values": {"K1": 0.5},
                    "model_files": {
                        "main": {"path": f"01_建模/main_{case}.mph", "sha256": sha256_file(model)},
                        "solved": {"path": f"01_建模/solved_{case}.mph", "sha256": sha256_file(solved)},
                    },
                    "_fingerprints": fingerprint,
                })
            payload = aggregate_case_results(
                data, expected_cases=("C0", "C1"),
                validator=lambda path, case: result_is_current(
                    path, {"case": case}, require_models=True
                ),
                spec_sha256=spec["spec_sha256"],
            )
            self.assertTrue(payload["provenance"]["complete"])
            self.assertEqual(payload["values"], {"C0.K1": 0.5, "C1.K1": 0.5})
            self.assertTrue(evaluate_gate(spec, payload, require_provenance=True)["admissible"])

    def test_require_models_rejects_wrong_case_paths(self):
        with tempfile.TemporaryDirectory() as td:
            case = Path(td) / "case"
            data = case / "03_结果" / "数据"
            data.mkdir(parents=True)
            model_files = {}
            for kind in ("main", "solved"):
                wrong = case / "01_建模" / f"{kind}_C1.mph"
                wrong.parent.mkdir(parents=True, exist_ok=True)
                wrong.write_text(kind, encoding="utf-8")
                model_files[kind] = {
                    "path": f"01_建模/{kind}_C1.mph", "sha256": sha256_file(wrong),
                }
            result = data / "工况_C0.json"
            atomic_write_json(result, {
                "case": "C0", "status": "OK", "_fingerprints": {"case": "C0"},
                "model_files": model_files,
            })
            self.assertFalse(result_is_current(result, {"case": "C0"}, require_models=True)[0])

    def test_require_models_demands_main_and_solved(self):
        with tempfile.TemporaryDirectory() as td:
            case = Path(td) / "case"
            data = case / "03_结果" / "数据"
            data.mkdir(parents=True)
            model = case / "01_建模" / "main_C0.mph"
            model.parent.mkdir(parents=True)
            model.write_text("main", encoding="utf-8")
            result = data / "工况_C0.json"
            atomic_write_json(result, {
                "status": "OK", "_fingerprints": {"case": "C0"},
                "model_files": {"main": {"path": "01_建模/main_C0.mph", "sha256": sha256_file(model)}},
            })
            self.assertFalse(result_is_current(result, {"case": "C0"}, require_models=True)[0])


if __name__ == "__main__":
    unittest.main()
