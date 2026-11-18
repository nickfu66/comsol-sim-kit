"""顺序工况驱动：完整指纹与模型哈希一致才跳过，收尾自动聚合。"""
import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import paths
from paths import DATA, HISTORY, LOG, QUALITY_SPEC
from case_spec import CASES, case_names, fingerprint
from csol_kit import CsolError, aggregate_case_results, result_is_current
from quality import canonical_spec_sha256


def run_one(case):
    log_path = LOG / f"run_{case}.log"
    command = [sys.executable, "-B", "-u", str(Path(paths.HERE) / "run_case_one.py"), "--case", case]
    with log_path.open("w", encoding="utf-8") as stream:
        process = subprocess.Popen(
            command, cwd=paths.HERE, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
        )
        for line in process.stdout:
            print(line, end="")
            stream.write(line)
        return process.wait()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", choices=case_names())
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    if not CASES:
        parser.error("CASES 为空；请先按任务书填写 case_spec.py")
    selected = (args.only,) if args.only else case_names()
    rc = 0
    for case in selected:
        current = fingerprint(case)
        result = DATA / f"工况_{case}.json"
        current_ok, reason = (False, "--force") if args.force else result_is_current(
            result, current, require_models=True
        )
        if current_ok:
            print(f"[driver] 跳过 {case}：{reason}")
            continue
        if result.exists():
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            shutil.move(str(result), HISTORY / f"{stamp}_工况_{case}.json")
        print(f"[driver] 运行 {case}：{reason}")
        case_rc = run_one(case)
        if case_rc and not rc:
            rc = case_rc
    try:
        spec = json.loads(QUALITY_SPEC.read_text(encoding="utf-8"))
        aggregate_case_results(
            DATA,
            expected_cases=case_names(),
            validator=lambda path, case: result_is_current(
                path, fingerprint(case), require_models=True
            ),
            spec_sha256=canonical_spec_sha256(spec),
        )
    except CsolError as exc:
        print(f"[driver] {exc}")
        return 1
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
