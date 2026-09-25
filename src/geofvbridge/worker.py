"""Isolated conversion worker used by the desktop application."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
import traceback
from pathlib import Path

from .api import FV_DATASET_SUFFIX, convert_source, save_fv_dataset
from .model import ConversionOptions
from .petrel import PetrelImportOptions

STAGE_RANGES = {
    "mesh_conversion": (2, 85),
    "read_grid": (2, 10),
    "build_geometry": (10, 35),
    "build_topology": (35, 55),
    "finite_volume_geometry": (55, 75),
    "source_connections": (75, 86),
    "vertical_coarsening": (86, 94),
}


def _emit(payload: dict[str, object]) -> None:
    # Keep the QProcess protocol ASCII-only. On Windows a redirected child
    # stdout can otherwise use the active ANSI code page while the GUI decodes
    # the pipe as UTF-8, corrupting non-ASCII paths before json.loads sees them.
    print(json.dumps(payload, ensure_ascii=True, default=str), flush=True)


def _normalized_output(path: Path) -> Path:
    if not path.name.lower().endswith(FV_DATASET_SUFFIX):
        path = path.with_name(path.name + FV_DATASET_SUFFIX)
    return path


def _artifact_paths(hdf5: Path) -> tuple[Path, Path, Path]:
    base = hdf5.name[: -len(FV_DATASET_SUFFIX)]
    return (
        hdf5,
        hdf5.with_name(base + ".summary.json"),
        hdf5.with_name(base + ".vtu"),
    )


def run_request(request: dict[str, object]) -> dict[str, object]:
    source = Path(str(request["input"])).resolve()
    output = _normalized_output(Path(str(request["output"])).resolve())
    output.parent.mkdir(parents=True, exist_ok=True)
    raw_staging = request.get("staging_dir")
    if raw_staging:
        staging = Path(str(raw_staging)).resolve()
        staging.mkdir(parents=True, exist_ok=True)
    else:
        staging = Path(
            tempfile.mkdtemp(prefix=".geofvbridge-", dir=output.parent)
        ).resolve()
    if not staging.name.startswith(".geofvbridge-"):
        raise ValueError("The conversion staging directory must use the .geofvbridge- prefix.")

    last_percent = -1

    def report(stage: str, current: int, total: int) -> None:
        nonlocal last_percent
        lower, upper = STAGE_RANGES.get(stage, (0, 90))
        fraction = current / total if total else 0.0
        percent = max(last_percent, min(upper, round(lower + fraction * (upper - lower))))
        last_percent = percent
        _emit(
            {
                "event": "progress",
                "stage": stage,
                "current": current,
                "total": total,
                "percent": percent,
            }
        )

    gmsh_options = ConversionOptions(
        length_unit=str(request.get("length_unit", "m"))
    )
    raw_petrel = dict(request.get("petrel_options") or {})
    petrel_options = PetrelImportOptions(
        grid_mode=str(raw_petrel.get("grid_mode", "native")).replace("-", "_"),
        initial_state=str(raw_petrel.get("initial_state", "none")),
        coordinate_mode=str(raw_petrel.get("coordinate_mode", "map")),
        origin_x=float(raw_petrel.get("origin_x", 0.0)),
        origin_y=float(raw_petrel.get("origin_y", 0.0)),
        z_mode=str(raw_petrel.get("z_mode", "negative-depth")),
        tolerance=float(raw_petrel.get("tolerance", 1.0e-6)),
        property_paths=tuple(Path(value) for value in raw_petrel.get("properties", [])),
        nnc_path=(
            Path(str(raw_petrel["nnc"]))
            if raw_petrel.get("nnc")
            else None
        ),
        conversion_options=gmsh_options,
    )

    try:
        _emit({"event": "progress", "stage": "starting", "percent": 0})
        model = convert_source(
            source,
            gmsh_options=gmsh_options,
            petrel_options=petrel_options,
            progress_callback=report,
        )
        if not model.report.valid:
            raise ValueError(
                f"Conversion produced {len(model.report.errors)} validation error(s)."
            )
        _emit({"event": "progress", "stage": "saving", "percent": 95})
        staged_hdf5 = staging / output.name
        artifacts = save_fv_dataset(model, staged_hdf5)
        staged_paths = (artifacts.hdf5, artifacts.summary, artifacts.vtu)
        final_paths = _artifact_paths(output)
        for staged_path, final_path in zip(staged_paths[1:], final_paths[1:]):
            os.replace(staged_path, final_path)
        os.replace(staged_paths[0], final_paths[0])
        result = {
            "model": str(final_paths[0]),
            "summary": str(final_paths[1]),
            "vtu": str(final_paths[2]),
            **model.summary(),
        }
        _emit({"event": "progress", "stage": "complete", "percent": 100})
        _emit({"event": "complete", "result": result})
        return result
    finally:
        if staging.exists() and staging.name.startswith(".geofvbridge-"):
            shutil.rmtree(staging, ignore_errors=True)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m geofvbridge.worker")
    parser.add_argument("--request", required=True, type=Path)
    return parser


def main(argv=None) -> int:
    args = _parser().parse_args(argv)
    try:
        request = json.loads(args.request.read_text(encoding="utf-8"))
        run_request(request)
        return 0
    except Exception as error:
        _emit({"event": "error", "message": str(error)})
        traceback.print_exc(file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
