"""可扩展的 COMSOL Java API 类型清册与创建守卫。

清册不是完整手册。未知类型必须先查证并做最小探针，再注册；不能据此推断
当前安装缺少某项能力。
"""
from __future__ import annotations

import difflib

_MANUAL = "COMSOL Programming Reference Manual（按安装版本核对）"
# 真机探针来源标记：物理中立、已读回验证的通用节点类型。
_PROBE_63 = "真机探针 COMSOL 6.3 build 290（可复用节点类型）"

REGISTRY = {
    "mesh": {
        name: _MANUAL for name in (
            "FreeTet", "FreeTri", "FreeQuad", "Sweep", "Map", "BndLayer",
            "Distribution", "Size", "Copy", "Refine", "Convert",
        )
    },
    "geometry": {
        name: _MANUAL for name in (
            "Block", "Cylinder", "Sphere", "Cone", "Rectangle", "Circle",
            "Polygon", "WorkPlane", "Union", "Difference", "Intersection",
            "Revolve", "Extrude", "Import", "Compose", "Array",
        )
    },
    "material": {
        name: _MANUAL for name in ("Common", "External", "Link", "PorousMedia", "Switch")
    },
    "selection": {
        name: _MANUAL for name in (
            "Box", "Explicit", "Adjacent", "Ball", "Cylinder", "Union",
            "Difference", "Complement", "Disk",
        )
    },
    "study": {
        name: _MANUAL for name in (
            "Stationary", "Transient", "Eigenfrequency", "Frequency", "Parametric",
        )
    },
    "dataset": {
        name: _MANUAL for name in (
            "Solution", "Mesh", "CutPlane", "CutLine2D", "CutLine3D",
            "CutPoint1D", "CutPoint2D", "CutPoint3D", "Join", "Maximum", "Minimum",
            # Grid2D：类型创建已实测（6.3 build 290）；其坐标/分辨率属性名
            # 未探通（gridx/gridy/x/y/resolution/method 均报 Unknown_property），
            # 登记类型名不代表属性可用，使用前须自行探针。
            "Grid2D",
        )
    },
    # solver 序列节点：createAutoSequences 之外手工组织求解器时使用。
    # 只登记类型名，不含任何研究类型、属性或物理场专属设置。
    "solver": {
        name: _PROBE_63 for name in (
            "Study", "StudyStep", "Variables", "Stationary",
            "Parametric", "Eigenvalue",
        )
    },
}

ALIASES = {
    "mesh": {"Swept": "Sweep", "Mapped": "Map", "BoundaryLayer": "BndLayer"},
    "study": {"TimeDependent": "Transient"},
}


class ApiRegistryError(ValueError):
    """API 类型未注册、类别错误或缺少验证来源。"""


def _suggestion(category, name):
    alias = ALIASES.get(category, {}).get(name)
    if alias:
        return f"；应使用官方类型 {alias!r}"
    candidates = difflib.get_close_matches(name, REGISTRY.get(category, {}), n=3, cutoff=0.45)
    return f"；相近候选：{', '.join(candidates)}" if candidates else ""


def assert_type(category, name):
    """返回已注册的精确类型名；GUI 别名和未知名称一律拒绝。"""
    if category not in REGISTRY:
        raise ApiRegistryError(f"未知 API 类别 {category!r}；已有类别：{sorted(REGISTRY)}")
    if name not in REGISTRY[category]:
        raise ApiRegistryError(
            f"类别 {category!r} 未注册类型 {name!r}{_suggestion(category, name)}。"
            "请先查证并用最小探针验证，再 register_type；不要归因于环境缺能力。"
        )
    return name


def lookup(category, name):
    """查询已注册类型及其来源。"""
    canonical = assert_type(category, name)
    return {"category": category, "type": canonical, "source": REGISTRY[category][canonical]}


def register_type(category, name, source, aliases=()):
    """验证后扩展注册表；source 必须能定位手册或探针证据。"""
    if not category.strip() or not name.strip() or not source.strip():
        raise ApiRegistryError("category、name、source 均不能为空")
    REGISTRY.setdefault(category, {})[name] = source
    for alias in aliases:
        if alias.strip():
            ALIASES.setdefault(category, {})[alias] = name
    return lookup(category, name)


def create_checked(feature_list, tag, type_name, category, **kwargs):
    """只有通过注册表校验后才调用底层 create。"""
    canonical = assert_type(category, type_name)
    return feature_list.create(tag, canonical, **kwargs)
