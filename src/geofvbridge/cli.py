"""GeoFVBridge command-line interface."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .api import (
    convert_mesh,
    default_fv_dataset_path,
    export_model,
    inspect_mesh,
    save_fv_dataset,
)
from .model import ConversionOptions
from .persistence import read_model
from .validation import validate_model


def _dump(value) -> None:
    print(json.dumps(value, indent=2, ensure_ascii=False, default=str))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="geofvbridge")
    parser.add_argument("--version", action="version", version=f"GeoFVBridge {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)
    inspect = commands.add_parser("inspect", help="Inspect a Gmsh mesh without converting it.")
    inspect.add_argument("input", type=Path)
    convert = commands.add_parser("convert", help="Convert a Gmsh mesh to GeoFV HDF5.")
    convert.add_argument("input", type=Path)
    convert.add_argument("--length-unit", default="m")
    validate = commands.add_parser("validate", help="Validate a GeoFV HDF5 model.")
    validate.add_argument("model", type=Path)
    export = commands.add_parser("export", help="Export a solver backend.")
    export.add_argument("backend", choices=("tough2", "eco2m"))
    export.add_argument("model", type=Path)
    export.add_argument("--config", required=True, type=Path)
    export.add_argument("--output", type=Path)
    commands.add_parser("gui", help="Launch the staged desktop GUI.")
    return parser


def main(argv=None) -> int:
    if argv is None and len(sys.argv) == 1:
        from .gui.app import run

        return run()
    args = _parser().parse_args(argv)
    if args.command == "inspect":
        _dump(inspect_mesh(args.input))
        return 0
    if args.command == "convert":
        options = ConversionOptions(length_unit=args.length_unit)
        model = convert_mesh(args.input, options)
        artifacts = save_fv_dataset(model, default_fv_dataset_path(args.input))
        _dump(
            {
                "model": str(artifacts.hdf5),
                "summary": str(artifacts.summary),
                "vtu": str(artifacts.vtu),
                **model.summary(),
            }
        )
        return 0 if model.report.valid else 2
    if args.command == "validate":
        model = read_model(args.model)
        report = validate_model(model)
        _dump(report.as_dict())
        return 0 if report.valid else 2
    if args.command == "export":
        config = json.loads(args.config.read_text(encoding="utf-8"))
        output = args.output or args.model.parent / "eco2m"
        _dump(export_model(args.model, args.backend, config, output))
        return 0
    if args.command == "gui":
        from .gui.app import run

        return run()
    return 1
