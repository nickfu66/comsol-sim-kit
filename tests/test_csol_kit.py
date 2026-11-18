import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "env"))

from csol_kit import (  # noqa: E402
    CsolError,
    area_avg,
    atomic_write_json,
    axisym_area,
    case_fingerprint,
    check_domains,
    check_mesh,
    check_solution,
    enum_entries,
    ev,
    ev_scalar,
    logger,
    masked_avg,
    mem_gb,
    result_is_current,
    sha256_file,
    sha256_obj,
    solve,
    vol_avg,
)


class FakeStat:
    def __init__(self, count):
        self.count = count

    def getNumElem(self):
        return self.count


class FakeMesh:
    def __init__(self, count):
        self.count = count
        self.runs = 0

    def run(self):
        self.runs += 1

    def stat(self):
        return FakeStat(self.count)


class FakeGeom:
    def __init__(self, count):
        self.count = count

    def getNDomains(self):
        return self.count


class FakeModel:
    def __init__(self, values, failures=0):
        self.values = values
        self.failures = failures
        self.calls = []
        self.solved = []

    def evaluate(self, expr, unit=None, **kwargs):
        self.calls.append((expr, unit, kwargs))
        if "dataset" in kwargs:
            key = (expr, kwargs["dataset"], tuple(kwargs["inner"]))
            if key not in self.values:
                raise ValueError("missing inner solution")
            return self.values[key]
        if expr not in self.values:
            raise ValueError(expr)
        value = self.values[expr]
        if isinstance(value, Exception):
            raise value
        return value

    def solve(self, label):
        if self.failures:
            self.failures -= 1
            raise RuntimeError("transient")
        self.solved.append(label)


class EvalTests(unittest.TestCase):
    def test_ev_normalizes_scalar_and_array(self):
        model = FakeModel({"scalar": [2.5], "array": [1.0, 3.0]})
        self.assertEqual(ev(model, "scalar"), 2.5)
        np.testing.assert_array_equal(ev(model, "array"), [1.0, 3.0])
        with self.assertRaises(CsolError):
            ev_scalar(model, "array")
        self.assertEqual(ev_scalar(model, "array", reducer="max"), 3.0)
        self.assertEqual(ev_scalar(model, "array", reducer="mean"), 2.0)

    def test_ev_scalar_rejects_empty_array(self):
        with self.assertRaises(CsolError):
            ev_scalar(FakeModel({"empty": []}), "empty")


class GuardTests(unittest.TestCase):
    def test_mesh_zero_is_hard_failure(self):
        self.assertEqual(check_mesh(FakeMesh(12)), 12)
        with self.assertRaises(CsolError):
            check_mesh(FakeMesh(0))
        with self.assertRaises(CsolError):
            check_mesh(FakeMesh(2), expect_min=3)

    def test_domain_count_has_exact_and_lower_bounds(self):
        self.assertEqual(check_domains(FakeGeom(2), expect=2), 2)
        with self.assertRaises(CsolError):
            check_domains(FakeGeom(1), expect=2)
        with self.assertRaises(CsolError):
            check_domains(FakeGeom(0))

    def test_solution_accepts_valid_zero_but_rejects_nonfinite(self):
        model = FakeModel({"a": 0.0, "b": [0.0, 1.0], "bad": float("nan")})
        self.assertEqual(check_solution(model, {"a": "a"})["a"], 0.0)
        with self.assertRaises(CsolError):
            check_solution(model, {"bad": "bad"})
        with self.assertRaises(CsolError):
            check_solution(model, {"a": "a"}, require_nonzero=True)
        with self.assertRaises(CsolError):
            check_solution(model, {"b": "b"})
        self.assertEqual(check_solution(model, {"b": "b"}, reducers={"b": "last"})["b"], 1.0)

    def test_solution_rejects_empty_probe_set(self):
        with self.assertRaises(CsolError):
            check_solution(FakeModel({}), {})

    def test_solution_enumerates_dataset_and_inner(self):
        model = FakeModel({})
        model.datasets = lambda: ["Study 1/Solution 1", "Study 2/Solution 2"]
        model.inner = lambda dataset: (
            np.array([2, 1]), np.array([2.0, 1.0])
        )
        entries = enum_entries(model, study="Study 1")
        self.assertEqual(entries, [
            {"t": 1.0, "ds": "Study 1/Solution 1", "inner": 1},
            {"t": 2.0, "ds": "Study 1/Solution 1", "inner": 2},
        ])
        with self.assertRaises(CsolError):
            enum_entries(model, study="std1")
        with self.assertRaises(CsolError):
            enum_entries(model, study="Study 1", max_inner=1)


