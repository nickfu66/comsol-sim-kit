#!/usr/bin/env python3
"""公共环境单入口：preflight / lint / gate / env。"""
from __future__ import annotations

import argparse
import ast
import importlib.util
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ENV = Path(__file__).resolve().parents[1]
ROOT = ENV.parent
for item in (str(ENV), str(ENV / "ctl")):
    if item not in sys.path:
        sys.path.insert(0, item)

from comsol_boot import BootConfigError, load_config, validate_config  # noqa: E402
from quality import evaluate_gate, freeze_spec, write_evidence_bundle  # noqa: E402

EXIT_OK, EXIT_FAIL, EXIT_USAGE, EXIT_INTERNAL = 0, 1, 2, 3

REQUIRED_PUBLIC_FILES = (
    "README.md", "开工指令.md", "LICENSE", "CHANGELOG.md",
    "requirements.txt", "requirements.lock", ".gitignore", ".gitattributes",
    "config/config.example.toml",
    "env/comsol_boot.py", "env/api_registry.py", "env/csol_kit.py",
    "env/_smoke_csol_kit.py", "env/_README_环境说明.md",
    "env/HANDOVER_环境交接卡.md", "env/ctl/check.py", "env/ctl/quality.py",
    "env/docs/能力契约与扩展登记.md",
    "templates/README_任务导航.template.md", "templates/case/quality_spec.json",
    "tools/new_case.py", "tools/check_public.py", "tools/publish.py",
)


def lint_tree(directory):
    """扫描 .create(tag, "LiteralType")，要求先经过 create_checked。"""
    root = Path(directory)
    problems = []
    for path in sorted(root.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, UnicodeError, SyntaxError) as exc:
            problems.append(f"{path}: 无法解析：{exc}")
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr != "create" or len(node.args) < 2:
                continue
            second = node.args[1]
            if isinstance(second, ast.Constant) and not isinstance(second.value, str):
                continue
            type_text = second.value if isinstance(second, ast.Constant) else ast.unparse(second)
            problems.append(
                f"{path.relative_to(root)}:{node.lineno}: "
                f"直接创建类型 {type_text!r}，请使用 create_checked"
            )
    return problems


def markdown_link_problems(markdown_path):
    """检查本地 Markdown 链接；跳过 URL、mailto 和纯页内锚点。"""
    path = Path(markdown_path)
    problems = []
    text = path.read_text(encoding="utf-8")
    for match in re.finditer(r"\[[^]]+\]\(([^)]+)\)", text):
        target = match.group(1).strip()
        if target.startswith("<") and ">" in target:
            target = target[1:target.index(">")]
        elif " " in target and not Path(target).exists():
            target = target.split(" ", 1)[0]
        if not target or target.startswith(("#", "http://", "https://", "mailto:")):
            continue
        target = target.split("#", 1)[0]
        if not target:
            continue
        if not (path.parent / target).exists():
            line = text.count("\n", 0, match.start()) + 1
            problems.append(f"{path}:{line}: 链接不存在：{match.group(1)}")
    return problems


def public_markdown_files(root=ROOT):
    """只枚举公共文档，不读取本地 SIM、运行状态或版本库内部文件。"""
    root = Path(root)
    for path in sorted(root.rglob("*.md")):
        relative = path.relative_to(root)
        if any(part in {".git", ".runtime", "__pycache__"} for part in relative.parts):
            continue
        if relative.parts and re.match(r"^SIM\d+_", relative.parts[0]):
            continue
        if relative.as_posix() == "README_任务导航.local.md":
            continue
        yield path


def env_check(root=ROOT):
    """检查公共必需文件和 Markdown 本地链接。"""
    root = Path(root)
    problems = [f"缺少公共文件：{name}" for name in REQUIRED_PUBLIC_FILES if not (root / name).exists()]
    for path in public_markdown_files(root):
        problems.extend(markdown_link_problems(path))
    return problems


def _resolve(path):
    result = Path(path)
    return result if result.is_absolute() else ROOT / result


def preflight_command(args):
    try:
        config = load_config(args.config)
    except BootConfigError as exc:
        print(f"[preflight] FAIL：{exc}")
        return EXIT_FAIL
    problems = validate_config(config)
    if sys.version_info < (3, 11):
        problems.append("需要 Python >= 3.11")
    for module in ("numpy", "mph", "jpype"):
        if importlib.util.find_spec(module) is None:
            problems.append(f"缺少 Python 模块：{module}")
    if problems:
        for problem in problems:
            print(f"[preflight] FAIL：{problem}")
        return EXIT_FAIL
    print(f"[preflight] PASS：COMSOL {config['version']} / cores={config['cores']} / Python {sys.version.split()[0]}")
    print("[preflight] 仅完成配置检查，未启动 COMSOL；真机冒烟使用 python env/_smoke_csol_kit.py --comsol")
    return EXIT_OK


