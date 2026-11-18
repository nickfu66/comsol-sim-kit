import copy
import json
import math
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "env"))
sys.path.insert(0, str(PROJECT / "env" / "ctl"))

from csol_kit import atomic_write_json  # noqa: E402
from quality import (  # noqa: E402
    canonical_spec_sha256,
    evaluate_gate,
    freeze_spec,
    write_evidence_bundle,
)


def unfrozen_spec():
    return {
        "schema_version": 1,
        "case": "CASE_TEST",
        "spec_version": "1.0",
        "frozen_at": "",
        "spec_sha256": "",
        "source": {"type": "任务书", "ref": "任务书 §3", "confirmed_by": "维护者"},
        "criteria": [
            {
                "id": "K1", "metric": "闭合误差", "op": "<=", "value": 1.0,
                "unit": "%", "blocking": True, "source": "任务书 §3.1",
                "category": "conservation",
            },
            {
                "id": "R1", "metric": "观察量", "op": "report", "value": None,
                "unit": "", "blocking": False, "source": "任务书 §3.2",
                "category": "other",
            },
        ],
        "assumed_params": [],
    }


def frozen(spec):
    result = copy.deepcopy(spec)
    result["frozen_at"] = "2026-01-01T00:00:00+00:00"
    result["spec_sha256"] = canonical_spec_sha256(result)
    return result


def valid_spec():
    return frozen(unfrozen_spec())