class SolveAndAverageTests(unittest.TestCase):
    def test_solver_builds_checked_mesh_and_retries(self):
        mesh = FakeMesh(5)
        model = FakeModel({}, failures=1)
        count = solve(model, mesh, study="std1", retries=1, retry_wait_s=0, log=None)
        self.assertEqual(count, 5)
        self.assertEqual(mesh.runs, 1)
        self.assertEqual(model.solved, ["std1"])

    def test_weighted_averages_use_correct_denominators(self):
        model = FakeModel({
            "intop_surf(q)": 8.0,
            "intop_surf(1)": 2.0,
            "intop_vol(q)": 9.0,
            "intop_vol(1)": 3.0,
            "intop_front((mask)*(q))": 10.0,
            "intop_front(mask)": 4.0,
            "intop_edge(2*pi*r*(q))": 14.0,
            "intop_edge(2*pi*r)": 7.0,
        })
        self.assertEqual(area_avg(model, "q"), 4.0)
        self.assertEqual(vol_avg(model, "q"), 3.0)
        self.assertEqual(masked_avg(model, "q", "mask"), 2.5)
        self.assertEqual(axisym_area(model, "q"), 2.0)

    def test_average_unit_applies_to_ratio_not_integral(self):
        model = FakeModel({
            "intop_surf(1)": 2.0,
            "(intop_surf(T))/(intop_surf(1))": 300.0,
        })
        self.assertEqual(area_avg(model, "T", unit="K"), 300.0)
        calls = model.calls
        self.assertIn(("(intop_surf(T))/(intop_surf(1))", "K", {}), calls)
        self.assertNotIn(("intop_surf(T)", "K", {}), calls)

    def test_average_rejects_zero_denominator(self):
        model = FakeModel({"intop_surf(q)": 1.0, "intop_surf(1)": 0.0})
        with self.assertRaises(CsolError):
            area_avg(model, "q")


class PersistenceTests(unittest.TestCase):
    def test_atomic_json_and_logger(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "nested" / "result.json"
            atomic_write_json(target, {"中文": 1})
            self.assertEqual(json.loads(target.read_text(encoding="utf-8")), {"中文": 1})
            self.assertFalse(target.with_suffix(".json.tmp").exists())

            lines = []
            log = logger(Path(td) / "run.log", echo=lines.append)
            log("第一步")
            log.close()
            self.assertIn("第一步", (Path(td) / "run.log").read_text(encoding="utf-8"))
            self.assertEqual(lines, ["第一步"])

    def test_case_fingerprint_changes_with_parameters_and_files(self):
        with tempfile.TemporaryDirectory() as td:
            script = Path(td) / "case.py"
            script.write_text("x = 1\n", encoding="utf-8")
            first = case_fingerprint("C0", {"p": "1[Pa]"}, {"case.py": script})
            second = case_fingerprint("C0", {"p": "2[Pa]"}, {"case.py": script})
            self.assertNotEqual(first, second)
            script.write_text("x = 2\n", encoding="utf-8")
            third = case_fingerprint("C0", {"p": "1[Pa]"}, {"case.py": script})
            self.assertNotEqual(first, third)

    def test_result_is_current_requires_status_and_exact_fingerprint(self):
        with tempfile.TemporaryDirectory() as td:
            result = Path(td) / "result.json"
            fingerprint = {"case": "abc"}
            atomic_write_json(result, {"status": "OK", "_fingerprints": fingerprint})
            self.assertEqual(result_is_current(result, fingerprint), (True, "指纹一致"))
            atomic_write_json(result, {"status": "OK", "_fingerprints": {"case": "old"}})
            self.assertFalse(result_is_current(result, fingerprint)[0])
            atomic_write_json(result, {"status": "FAILED", "_fingerprints": fingerprint})
            self.assertFalse(result_is_current(result, fingerprint)[0])
            self.assertFalse(result_is_current(Path(td) / "missing.json", fingerprint)[0])

    def test_sha256_streams_without_read_bytes(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "large.bin"
            payload = b"abcd" * (1024 * 1024)
            path.write_bytes(payload)
            with patch.object(Path, "read_bytes", side_effect=AssertionError("must stream")):
                self.assertEqual(sha256_file(path), hashlib.sha256(payload).hexdigest())

    def test_hashes_and_memory_are_well_formed(self):
        self.assertEqual(sha256_obj({"b": 2, "a": 1}), sha256_obj({"a": 1, "b": 2}))
        self.assertGreater(mem_gb(), 0.0)


if __name__ == "__main__":
    unittest.main()