def lint_command(args):
    case = _resolve(args.sim)
    if not case.is_dir():
        print(f"[lint] 用法错误：案例目录不存在：{case}")
        return EXIT_USAGE
    problems = lint_tree(case)
    for problem in problems:
        print(f"[lint] {problem}")
    print(f"[lint] {'FAIL' if problems else 'PASS'}：{len(problems)} 处问题")
    return EXIT_FAIL if problems else EXIT_OK


def gate_command(args):
    case = _resolve(args.sim)
    spec_path = case / "quality_spec.json"
    if not spec_path.is_file():
        print(f"[gate] 用法错误：找不到 {spec_path}")
        return EXIT_USAGE
    if args.bundle and not args.emit:
        print("[gate] 用法错误：--bundle 需要同时指定 --emit")
        return EXIT_USAGE
    if args.freeze and not args.emit:
        print("[gate] 用法错误：--freeze 会修改 quality_spec.json，需要 --emit")
        return EXIT_USAGE
    values_path = _resolve(args.values) if args.values else case / "03_结果" / "数据" / "values.json"
    if args.values and not values_path.is_file():
        print(f"[gate] 用法错误：--values 文件不存在：{values_path}")
        return EXIT_USAGE
    try:
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
        if args.freeze:
            spec = freeze_spec(spec_path)
            print(f"[gate] 已冻结判据：{spec['spec_sha256']}")
        if args.freeze and not values_path.is_file() and not args.bundle:
            print("[gate] 冻结完成；未提供实测值，本次不执行正式验收。")
            return EXIT_OK
        values = json.loads(values_path.read_text(encoding="utf-8")) if values_path.is_file() else {}
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"[gate] 输入或判据无效：{exc}")
        return EXIT_FAIL

    verdict = evaluate_gate(spec, values, require_frozen=True, require_provenance=True)
    for result in verdict["results"]:
        print(f"[gate] {result['id']}: {result['status']} — {result['reason']}")
    for item in verdict["blocked"]:
        if item["id"].startswith("SPEC_"):
            print(f"[gate] {item['id']}: FAIL — {item['reason']}")
    print(f"[gate] 结论可引用={verdict['admissible']}")

    if args.bundle:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        bundle = case / "03_结果" / "数据" / "证据快照" / stamp
        write_evidence_bundle(bundle, spec_path, values, verdict)
        print(f"[gate] 证据快照：{bundle}")
    return EXIT_OK if verdict["admissible"] else EXIT_FAIL


def env_command(_args):
    problems = env_check(ROOT)
    for problem in problems:
        print(f"[env] {problem}")
    print(f"[env] {'FAIL' if problems else 'PASS'}：{len(problems)} 处问题")
    return EXIT_FAIL if problems else EXIT_OK


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    preflight = sub.add_parser("preflight", help="检查本机配置，不启动 COMSOL")
    preflight.add_argument("--config", help="config.toml 路径")
    preflight.set_defaults(func=preflight_command)

    lint = sub.add_parser("lint", help="扫描案例中的未守卫 API 创建")
    lint.add_argument("--sim", required=True, help="案例目录")
    lint.set_defaults(func=lint_command)

    gate = sub.add_parser("gate", help="按冻结判据验收案例")
    gate.add_argument("--sim", required=True, help="案例目录")
    gate.add_argument("--values", help="实测值 JSON，默认案例 03_结果/数据/values.json")
    gate.add_argument("--freeze", action="store_true", help="冻结当前 spec（需 --emit）")
    gate.add_argument("--bundle", action="store_true", help="生成证据快照（需 --emit）")
    gate.add_argument("--emit", action="store_true", help="允许写本次案例产物")
    gate.set_defaults(func=gate_command)

    env = sub.add_parser("env", help="检查公共文件和文档链接")
    env.set_defaults(func=env_command)
    return parser


def main(argv=None):
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except Exception as exc:
        print(f"[check] 内部异常：{type(exc).__name__}: {exc}", file=sys.stderr)
        return EXIT_INTERNAL


if __name__ == "__main__":
    raise SystemExit(main())
