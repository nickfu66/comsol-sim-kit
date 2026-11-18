"""通用判据结构校验、冻结、求值和证据快照；不含任何物理阈值。"""
from __future__ import annotations

import json
import math
import shutil
from datetime import datetime, timezone
from pathlib import Path

from csol_kit import atomic_write_json, sha256_file, sha256_obj

OPS = {
    "<": lambda value, threshold: value < threshold,
    "<=": lambda value, threshold: value <= threshold,
    ">": lambda value, threshold: value > threshold,
    ">=": lambda value, threshold: value >= threshold,
    "==": lambda value, threshold: value == threshold,
    "!=": lambda value, threshold: value != threshold,
}
VALID_SOURCE_TYPES = {"任务书", "人确认"}
BAD_SOURCE_WORDS = ("模型自拟", "模型自定", "自拟", "参考常见值", "默认经验值")
VALID_CATEGORIES = {"conservation", "mesh", "physics", "other"}
REQUIRED_FIELDS = ("id", "metric", "op", "value", "unit", "blocking", "source", "category")


def canonical_spec_sha256(spec):
    """计算判据内容哈希，排除两个冻结元数据字段。"""
    content = dict(spec)
    content.pop("spec_sha256", None)
    content.pop("frozen_at", None)
    return sha256_obj(content)


def _blocked(identifier, metric, reason, value=None, unit="", threshold=None, op=""):
    return {
        "id": identifier, "metric": metric, "reason": reason, "value": value,
        "unit": unit, "threshold": threshold, "op": op,
    }


def _finite_number(value):
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _valid_criterion_source(source):
    return bool(source) and not any(word in source for word in BAD_SOURCE_WORDS)


def spec_schema_problems(spec):
    """返回所有结构性封堵；任何一项都不受单个 blocking 设置影响。"""
    if not isinstance(spec, dict):
        return [_blocked("SPEC_INVALID", "顶层结构", "quality_spec 必须是 JSON 对象")]
    problems = []
    source = spec.get("source") or {}
    source_type = str(source.get("type", "")) if isinstance(source, dict) else ""
    source_ref = str(source.get("ref", "")) if isinstance(source, dict) else ""
    if (
        source_type not in VALID_SOURCE_TYPES
        or not source_ref.strip()
        or any(word in source_type + source_ref for word in BAD_SOURCE_WORDS)
    ):
        problems.append(_blocked(
            "SPEC_SOURCE", "判据来源",
            "source.type 必须为『任务书』或『人确认』，且 ref 必须明确",
        ))

    criteria = spec.get("criteria")
    if not isinstance(criteria, list) or not criteria:
        problems.append(_blocked("SPEC_EMPTY", "判据齐全性", "criteria 必须是非空列表"))
        return problems

    seen = set()
    duplicates = set()
    has_blocking = False
    for index, criterion in enumerate(criteria):
        label = f"criteria[{index}]"
        if not isinstance(criterion, dict):
            problems.append(_blocked("SPEC_INVALID", "判据结构", f"{label} 必须是对象"))
            continue
        identifier = str(criterion.get("id", "")).strip()
        label = f"{label}({identifier or '无ID'})"
        missing = [field for field in REQUIRED_FIELDS if field not in criterion]
        if missing:
            problems.append(_blocked("SPEC_INVALID", "判据结构", f"{label} 缺字段：{missing}"))
        if not identifier or not str(criterion.get("metric", "")).strip():
            problems.append(_blocked("SPEC_INVALID", "判据结构", f"{label} 的 id/metric 不能为空"))
        if identifier in seen:
            duplicates.add(identifier)
        seen.add(identifier)

        op = criterion.get("op")
        blocking = criterion.get("blocking")
        category = criterion.get("category")
        criterion_source = criterion.get("source")
        if op != "report" and op not in OPS:
            problems.append(_blocked("SPEC_INVALID", "比较符", f"{label} 的 op={op!r} 非法"))
        if not isinstance(blocking, bool):
            problems.append(_blocked("SPEC_INVALID", "blocking 类型", f"{label} 的 blocking 必须是布尔值"))
        if op == "report" and blocking is not False:
            problems.append(_blocked("SPEC_INVALID", "report 语义", f"{label} 的 report 必须 blocking=false"))
        if category not in VALID_CATEGORIES:
            problems.append(_blocked("SPEC_INVALID", "判据类别", f"{label} 的 category={category!r} 非法"))
        if not isinstance(criterion.get("unit"), str):
            problems.append(_blocked("SPEC_INVALID", "单位类型", f"{label} 的 unit 必须是字符串"))
        if not isinstance(criterion_source, str) or not _valid_criterion_source(criterion_source.strip()):
            problems.append(_blocked("SPEC_INVALID", "逐条来源", f"{label} 缺来源或含自拟/默认阈值表述"))
        if op != "report" and "value" in criterion and _finite_number(criterion.get("value")) is None:
            problems.append(_blocked("SPEC_INVALID", "阈值", f"{label} 的阈值必须是有限数值"))
        if op != "report" and blocking is True:
            has_blocking = True

    for identifier in sorted(duplicates):
        problems.append(_blocked("SPEC_DUPLICATE_ID", "判据唯一性", f"重复判据 id：{identifier}"))
    if not has_blocking:
        problems.append(_blocked("SPEC_NO_BLOCKING", "正式验收能力", "至少需要一条有效的 blocking=true 判据"))
    return problems


