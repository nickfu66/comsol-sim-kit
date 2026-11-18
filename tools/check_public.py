#!/usr/bin/env python3
"""公开前检查：文件边界、私人路径、凭据、历史标记和离线测试。"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath

PROJECT_ROOT = Path(__file__).resolve().parents[1]

FORBIDDEN_SUFFIXES = {
    ".mph", ".mphbin", ".pyc", ".jar", ".exe", ".dll", ".sqlite3",
    ".env", ".key", ".pem", ".pfx",
}
TEXT_SUFFIXES = {
    ".py", ".md", ".json", ".toml", ".txt", ".yml", ".yaml",
    ".gitignore", ".gitattributes", ".cfg", ".ini", ".lock", ".gitkeep",
}
LEGACY_MARKERS = (
    "金刚" + "石",
    "comsol" + "-mcp-test",
    "COMSOL" + "_Multiphysics_MCP",
    "SIM" + "14_高斯",
)
PRIVATE_PATH = re.compile(r"[A-Za-z]:[\\/]+Users[\\/]+[^\\/\s]+", re.IGNORECASE)
SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b(api[_-]?key|password|secret|token|access[_-]?token)"
    r"\s*[:=]\s*(?:[\"'][^\"']{8,}[\"']|[A-Za-z0-9_+/=.-]{8,})"
)
COMMON_TOKEN = re.compile(
    r"\b(ghp_[A-Za-z0-9]{12,}|github_pat_[A-Za-z0-9_]{12,}|"
    r"sk-[A-Za-z0-9]{12,}|AKIA[0-9A-Z]{12,})\b"
)
PRIVATE_KEY_BLOCK = re.compile(r"-----BEGIN (?:[A-Z]+ )?PRIVATE KEY-----")
SENSITIVE_BASENAME = re.compile(r"(?i)^(?:credentials?|secrets?|id_rsa|id_ed25519)(?:[._-]|$)")
SKIP_DIRS = {".git", ".runtime", "__pycache__", ".superpowers"}
TEMPLATE_OUTPUT_RULES = {
    "templates/case/01_建模/": {"_建模说明.md"},
    "templates/case/02_过程代码/探针/": {".gitkeep"},
    "templates/case/02_过程代码/日志/": {".gitkeep"},
    "templates/case/03_结果/图片/": {".gitkeep"},
    "templates/case/03_结果/数据/": {"results_manifest.json"},
}


def is_forbidden_filename(path):
    name = PurePosixPath(str(path)).name.lower()
    return (
        name == ".env" or name.startswith(".env.")
        or PurePosixPath(name).suffix in {".log", ".tmp", ".bak"}
    )


def template_output_problem(path):
    normalized = str(path).replace("\\", "/")
    for prefix, allowed in TEMPLATE_OUTPUT_RULES.items():
        if normalized.startswith(prefix) and PurePosixPath(normalized).name not in allowed:
            return f"{normalized}: templates 只允许空白模板结构，真实结果必须放 SIMxx 案例"
    return ""


def is_sensitive_filename(path):
    return bool(SENSITIVE_BASENAME.search(PurePosixPath(str(path)).name))


def is_text_path(path):
    suffix = PurePosixPath(str(path)).suffix.lower()
    return suffix in TEXT_SUFFIXES or PurePosixPath(str(path)).name in TEXT_SUFFIXES


def scan_public_content(display, text):
    """检查单个公开文本；同时供工作树和 Git 暂存 blob 使用。"""
    problems = []
    if PRIVATE_PATH.search(text):
        problems.append(f"{display}: 含私人路径")
    if SECRET_ASSIGNMENT.search(text) or COMMON_TOKEN.search(text) or PRIVATE_KEY_BLOCK.search(text):
        problems.append(f"{display}: 疑似密钥、访问令牌或私钥")
    for marker in LEGACY_MARKERS:
        if marker.lower() in text.lower():
            problems.append(f"{display}: 含历史项目标记 {marker!r}")
    return problems


def _is_local_case(relative):
    return bool(relative.parts and re.match(r"^SIM\d+_", relative.parts[0]))


def iter_public_files(root):
    """枚举公开候选；本地 SIM、真实配置和运行状态不属于候选。"""
    root = Path(root)
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if any(part in SKIP_DIRS for part in relative.parts):
            continue
        if _is_local_case(relative) or relative.as_posix() in {
            "config/config.toml", "README_任务导航.local.md",
        }:
            continue
        yield path, relative


def scan_public_tree(root):
    """返回公开发布问题；本地被忽略的 SIM 不参与扫描。"""
    root = Path(root)
    problems = []
    if not root.is_dir():
        return [f"项目目录不存在：{root}"]
    for name in ("work", "local"):
        if (root / name).exists():
            problems.append(f"公共架构不应包含 {name}/；个人任务和配置不纳入本项目目录")
    for path, relative in iter_public_files(root):
        display = relative.as_posix()
        if is_forbidden_filename(display) or path.suffix.lower() in FORBIDDEN_SUFFIXES:
            problems.append(f"{display}: 禁止公开的文件类型")
            continue
        template_problem = template_output_problem(display)
        if template_problem:
            problems.append(template_problem)
        if is_sensitive_filename(display):
            problems.append(f"{display}: 敏感文件名，需移除或人工改名确认")
        if path.stat().st_size > 5 * 1024 * 1024:
            problems.append(f"{display}: 单文件超过 5 MiB，需人工确认")
        if not is_text_path(display) and path.name != "LICENSE":
            problems.append(f"{display}: 未登记的公开资产类型，默认拒绝")
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            problems.append(f"{display}: 文本文件必须为 UTF-8")
            continue
        problems.extend(scan_public_content(display, text))
    return problems


def run_offline_tests(root=PROJECT_ROOT):
    """以禁止写字节码的方式运行完整离线测试。"""
    environment = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    return subprocess.run(
        [sys.executable, "-B", "-m", "unittest", "discover", "-s", "tests", "-v"],
        cwd=root, env=environment,
    )


def main(argv=None):
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=PROJECT_ROOT)
    parser.add_argument("--skip-tests", action="store_true")
    args = parser.parse_args(argv)
    root = Path(args.root)
    problems = scan_public_tree(root)
    for problem in problems:
        print(f"[public] FAIL：{problem}")
    if problems:
        print(f"[public] 共 {len(problems)} 处问题，未执行发布")
        return 1
    print("[public] 文件边界与内容扫描 PASS")
    if not args.skip_tests:
        result = run_offline_tests(root)
        if result.returncode:
            return result.returncode
    print("[public] PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
