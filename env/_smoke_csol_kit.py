#!/usr/bin/env python3
"""公共库离线冒烟；--comsol 时另做最小几何/网格/保存/加载验证。"""
from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

ENV = Path(__file__).resolve().parent
ROOT = ENV.parent
sys.path.insert(0, str(ENV))

import csol_kit as K  # noqa: E402


class _Stat:
    def __init__(self, count): self.count = count
    def getNumElem(self): return self.count


class _Mesh:
    def __init__(self, count): self.count = count
    def stat(self): return _Stat(self.count)


class _Geom:
    def getNDomains(self): return 1


def offline_smoke():
    checks = 0
    assert K.check_mesh(_Mesh(3)) == 3; checks += 1
    try:
        K.check_mesh(_Mesh(0))
    except K.CsolError:
        checks += 1
    else:
        raise AssertionError("零网格未被拒绝")
    assert K.check_domains(_Geom(), expect=1) == 1; checks += 1
    with tempfile.TemporaryDirectory() as td:
        target = Path(td) / "atomic.json"
        K.atomic_write_json(target, {"ok": True})
        assert target.is_file(); checks += 1
    from api_registry import assert_type
    assert assert_type("mesh", "Sweep") == "Sweep"; checks += 1
    print(f"[smoke] 离线 {checks}/{checks} 项通过；未启动 COMSOL")
    return 0


def comsol_smoke():
    from comsol_boot import runtime_metadata, start_client
    client = start_client()
    model = None
    loaded = None
    try:
        model = client.create("ComsolSimKitSmoke")
        java = model.java
        java.component().create("comp1", True)
        component = java.component("comp1")
        component.geom().create("geom1", 3)
        geometry = component.geom("geom1")
        geometry.create("blk1", "Block")
        geometry.run()
        component.mesh().create("mesh1")
        mesh = component.mesh("mesh1")
        mesh.create("ftet1", "FreeTet")
        mesh.run()
        count = K.check_mesh(mesh, label="comsol-smoke")
        target = ROOT / ".runtime" / "smoke" / "minimal.mph"
        target.parent.mkdir(parents=True, exist_ok=True)
        model.save(str(target))
        runtime_metadata(ROOT / "config" / "config.toml", actual_version=model.version())
        loaded = client.load(str(target))
        assert loaded is not None
        print(f"[smoke] COMSOL 最小模型通过：{count} 个网格单元；保存/加载成功")
        return 0
    finally:
        if loaded is not None:
            client.remove(loaded)
        if model is not None:
            client.remove(model)


def main():
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--comsol", action="store_true", help="额外运行本机 COMSOL 最小模型")
    args = parser.parse_args()
    rc = offline_smoke()
    return rc or (comsol_smoke() if args.comsol else 0)


if __name__ == "__main__":
    raise SystemExit(main())