def evaluate_gate(spec, values, require_frozen=True, require_provenance=False):
    """正式验收默认要求冻结；require_frozen=False 仅用于显式预检。"""
    if not isinstance(spec, dict):
        return {
            "tool": "env/ctl/quality.py",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "case": "", "spec_content_sha256": "", "require_frozen": require_frozen,
            "admissible": False, "results": [],
            "blocked": [_blocked("SPEC_INVALID", "顶层结构", "quality_spec 必须是 JSON 对象")],
        }
    payload = values
    values = values.get("values", values) if isinstance(values, dict) else {}
    if not isinstance(values, dict):
        values = {}
    blocked = spec_schema_problems(spec)
    results = []

    expected_sha = str(spec.get("spec_sha256") or "").strip()
    frozen_at = str(spec.get("frozen_at") or "").strip()
    actual_sha = canonical_spec_sha256(spec)
    if require_frozen and (not expected_sha or not frozen_at):
        blocked.append(_blocked("SPEC_NOT_FROZEN", "判据冻结", "正式验收前必须冻结 spec_sha256 与 frozen_at"))
    if expected_sha and expected_sha != actual_sha:
        blocked.append(_blocked(
            "SPEC_FROZEN", "冻结判据完整性",
            f"冻结哈希不匹配：expected={expected_sha}, actual={actual_sha}",
        ))

    if require_provenance:
        provenance = payload.get("provenance") if isinstance(payload, dict) else None
        if not isinstance(payload.get("values"), dict) or not isinstance(provenance, dict):
            blocked.append(_blocked("SPEC_PROVENANCE", "结果来源", "正式验收需要 values.json 及完整 provenance"))
        else:
            if provenance.get("complete") is not True:
                blocked.append(_blocked("SPEC_PROVENANCE", "结果完整性", "存在缺失、失败或过期工况"))
            if provenance.get("spec_sha256") != actual_sha:
                blocked.append(_blocked("SPEC_PROVENANCE", "结果与判据绑定", "结果不是由当前冻结 spec 生成"))
            declared = set(provenance.get("cases") or [])
            required = {
                str(c.get("id", "")).split(".", 1)[0]
                for c in (spec.get("criteria") or [])
                if isinstance(c, dict) and c.get("blocking") is True and "." in str(c.get("id", ""))
            }
            if not required:
                blocked.append(_blocked("SPEC_PROVENANCE", "判据 ID 口径", "blocking ID 必须为 <工况>.<探针ID>"))
            elif required - declared:
                blocked.append(_blocked("SPEC_PROVENANCE", "工况覆盖", f"缺少已验证工况：{sorted(required - declared)}"))

    criteria = spec.get("criteria") if isinstance(spec.get("criteria"), list) else []
    for criterion in criteria:
        if not isinstance(criterion, dict):
            continue
        identifier = str(criterion.get("id", "")).strip() or "?"
        metric = str(criterion.get("metric", "")).strip()
        op = str(criterion.get("op", ""))
        threshold = criterion.get("value")
        blocking = criterion.get("blocking") is True
        unit = criterion.get("unit") if isinstance(criterion.get("unit"), str) else ""
        criterion_source = criterion.get("source") if isinstance(criterion.get("source"), str) else ""
        criterion_source = criterion_source.strip()
        source_valid = _valid_criterion_source(criterion_source)
        value = values.get(identifier)

        if not source_valid:
            status = "FAIL"
            reason = "缺少逐条判据来源，或来源包含模型自拟/常见默认值表述"
        elif op == "report":
            if criterion.get("blocking") is False:
                status = "RECORD"
                reason = "记录项，不参与封堵"
            else:
                status = "FAIL"
                reason = "report 必须 blocking=false"
            blocking = False
        elif value is None:
            status = "NOT_EVALUATED"
            reason = "未提供实测值"
        elif op not in OPS:
            status = "FAIL"
            reason = f"未知比较符 {op!r}"
        else:
            numeric_value = _finite_number(value)
            numeric_threshold = _finite_number(threshold)
            if numeric_value is None:
                status = "FAIL"
                reason = f"实测值不是有限数值：{value!r}"
            elif numeric_threshold is None:
                status = "FAIL"
                reason = f"阈值不是有限数值：{threshold!r}"
            else:
                passed = OPS[op](numeric_value, numeric_threshold)
                status = "PASS" if passed else "FAIL"
                reason = f"{value}{unit} {op} {threshold}{unit}"

        results.append({
            "id": identifier, "metric": metric,
            "category": str(criterion.get("category", "other")),
            "status": status, "blocking": blocking, "value": value, "unit": unit,
            "threshold": threshold, "op": op, "reason": reason, "source": criterion_source,
        })
        if blocking and status != "PASS":
            blocked.append(_blocked(identifier, metric, reason, value, unit, threshold, op))

    return {
        "tool": "env/ctl/quality.py",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "case": spec.get("case", ""),
        "spec_content_sha256": actual_sha,
        "require_frozen": require_frozen,
        "require_provenance": require_provenance,
        "admissible": not blocked,
        "results": results,
        "blocked": blocked,
    }


