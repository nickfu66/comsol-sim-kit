"""物理中立的 COMSOL 通用工具。

本模块只依赖 NumPy 和 Python 标准库，导入时不会启动 COMSOL。
所有校验失败都抛出 :class:`CsolError`，避免被调用方静默吞掉。
"""
from __future__ import annotations

import ctypes
import hashlib
import json
import math
import os
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Mapping

import numpy as np

__all__ = [
    "CsolError", "ev", "ev_scalar", "check_mesh", "check_domains",
    "check_solution", "solve", "area_avg", "vol_avg", "masked_avg",
    "axisym_area", "axisym_vol", "mem_gb", "logger", "atomic_write_json",
    "enum_entries", "sha256_file", "sha256_obj", "case_fingerprint",
    "result_is_current", "aggregate_case_results",
]


class CsolError(RuntimeError):
    """公共库发现的模型、网格、解或数据口径错误。"""


def ev(model, expr, unit=None):
    """求值并归一为 float 或一维/多维 ndarray。"""
    value = model.evaluate(expr, unit) if unit else model.evaluate(expr)
    try:
        array = np.asarray(value, dtype=float)
    except (TypeError, ValueError):
        return float(value)
    if array.size == 1:
        return float(array.ravel()[0])
    return array


def ev_scalar(model, expr, unit=None, reducer=None):
    """求值为 float；数组必须由调用方显式指定归约方式。"""
    value = ev(model, expr, unit)
    if not isinstance(value, np.ndarray):
        return float(value)
    if value.size == 0:
        raise CsolError(f"表达式 {expr!r} 求值得到空数组")
    if reducer is None:
        raise CsolError(f"表达式 {expr!r} 返回数组，必须显式指定 reducer")
    reducers = {
        "max": np.max, "min": np.min, "mean": np.mean, "sum": np.sum,
        "first": lambda array: array.ravel()[0],
        "last": lambda array: array.ravel()[-1],
    }
    if reducer not in reducers:
        raise CsolError(f"未知归约器 {reducer!r}；可选 {sorted(reducers)}")
    return float(reducers[reducer](value))


def check_mesh(mesh, expect_min=1, label="mesh"):
    """返回单元数；空网格或低于下限立即失败。"""
    count = int(mesh.stat().getNumElem())
    if count == 0:
        raise CsolError(
            f"[{label}] 网格单元数为 0：检查实体选择、尺寸设置和网格特征。"
        )
    if count < expect_min:
        raise CsolError(f"[{label}] 网格单元数 {count} < 下限 {expect_min}")
    return count


def check_domains(geom, expect=None, label="geom", expect_min=1):
    """检查几何域数量的精确值或下限。"""
    count = int(geom.getNDomains())
    if expect is not None and count != expect:
        raise CsolError(f"[{label}] 域数 {count} != 预期 {expect}")
    if count < expect_min:
        raise CsolError(f"[{label}] 域数 {count} < 下限 {expect_min}")
    return count


def check_solution(model, probe_exprs, label="solution", verbose=False,
                   require_nonzero=False, reducers=None):
    """检查每个探测表达式都能得到有限标量。

    零可能是合法物理解，因此默认允许；只有调用方明确要求时才检查非零。
    """
    if not probe_exprs:
        raise CsolError(f"[{label}] 至少需要一个解探测表达式")
    results = {}
    reducers = reducers or {}
    for name, expr in probe_exprs.items():
        try:
            value = ev_scalar(model, expr, reducer=reducers.get(name))
        except Exception as exc:
            raise CsolError(f"[{label}] 探测 {name}={expr!r} 失败：{exc}") from exc
        if not math.isfinite(value):
            raise CsolError(f"[{label}] 探测 {name}={expr!r} 得到非有限值 {value}")
        results[name] = value
        if verbose:
            print(f"[{label}] {name} = {value:.9g}")
    if require_nonzero and all(abs(value) < 1e-30 for value in results.values()):
        raise CsolError(f"[{label}] 所有探测项均为零，需确认求解和激励是否生效")
    return results


def solve(model, mesh, study="std1", log=print, retries=1, retry_wait_s=2.0,
          expect_min_elem=1):
    """先运行并校验网格，再求解指定研究；仅对求解异常重试。"""
    mesh.run()
    count = check_mesh(mesh, expect_min=expect_min_elem, label=f"{study}/mesh")
    last_error = None
    for attempt in range(retries + 1):
        try:
            model.solve(study)
            return count
        except Exception as exc:
            last_error = exc
            if attempt == retries:
                raise
            if log:
                log(f"[solve] 第 {attempt + 1} 次求解失败，将重试：{exc}")
            time.sleep(retry_wait_s)
    raise last_error  # pragma: no cover


def _sum_value(value):
    return float(np.sum(value)) if isinstance(value, np.ndarray) else float(value)


