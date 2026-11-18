import sys
import unittest
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "env"))

from api_registry import (  # noqa: E402
    ApiRegistryError,
    assert_type,
    create_checked,
    lookup,
    register_type,
)


class FakeFeatures:
    def __init__(self):
        self.calls = []

    def create(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return {"args": args, "kwargs": kwargs}


class RegistryTests(unittest.TestCase):
    def test_official_name_lookup(self):
        self.assertEqual(assert_type("mesh", "Sweep"), "Sweep")
        self.assertEqual(lookup("study", "Transient")["type"], "Transient")

    def test_gui_alias_is_not_silently_accepted(self):
        with self.assertRaisesRegex(ApiRegistryError, "Sweep"):
            assert_type("mesh", "Swept")
        with self.assertRaisesRegex(ApiRegistryError, "Transient"):
            assert_type("study", "TimeDependent")

    def test_unknown_name_never_calls_create(self):
        features = FakeFeatures()
        with self.assertRaises(ApiRegistryError):
            create_checked(features, "mesh1", "NotARealType", "mesh")
        self.assertEqual(features.calls, [])

    def test_create_checked_uses_canonical_type(self):
        features = FakeFeatures()
        created = create_checked(features, "swe1", "Sweep", "mesh")
        self.assertEqual(created["args"], ("swe1", "Sweep"))
        self.assertEqual(features.calls[0][0], ("swe1", "Sweep"))

    def test_register_type_requires_source_and_supports_aliases(self):
        register_type("custom_test", "VerifiedType", "本地探针 TEST-001", aliases=("GuiName",))
        self.assertEqual(assert_type("custom_test", "VerifiedType"), "VerifiedType")
        with self.assertRaisesRegex(ApiRegistryError, "VerifiedType"):
            assert_type("custom_test", "GuiName")
        with self.assertRaises(ApiRegistryError):
            register_type("custom_test", "NoSource", "")

    def test_solver_sequence_node_types_are_registered(self):
        # 真机探针：COMSOL 6.3 solver 序列的通用节点类型，物理中立。
        for name in ("Study", "StudyStep", "Variables", "Stationary",
                     "Parametric", "Eigenvalue"):
            self.assertEqual(assert_type("solver", name), name)

    def test_create_checked_accepts_solver_type_with_source(self):
        features = FakeFeatures()
        created = create_checked(features, "s1", "Stationary", "solver")
        self.assertEqual(created["args"], ("s1", "Stationary"))
        self.assertIn("探针", lookup("solver", "Stationary")["source"])


if __name__ == "__main__":
    unittest.main()