def freeze_spec(path):
    """结构完整后原子写回冻结元数据；畸形 spec 不允许冻结。"""
    target = Path(path)
    spec = json.loads(target.read_text(encoding="utf-8"))
    problems = spec_schema_problems(spec)
    if problems:
        detail = "；".join(f"{item['id']}: {item['reason']}" for item in problems)
        raise ValueError(f"判据结构不完整，不能冻结：{detail}")
    spec["frozen_at"] = datetime.now(timezone.utc).isoformat()
    spec["spec_sha256"] = canonical_spec_sha256(spec)
    atomic_write_json(target, spec)
    return spec


def write_evidence_bundle(directory, spec_path, values, verdict):
    """写入 spec、实测值、verdict 和 SHA256 清单，返回 manifest。"""
    target = Path(directory)
    target.mkdir(parents=True, exist_ok=True)
    spec_copy = target / "quality_spec.json"
    shutil.copyfile(spec_path, spec_copy)
    atomic_write_json(target / "values.json", values)
    atomic_write_json(target / "verdict.json", verdict)
    files = [
        {"path": name, "sha256": sha256_file(target / name)}
        for name in ("quality_spec.json", "values.json", "verdict.json")
    ]
    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "admissible": verdict["admissible"],
        "files": files,
    }
    atomic_write_json(target / "manifest.json", manifest)
    return manifest
