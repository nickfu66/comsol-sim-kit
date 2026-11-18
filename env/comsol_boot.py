"""COMSOL 进程内 standalone 启动；mph/JPype 仅在 start_client 时导入。"""
from __future__ import annotations

import importlib
import importlib.metadata
import os
import platform
import sys
import tempfile
import tomllib
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class BootConfigError(RuntimeError):
    """本机配置缺失、无效或不可写。"""


def load_config(path=None, project_root=None):
    """读取 TOML 并解析 COMSOL、JVM 和状态目录路径。"""
    root = Path(project_root) if project_root else PROJECT_ROOT
    selected = path or os.environ.get("COMSOL_SIM_KIT_CONFIG") or root / "config" / "config.toml"
    config_path = Path(selected)
    if not config_path.is_file():
        raise BootConfigError(
            f"找不到配置 {config_path}；请复制 config/config.example.toml "
            "为 config/config.toml 后按本机修改，或设置 COMSOL_SIM_KIT_CONFIG。"
        )
    try:
        with config_path.open("rb") as stream:
            raw = tomllib.load(stream)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise BootConfigError(f"配置不可读：{exc}") from exc

    if not str(raw.get("comsol_root", "")).strip():
        raise BootConfigError("config.toml 缺少 comsol_root")
    cores = int(raw.get("cores", 8))
    if cores < 1:
        raise BootConfigError("cores 必须 >= 1")
    def rooted(value):
        candidate = Path(value)
        return candidate if candidate.is_absolute() else root / candidate

    comsol_root = rooted(raw["comsol_root"])
    state_dir = rooted(raw.get("state_dir", ".runtime/comsol_home"))
    jvm_dll = rooted(raw.get("jvm_dll", comsol_root / "java/win64/jre/bin/server/jvm.dll"))
    server = rooted(raw.get("server", comsol_root / "bin/win64/comsolmphserver.exe"))
    return {
        "comsol_root": comsol_root,
        "version": str(raw.get("version", "6.3")),
        "build": int(raw.get("build", 0)),
        "cores": cores,
        "state_dir": state_dir,
        "jvm_dll": jvm_dll,
        "server": server,
        "documentation_root": str(raw.get("documentation_root", "")),
    }


def validate_config(config):
    """检查安装路径、JVM 和状态目录可写性，返回问题列表。"""
    problems = []
    if not config["comsol_root"].is_dir():
        problems.append(f"COMSOL 根目录不存在：{config['comsol_root']}")
    if not config["jvm_dll"].is_file():
        problems.append(f"JVM 不存在：{config['jvm_dll']}")
    try:
        for name in ("prefs", "recovery", "tmp"):
            (config["state_dir"] / name).mkdir(parents=True, exist_ok=True)
        fd, probe = tempfile.mkstemp(prefix="preflight-", dir=config["state_dir"])
        os.close(fd)
        os.unlink(probe)
    except OSError as exc:
        problems.append(f"COMSOL 状态目录不可写：{exc}")
    return problems


def runtime_metadata(config_path=None, actual_version=None):
    """返回续跑环境指纹；可用模型实际版本核对配置声明。"""
    config = load_config(config_path)
    metadata = {
        "comsol_version": config["version"],
        "comsol_build": config["build"],
        "python": platform.python_version(),
        "platform": f"{platform.system()} {platform.release()} {platform.machine()}",
        "mph": importlib.metadata.version("mph"),
        "jpype1": importlib.metadata.version("jpype1"),
        "numpy": importlib.metadata.version("numpy"),
    }
    if actual_version is not None:
        parts = str(actual_version).split(".")
        actual_build = int(parts[-1]) if parts[-1].isdigit() else -1
        actual_series = ".".join(parts[:2])
        if actual_series != config["version"]:
            raise BootConfigError(
                f"实际 COMSOL 系列 {actual_series} 与配置声明 {config['version']} 不一致"
            )
        build_verified = len(parts) >= 3 and parts[-1].isdigit()
        if build_verified and config["build"] and actual_build != config["build"]:
            raise BootConfigError(
                f"实际 COMSOL build {actual_build} 与配置声明 {config['build']} 不一致"
            )
        metadata["comsol_actual"] = actual_version
        metadata["comsol_build_verified"] = build_verified
    return metadata


def start_client(config_path=None):
    """以 JPype 进程内模式启动一个客户端；每进程仍只应创建一个。"""
    config = load_config(config_path)
    problems = validate_config(config)
    if problems:
        raise BootConfigError("；".join(problems))
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    mph = importlib.import_module("mph")
    importlib.import_module("mph.discovery")
    jpype = importlib.import_module("jpype")
    major, minor, *_ = config["version"].split(".")
    backend = {
        "name": config["version"],
        "major": int(major), "minor": int(minor), "patch": 0,
        "build": config["build"],
        "root": config["comsol_root"],
        "jvm": config["jvm_dll"],
        "server": [config["server"]],
    }
    mph.discovery.backend = lambda version=None: backend
    mph.discovery.find_backends = lambda: [backend]

    original_start_jvm = jpype.startJVM

    def start_jvm_with_state(*args, **kwargs):
        jvm_args = list(args)
        home = config["state_dir"]
        extra = [
            f"-Dcs.prefsdir={home / 'prefs'}",
            f"-Dcs.recoverydir={home / 'recovery'}",
            f"-Dcs.tmpdir={home / 'tmp'}",
            f"-Duser.home={home}",
            f"-Djava.io.tmpdir={home / 'tmp'}",
        ]
        jvm_args[1:1] = extra
        return original_start_jvm(*jvm_args, **kwargs)

    jpype.startJVM = start_jvm_with_state
    return mph.Client(cores=config["cores"])