def _ratio(model, numerator, denominator, unit, name):
    den = _sum_value(ev(model, denominator))
    if abs(den) < 1e-300:
        raise CsolError(f"{name}: 分母 {denominator!r} 为零，平均值无定义")
    if unit:
        # unit 属于平均量，不属于分子积分；例如温度面积平均的单位是 K，
        # 而温度面积积分的单位应是 K·m²。直接对整个比值指定平均量单位。
        return _sum_value(ev(model, f"({numerator})/({denominator})", unit))
    num = _sum_value(ev(model, numerator))
    return num / den


def area_avg(model, expr, intop="intop_surf", unit=None):
    """三维或普通表面的面积平均。"""
    return _ratio(model, f"{intop}({expr})", f"{intop}(1)", unit, "area_avg")


def vol_avg(model, expr, intop="intop_vol", unit=None):
    """普通三维域的体积平均。"""
    return _ratio(model, f"{intop}({expr})", f"{intop}(1)", unit, "vol_avg")


def masked_avg(model, expr, mask, intop="intop_front", unit=None):
    """掩码区域平均，分母严格使用掩码自身的积分。"""
    return _ratio(
        model,
        f"{intop}(({mask})*({expr}))",
        f"{intop}({mask})",
        unit,
        "masked_avg",
    )


def axisym_area(model, expr, intop="intop_edge", unit=None):
    """二维轴对称边界旋转面积平均，自动加入 2πr 权重。"""
    return _ratio(
        model, f"{intop}(2*pi*r*({expr}))", f"{intop}(2*pi*r)",
        unit, "axisym_area",
    )


def axisym_vol(model, expr, intop="intop_dom", unit=None):
    """二维轴对称域旋转体积平均，自动加入 2πr 权重。"""
    return _ratio(
        model, f"{intop}(2*pi*r*({expr}))", f"{intop}(2*pi*r)",
        unit, "axisym_vol",
    )


def mem_gb():
    """返回当前可用物理内存（GB），无法查询时返回 0。"""
    if sys.platform == "win32":
        class MemoryStatus(ctypes.Structure):
            _fields_ = [
                ("length", ctypes.c_ulong), ("memory_load", ctypes.c_ulong),
                ("total_phys", ctypes.c_ulonglong), ("avail_phys", ctypes.c_ulonglong),
                ("total_page", ctypes.c_ulonglong), ("avail_page", ctypes.c_ulonglong),
                ("total_virtual", ctypes.c_ulonglong), ("avail_virtual", ctypes.c_ulonglong),
                ("avail_extended", ctypes.c_ulonglong),
            ]
        status = MemoryStatus()
        status.length = ctypes.sizeof(MemoryStatus)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return status.avail_phys / 1024 ** 3
        return 0.0
    try:
        pages = os.sysconf("SC_AVPHYS_PAGES")
        return pages * os.sysconf("SC_PAGE_SIZE") / 1024 ** 3
    except (ValueError, OSError, AttributeError):
        return 0.0


def logger(path, echo=print):
    """创建同时写 UTF-8 日志和可选回显的函数，用后调用 log.close()。"""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    stream = target.open("a", encoding="utf-8")

    def log(message):
        text = str(message)
        stream.write(text + "\n")
        stream.flush()
        if echo:
            echo(text)

    def close():
        if not stream.closed:
            stream.close()

    log.close = close
    return log


