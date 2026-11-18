#!/usr/bin/env python3
"""维护者发布工具：默认 dry-run，只有 --yes 才 commit + push。"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path, PurePosixPath

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "tools"))
from check_public import (  # noqa: E402
    FORBIDDEN_SUFFIXES,
    SKIP_DIRS,
    is_forbidden_filename,
    is_sensitive_filename,
    is_text_path,
    template_output_problem,
    run_offline_tests,
    scan_public_content,
    scan_public_tree,
)

PUBLIC_FILES = {
    "README.md", "开工指令.md", "LICENSE", "CHANGELOG.md",
    "requirements.txt", "requirements.lock", ".gitignore", ".gitattributes",
    "config/config.example.toml",
}
PUBLIC_DIRECTORIES = ("env/", "templates/", "tools/", "tests/")


def validate_public_path(path):
    """只允许白名单内的相对 POSIX 路径。"""
    raw = str(path).replace("\\", "/")
    if not raw or raw.startswith("/") or (len(raw) >= 2 and raw[1] == ":"):
        return False
    parts = raw.split("/")
    if ".." in parts:
        return False
    normalized = "/".join(part for part in parts if part not in ("", "."))
    normalized_parts = normalized.split("/")
    if any(part in SKIP_DIRS or part in {"work", "local"} for part in normalized_parts):
        return False
    if (
        is_forbidden_filename(normalized)
        or PurePosixPath(normalized).suffix.lower() in FORBIDDEN_SUFFIXES
        or is_sensitive_filename(normalized)
        or template_output_problem(normalized)
    ):
        return False
    if not is_text_path(normalized) and PurePosixPath(normalized).name != "LICENSE":
        return False
    return normalized in PUBLIC_FILES or any(normalized.startswith(item) for item in PUBLIC_DIRECTORIES)


def _git(root, *args, check=True):
    return subprocess.run(
        ["git", "-c", "core.quotepath=false", *args], cwd=root,
        text=True, encoding="utf-8", capture_output=True, check=check,
    )


def _git_bytes(root, *args):
    return subprocess.run(
        ["git", "-c", "core.quotepath=false", *args],
        cwd=root, capture_output=True, check=True,
    )


def staged_content_problems(root):
    """审计完整最终 Git 索引；已删除文件不再计入，未变化敏感文件也不能漏检。"""
    root = Path(root)
    indexed = [path for path in _git(root, "ls-files", "-z").stdout.split("\0") if path]
    problems = [f"{path}: 非公共索引路径" for path in indexed if not validate_public_path(path)]
    for path in indexed:
        data = _git_bytes(root, "show", f":{path}").stdout
        if len(data) > 5 * 1024 * 1024:
            problems.append(f"{path}: 暂存 blob 超过 5 MiB")
        if not is_text_path(path):
            continue
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            problems.append(f"{path}: 暂存文本不是 UTF-8")
            continue
        problems.extend(scan_public_content(path, text))
    return problems


def target_branch_matches(root, branch):
    """实际提交只允许发生在目标分支，避免 commit 与 push 指向不同分支。"""
    current = _git(root, "branch", "--show-current").stdout.strip()
    return bool(current) and current == branch


def main(argv=None):
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--message", default="更新公共仿真框架", help="提交说明")
    parser.add_argument("--remote", default="origin")
    parser.add_argument("--branch", default="main")
    parser.add_argument("--yes", action="store_true", help="确认实际提交并推送")
    parser.add_argument("--skip-tests", action="store_true")
    parser.add_argument("--root", default=PROJECT_ROOT)
    args = parser.parse_args(argv)
    root = Path(args.root)

    problems = scan_public_tree(root)
    for problem in problems:
        print(f"[publish] FAIL：{problem}")
    if problems:
        return 1
    if not args.skip_tests and run_offline_tests(root).returncode:
        return 1

    inside = _git(root, "rev-parse", "--is-inside-work-tree", check=False)
    if inside.returncode or inside.stdout.strip() != "true":
        print("[publish] 检查通过，但这里还不是 Git 仓库；请先 git init 并配置远程仓库。")
        return 2

    index_problems = staged_content_problems(root)
    for problem in index_problems:
        print(f"[publish] 最终索引 FAIL：{problem}")
    if index_problems:
        return 1

    status = _git(root, "status", "--short").stdout
    print(status or "[publish] 工作区无变化")
    if not args.yes:
        print("[publish] dry-run：未暂存、未提交、未推送。确认后加 --yes。")
        return 0

    if not target_branch_matches(root, args.branch):
        print(f"[publish] 当前分支不是目标分支 {args.branch}；已阻止 commit/push")
        return 1

    candidates = sorted(path for path in PUBLIC_FILES if (root / path).exists())
    candidates.extend(name.rstrip("/") for name in PUBLIC_DIRECTORIES if (root / name.rstrip("/")).exists())
    _git(root, "add", "--", *candidates)
    staged = _git(root, "diff", "--cached", "--name-only").stdout.splitlines()
    if not staged:
        print("[publish] 没有可提交的公共变化")
        return 0
    staged_problems = staged_content_problems(root)
    for problem in staged_problems:
        print(f"[publish] 暂存内容 FAIL：{problem}")
    if staged_problems:
        print("[publish] 已阻止 commit；未执行推送")
        return 1
    print(_git(root, "diff", "--cached", "--stat").stdout)
    _git(root, "commit", "-m", args.message)
    _git(root, "push", args.remote, args.branch)
    print("[publish] 已提交并推送")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
