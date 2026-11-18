"""统一产物路径；只引用公共 ENV 与本案例目录。"""
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
CASE = HERE.parent
ROOT = CASE.parent
ENV = ROOT / "env"
for item in (str(ENV), str(ENV / "ctl"), str(HERE)):
    if item not in sys.path:
        sys.path.insert(0, item)

MODEL = CASE / "01_建模"
RESULT = CASE / "03_结果"
DATA = RESULT / "数据"
FIG = RESULT / "图片"
LOG = HERE / "日志"
PROBE = HERE / "探针"
HISTORY = LOG / "历史"

def main_mph(case):
    return MODEL / f"main_{case}.mph"


def solved_mph(case):
    return MODEL / f"solved_{case}.mph"


QUALITY_SPEC = CASE / "quality_spec.json"

for directory in (MODEL, DATA, FIG, LOG, PROBE, HISTORY):
    directory.mkdir(parents=True, exist_ok=True)
