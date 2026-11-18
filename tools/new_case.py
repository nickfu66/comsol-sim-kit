#!/usr/bin/env python3
"""从唯一空白模板创建 SIMxx_名称，不复制任何历史任务。"""
from __future__ import annotations

import argparse
import json
import re
import shutil
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CASE_TEMPLATE = PROJECT_ROOT / "templates" / "case"


def _next_number(root):
    numbers = []
    for path in Path(root).iterdir():
        match = re.match(r"^SIM(\d+)_", path.name) if path.is_dir() else None
        if match:
            numbers.append(int(match.group(1)))
    return max(numbers, default=0) + 1


def create_case(name, root=PROJECT_ROOT, template_dir=CASE_TEMPLATE):
    """创建下一个空白案例并返回路径；永不覆盖已有目录。"""
    clean = name.strip().replace(" ", "_")
    if not clean or clean in {".", ".."} or ".." in clean or "/" in clean or "\\" in clean:
        raise ValueError("任务名称不能为空，也不能包含路径分隔符或 ..")
    root = Path(root)
    template = Path(template_dir)
    if not template.is_dir():
        raise FileNotFoundError(f"空白模板不存在：{template}")
    root.mkdir(parents=True, exist_ok=True)
    destination = root / f"SIM{_next_number(root):02d}_{clean}"
    if destination.exists():
        raise FileExistsError(f"拒绝覆盖：{destination}")
    shutil.copytree(template, destination)
    navigation = root / "README_任务导航.local.md"
    navigation_template = template.parent / "README_任务导航.template.md"
    if not navigation.exists() and navigation_template.is_file():
        shutil.copyfile(navigation_template, navigation)

    spec_path = destination / "quality_spec.json"
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    spec["case"] = destination.name
    spec_path.write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")

    manifest_path = destination / "03_结果" / "数据" / "results_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["case"] = destination.name
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    task_path = destination / "任务书_待填写.md"
    task_path.write_text(
        task_path.read_text(encoding="utf-8").replace("<任务名称>", clean),
        encoding="utf-8",
    )
    return destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("name", help="任务名称，不包含 SIM 编号")
    args = parser.parse_args()
    try:
        destination = create_case(args.name)
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    print(destination)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
