"""单工况执行器：参数复位、按工况双模型、求解、哈希与结果落盘。"""
import argparse

import paths
from paths import CASE, DATA, ROOT, main_mph, solved_mph
from case_spec import RESET_PARAMS, case_params, fingerprint
from comsol_boot import runtime_metadata, start_client
from csol_kit import atomic_write_json, check_solution, sha256_file, solve
from model_common import build_model


def model_record(path):
    return {"path": path.relative_to(CASE).as_posix(), "sha256": sha256_file(path)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", required=True)
    args = parser.parse_args()
    parameters = case_params(args.case)
    client = start_client(ROOT / "config" / "config.toml")
    model = None
    try:
        bundle = build_model(client, args.case, parameters, RESET_PARAMS)
        model = bundle["model"]
        main_path = main_mph(args.case)
        solved_path = solved_mph(args.case)
        model.save(str(main_path))
        count = solve(model, bundle["mesh"], study=bundle["study"])
        values = check_solution(
            model, bundle["probes"], require_nonzero=False,
            reducers=bundle.get("reducers"),
        )
        model.save(str(solved_path))
        output = {
            "case": args.case,
            "params": parameters,
            "status": "OK",
            "mesh_elements": count,
            "values": values,
            "model_files": {
                "main": model_record(main_path),
                "solved": model_record(solved_path),
            },
            "runtime": runtime_metadata(
                ROOT / "config" / "config.toml", actual_version=model.version()
            ),
            "_fingerprints": fingerprint(args.case),
        }
        atomic_write_json(DATA / f"工况_{args.case}.json", output)
        return 0
    finally:
        if model is not None:
            client.remove(model)


if __name__ == "__main__":
    raise SystemExit(main())