def atomic_write_json(path, obj, indent=2, ensure_ascii=False):
    """同目录临时文件 + os.replace，避免中断留下截断 JSON。"""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(obj, indent=indent, ensure_ascii=ensure_ascii, default=str)
    fd, temporary = tempfile.mkstemp(prefix=target.name + ".", suffix=".tmp", dir=target.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def enum_entries(model, study=None, max_inner=None, log=None):
    """用 MPh inner(dataset) 枚举完整时间条目。

    study 使用显示名（例如 "Study 1"）而非 Java tag；达到 max_inner 必须报错，
    不允许静默截断后续解。
    """
    names = [str(item) for item in model.datasets()]
    if study is not None:
        names = [name for name in names if name == study or name.startswith(study + "/")]
        if not names:
            raise CsolError(f"找不到研究显示名 {study!r} 对应的数据集；可用：{model.datasets()}")
    entries = []
    for dataset in names:
        try:
            indices, times = model.inner(dataset=dataset)
        except Exception as exc:
            raise CsolError(f"数据集 {dataset!r} 无法读取 inner 解索引：{exc}") from exc
        if len(indices) != len(times):
            raise CsolError(f"数据集 {dataset!r} 的 inner 索引与时间值数量不一致")
        if max_inner is not None and len(indices) > max_inner:
            raise CsolError(f"数据集 {dataset!r} 有 {len(indices)} 条，超过 max_inner={max_inner}")
        for index, time_value in zip(indices, times):
            entries.append({"t": float(time_value), "ds": dataset, "inner": int(index)})
    entries.sort(key=lambda item: item["t"])
    if log:
        log(f"[enum_entries] {len(names)} 个数据集 / {len(entries)} 个条目")
    return entries


def sha256_file(path):
    """分块计算文件 SHA256，避免大型模型一次性读入内存。"""
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_obj(obj):
    """计算规范化 JSON 的 SHA256。"""
    payload = json.dumps(obj, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def case_fingerprint(case, parameters, files, runtime=None):
    """生成工况、参数、运行环境及相关脚本的稳定指纹。"""
    result = {"case": sha256_obj({
        "case": case, "parameters": dict(parameters), "runtime": runtime or {},
    })}
    for name, path in sorted(files.items()):
        file_path = Path(path)
        if not file_path.is_file():
            raise CsolError(f"续跑依赖不存在：{file_path}")
        result[f"file:{name}"] = sha256_file(file_path)
    return result


def result_is_current(path, fingerprint, require_models=False):
    """只有状态 OK 且完整指纹一致时才允许跳过，返回 (bool, reason)。"""
    target = Path(path)
    if not target.is_file():
        return False, "结果文件不存在"
    try:
        old = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return False, f"结果不可读：{exc}"
    if old.get("status") != "OK":
        return False, "旧结果状态不是 OK"
    if old.get("_fingerprints") != fingerprint:
        return False, "工况参数、运行环境或脚本指纹不一致"
    if require_models:
        models = old.get("model_files")
        if not isinstance(models, dict) or set(models) != {"main", "solved"}:
            return False, "旧结果必须且只能登记 main、solved 双模型"
        case_root = target.parents[2]
        case_name = str(old.get("case") or target.stem.removeprefix("工况_"))
        expected_names = {
            "main": f"main_{case_name}.mph", "solved": f"solved_{case_name}.mph",
        }
        for kind, info in models.items():
            if PurePosixPath(str(info.get("path", ""))).name != expected_names[kind]:
                return False, f"{kind} 模型路径不属于当前工况 {case_name}"
            try:
                model_path = (case_root / info["path"]).resolve()
                model_path.relative_to(case_root.resolve())
            except (KeyError, TypeError, ValueError):
                return False, "模型路径无效或越过案例目录"
            if not model_path.is_file():
                return False, f"模型文件不存在：{model_path}"
            if not info.get("sha256") or sha256_file(model_path) != info["sha256"]:
                return False, f"模型哈希不一致：{model_path}"
    return True, "指纹一致"


def aggregate_case_results(data_dir, expected_cases, validator, spec_sha256):
    """仅在全部声明工况通过当前校验后生成可验收聚合。

    validator(result_path, case) 必须重新计算并返回 (bool, reason)，至少覆盖
    当前参数/依赖指纹与 main/solved 双模型哈希。任何缺失或失效都会先写入
    incomplete provenance，再抛 CsolError，防止陈旧结果继续通过 gate。
    """
    data = Path(data_dir)
    case_root = data.parents[1]
    expected = tuple(expected_cases)
    if not expected or not spec_sha256:
        raise CsolError("聚合需要非空 expected_cases 与当前 spec_sha256")

    records = {}
    invalid = []
    for case in expected:
        result_path = data / f"工况_{case}.json"
        if not result_path.is_file():
            invalid.append({"case": case, "reason": "结果文件不存在"})
            continue
        try:
            record = json.loads(result_path.read_text(encoding="utf-8"))
            records[case] = (record, result_path)
            valid, reason = validator(result_path, case)
        except Exception as exc:
            valid, reason = False, f"校验异常：{exc}"
        if not valid:
            invalid.append({"case": case, "reason": reason})

    generated_at = datetime.now(timezone.utc).isoformat()
    if invalid:
        payload = {
            "generated_at": generated_at,
            "values": {},
            "provenance": {
                "complete": False, "spec_sha256": spec_sha256,
                "cases": [], "invalid": invalid,
            },
        }
        atomic_write_json(data / "values.json", payload)
        raise CsolError(f"结果聚合被阻止：{invalid}")

    merged = {}
    cases = []
    for case in expected:
        old, result_path = records[case]
        values = old.get("values") or {}
        for key in sorted(values):
            qualified = key if key.startswith(case + ".") else f"{case}.{key}"
            if qualified in merged and merged[qualified] != values[key]:
                raise CsolError(f"聚合输出 ID 冲突：{qualified}")
            merged[qualified] = values[key]
        cases.append({
            "case": case,
            "params": old.get("params", {}),
            "result_files": [result_path.relative_to(case_root).as_posix()],
            "model_files": old.get("model_files", {}),
            "runtime": old.get("runtime", {}),
            "check_status": "指纹与双模型已验证，待 gate",
        })
    payload = {
        "generated_at": generated_at,
        "cases": [item["case"] for item in cases],
        "values": merged,
        "provenance": {
            "complete": True,
            "spec_sha256": spec_sha256,
            "cases": [item["case"] for item in cases],
            "validated_at": generated_at,
        },
    }
    atomic_write_json(data / "values.json", payload)
    manifest_path = data / "results_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.is_file() else {}
    manifest.setdefault("case", case_root.name)
    manifest["generated_at"] = generated_at
    manifest["spec_sha256"] = spec_sha256
    manifest["provenance"] = payload["provenance"]
    manifest["cases"] = cases
    atomic_write_json(manifest_path, manifest)
    return payload