class GateTests(unittest.TestCase):
    def test_pass_and_record(self):
        verdict = evaluate_gate(valid_spec(), {"K1": 0.25, "R1": 42})
        self.assertTrue(verdict["admissible"])
        self.assertEqual(verdict["results"][0]["status"], "PASS")
        self.assertEqual(verdict["results"][1]["status"], "RECORD")

    def test_blocking_fail_and_missing_value_block(self):
        failed = evaluate_gate(valid_spec(), {"K1": 2.0})
        self.assertFalse(failed["admissible"])
        self.assertIn("K1", [item["id"] for item in failed["blocked"]])
        missing = evaluate_gate(valid_spec(), {})
        self.assertFalse(missing["admissible"])
        self.assertEqual(missing["results"][0]["status"], "NOT_EVALUATED")

    def test_empty_criteria_cannot_pass(self):
        spec = unfrozen_spec()
        spec["criteria"] = []
        verdict = evaluate_gate(frozen(spec), {})
        self.assertFalse(verdict["admissible"])
        self.assertIn("SPEC_EMPTY", [item["id"] for item in verdict["blocked"]])

    def test_nonblocking_failure_does_not_block(self):
        spec = unfrozen_spec()
        spec["criteria"][1].update({"op": "<", "value": 10})
        verdict = evaluate_gate(frozen(spec), {"K1": 0.0, "R1": 20})
        self.assertTrue(verdict["admissible"])
        self.assertEqual(verdict["results"][1]["status"], "FAIL")

    def test_invalid_sources_fail(self):
        spec = unfrozen_spec()
        spec["source"] = {"type": "模型自拟", "ref": "参考常见值"}
        verdict = evaluate_gate(frozen(spec), {"K1": 0.0})
        self.assertIn("SPEC_SOURCE", [item["id"] for item in verdict["blocked"]])
        spec = unfrozen_spec()
        spec["criteria"][0]["source"] = ""
        verdict = evaluate_gate(frozen(spec), {"K1": 0.0})
        self.assertFalse(verdict["admissible"])
        spec = unfrozen_spec()
        spec["criteria"][0]["source"] = "模型自拟阈值"
        verdict = evaluate_gate(frozen(spec), {"K1": 0.0})
        self.assertFalse(verdict["admissible"])
        self.assertEqual(verdict["results"][0]["status"], "FAIL")

    def test_report_cannot_bypass_source_or_be_blocking(self):
        spec = unfrozen_spec()
        spec["criteria"][1]["source"] = ""
        verdict = evaluate_gate(frozen(spec), {"K1": 0.0})
        self.assertFalse(verdict["admissible"])
        self.assertEqual(verdict["results"][1]["status"], "FAIL")
        spec = unfrozen_spec()
        spec["criteria"][1]["blocking"] = True
        verdict = evaluate_gate(frozen(spec), {"K1": 0.0})
        self.assertIn("SPEC_INVALID", [item["id"] for item in verdict["blocked"]])

    def test_report_only_is_not_a_formal_acceptance_spec(self):
        spec = unfrozen_spec()
        spec["criteria"] = [spec["criteria"][1]]
        verdict = evaluate_gate(frozen(spec), {"R1": 42})
        self.assertFalse(verdict["admissible"])
        self.assertIn("SPEC_NO_BLOCKING", [item["id"] for item in verdict["blocked"]])

    def test_duplicate_criterion_ids_fail(self):
        spec = unfrozen_spec()
        spec["criteria"].append(copy.deepcopy(spec["criteria"][0]))
        verdict = evaluate_gate(frozen(spec), {"K1": 0.0})
        self.assertIn("SPEC_DUPLICATE_ID", [item["id"] for item in verdict["blocked"]])

    def test_malformed_criteria_fail_closed(self):
        examples = [
            ["not-an-object"],
            [{**unfrozen_spec()["criteria"][0], "blocking": "false"}],
            [{key: value for key, value in unfrozen_spec()["criteria"][0].items() if key != "blocking"}],
            [{key: value for key, value in unfrozen_spec()["criteria"][0].items() if key != "unit"}],
            [{**unfrozen_spec()["criteria"][0], "category": "unknown"}],
        ]
        for criteria in examples:
            with self.subTest(criteria=criteria):
                spec = unfrozen_spec()
                spec["criteria"] = criteria
                verdict = evaluate_gate(frozen(spec), {})
                self.assertFalse(verdict["admissible"])
                self.assertTrue(any(item["id"].startswith("SPEC_") for item in verdict["blocked"]))

    def test_non_object_spec_fails_closed(self):
        for spec in (None, [], "bad"):
            with self.subTest(spec=spec):
                verdict = evaluate_gate(spec, {})
                self.assertFalse(verdict["admissible"])
                self.assertIn("SPEC_INVALID", [item["id"] for item in verdict["blocked"]])

    def test_nonfinite_values_and_thresholds_never_pass(self):
        for op in ("<", "<=", ">", ">=", "==", "!="):
            for value in (float("nan"), float("inf"), "nan", "inf", "-inf"):
                with self.subTest(op=op, value=value):
                    spec = unfrozen_spec()
                    spec["criteria"] = [dict(spec["criteria"][0], op=op, value=0)]
                    verdict = evaluate_gate(frozen(spec), {"K1": value})
                    self.assertFalse(verdict["admissible"])
                    self.assertEqual(verdict["results"][0]["status"], "FAIL")
        for threshold in (float("nan"), "inf"):
            spec = unfrozen_spec()
            spec["criteria"][0]["value"] = threshold
            verdict = evaluate_gate(frozen(spec), {"K1": 0.0})
            self.assertFalse(verdict["admissible"])
            self.assertIn("SPEC_INVALID", [item["id"] for item in verdict["blocked"]])

    def test_unfrozen_spec_is_not_formally_admissible(self):
        verdict = evaluate_gate(unfrozen_spec(), {"K1": 0.0})
        self.assertFalse(verdict["admissible"])
        self.assertIn("SPEC_NOT_FROZEN", [item["id"] for item in verdict["blocked"]])
        precheck = evaluate_gate(unfrozen_spec(), {"K1": 0.0}, require_frozen=False)
        self.assertTrue(precheck["admissible"])

    def test_frozen_hash_detects_tampering_without_self_reference(self):
        spec = valid_spec()
        unchanged = evaluate_gate(spec, {"K1": 0.0})
        self.assertTrue(unchanged["admissible"])
        spec["criteria"][0]["value"] = 99.0
        changed = evaluate_gate(spec, {"K1": 0.0})
        self.assertIn("SPEC_FROZEN", [item["id"] for item in changed["blocked"]])

    def test_freeze_spec_round_trip_and_invalid_freeze(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "quality_spec.json"
            atomic_write_json(path, unfrozen_spec())
            result = freeze_spec(path)
            self.assertTrue(result["spec_sha256"])
            self.assertTrue(result["frozen_at"])
            loaded = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(loaded["spec_sha256"], canonical_spec_sha256(loaded))
            self.assertTrue(evaluate_gate(loaded, {"K1": 0.0})["admissible"])
            atomic_write_json(path, {"source": {}, "criteria": [{"op": "report"}]})
            with self.assertRaises(ValueError):
                freeze_spec(path)

    def test_evidence_bundle_contains_hashes(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            spec_path = root / "quality_spec.json"
            atomic_write_json(spec_path, valid_spec())
            verdict = evaluate_gate(valid_spec(), {"K1": 0.0})
            manifest = write_evidence_bundle(root / "bundle", spec_path, {"K1": 0.0}, verdict)
            self.assertEqual(len(manifest["files"]), 3)
            for item in manifest["files"]:
                self.assertEqual(len(item["sha256"]), 64)
                self.assertTrue((root / "bundle" / item["path"]).is_file())


if __name__ == "__main__":
    unittest.main()
