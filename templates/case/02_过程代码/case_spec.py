"""不可变工况、复位参数和唯一执行指纹；空白模板无默认参数。"""
from pathlib import Path
from types import MappingProxyType

from comsol_boot import runtime_metadata
from csol_kit import case_fingerprint

CASE_DIR = Path(__file__).resolve().parents[1]
ROOT = CASE_DIR.parent
_CASES = {}
CASES = MappingProxyType(_CASES)
RESET_PARAMS = ()

# 新增本地 helper 时，必须加入此清单，否则其变化不会触发续跑。
DEPENDENCY_FILES = (
    "02_过程代码/run_case_one.py",
    "02_过程代码/model_common.py",
    "02_过程代码/case_spec.py",
    "02_过程代码/paths.py",
    "env/csol_kit.py",
    "env/comsol_boot.py",
    "env/api_registry.py",
)


def case_params(name):
    if name not in CASES:
        raise KeyError(f"未知工况 {name!r}；请先在 case_spec.py 按任务书登记")
    return dict(CASES[name])


def case_names():
    return tuple(CASES)


def execution_files():
    return {
        name: (CASE_DIR if name.startswith("02_过程代码/") else ROOT) / name
        for name in DEPENDENCY_FILES
    }


def fingerprint(case):
    return case_fingerprint(
        case, case_params(case), execution_files(),
        runtime=runtime_metadata(ROOT / "config" / "config.toml"),
    )
