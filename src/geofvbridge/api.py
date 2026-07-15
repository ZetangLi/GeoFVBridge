"""Stable high-level API used by the CLI and GUI."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import meshio

from .backends import get_backend, list_backends
from .converter import cell_type_dimension, convert_file
from .model import ConversionOptions, ExtrusionOptions, FVModel
from .persistence import read_model, write_model
from .solver import prepare_solver_model as _prepare_solver_model
from .validation import validate_model as _validate_model
from .visualization import to_pyvista as _to_pyvista
from .visualization import write_vtu


@dataclass(frozen=True, slots=True)
class DatasetArtifacts:
    hdf5: Path
    summary: Path
    vtu: Path


FV_DATASET_SUFFIX = ".geofv.h5"


def inspect_mesh(path: str | Path) -> dict:
    path = Path(path)
    mesh = meshio.read(path)
    types: dict[str, int] = {}
    dimensions: list[int] = []
    for block in mesh.cells:
        types[block.type] = types.get(block.type, 0) + len(block.data)
        dimension = cell_type_dimension(block.type)
        if dimension is not None:
            dimensions.append(dimension)
    physical_groups = {
        name: {"tag": int(values[0]), "dimension": int(values[1])}
        for name, values in mesh.field_data.items()
        if len(values) >= 2
    }
    points = mesh.points
    bounds = {
        axis: [float(points[:, index].min()), float(points[:, index].max())]
        for index, axis in enumerate(("x", "y", "z"))
        if len(points) and points.shape[1] > index
    }
    return {
        "path": str(path.resolve()),
        "points": len(mesh.points),
        "dimension": max(dimensions) if dimensions else None,
        "cell_types": types,
        "physical_groups": physical_groups,
        "coordinate_bounds": bounds,
    }


def convert_mesh(
    path: str | Path,
    options: ConversionOptions | None = None,
    *,
    extrusion: ExtrusionOptions | None = None,
) -> FVModel:
    return convert_file(path, options, extrusion)


def default_fv_dataset_path(input_path: str | Path) -> Path:
    """Return the side-by-side dataset path derived from an input file name."""
    path = Path(input_path)
    if path.name.lower().endswith(FV_DATASET_SUFFIX):
        return path
    return path.with_name(path.stem + FV_DATASET_SUFFIX)


def save_fv_dataset(model: FVModel, path: str | Path) -> DatasetArtifacts:
    path = Path(path)
    if not path.name.lower().endswith(FV_DATASET_SUFFIX):
        path = path.with_name(path.name + FV_DATASET_SUFFIX)
    base_name = path.name[: -len(FV_DATASET_SUFFIX)]
    summary = path.with_name(base_name + ".summary.json")
    vtu = path.with_name(base_name + ".vtu")
    write_model(model, path, summary)
    write_vtu(model, vtu)
    return DatasetArtifacts(path, summary, vtu)


def load_fv_dataset(path: str | Path) -> FVModel:
    return read_model(path)


def prepare_solver_model(
    model_or_path: FVModel | str | Path,
    extrusion: ExtrusionOptions | None = None,
) -> FVModel:
    """Prepare a three-dimensional model for a solver backend.

    Three-dimensional FV datasets pass through unchanged. Two-dimensional
    datasets are extruded here, after the reusable native-dimensional dataset
    has already been created and saved.
    """
    return _prepare_solver_model(model_or_path, extrusion)


def to_pyvista(
    model: FVModel,
    display_mode: str = "material",
    *,
    inactive_cells: Iterable[int] | None = None,
    visible_materials: Iterable[str] | None = None,
):
    """Build a display bundle, optionally filtered by material name."""
    return _to_pyvista(
        model,
        display_mode,
        inactive_cells=inactive_cells,
        visible_materials=visible_materials,
    )


def validate_model(model_or_path: FVModel | str | Path):
    model = read_model(model_or_path) if isinstance(model_or_path, (str, Path)) else model_or_path
    return _validate_model(model)


def _backend_config(config) -> dict:
    if isinstance(config, (str, Path)):
        return json.loads(Path(config).read_text(encoding="utf-8"))
    return dict(config)


def _solver_extrusion(config: dict) -> ExtrusionOptions:
    settings = config.get("extrusion")
    if not isinstance(settings, dict):
        raise ValueError(
            "A native 2-D FV dataset requires an 'extrusion' object in the backend config."
        )
    direction = settings.get("direction", settings.get("axis", "y"))
    if isinstance(direction, str):
        axes = {
            "x": (1.0, 0.0, 0.0),
            "y": (0.0, 1.0, 0.0),
            "z": (0.0, 0.0, 1.0),
        }
        try:
            direction = axes[direction.lower()]
        except KeyError as error:
            raise ValueError("Extrusion axis must be x, y, or z.") from error
    direction = tuple(float(value) for value in direction)
    if len(direction) != 3:
        raise ValueError("Extrusion direction must contain three components.")
    raw_layers = settings.get("layer_thicknesses")
    if raw_layers is not None:
        layer_thicknesses = tuple(float(value) for value in raw_layers)
    else:
        total = float(settings.get("total_thickness", settings.get("thickness", 0.0)))
        layers = int(settings.get("layers", 1))
        if total <= 0.0 or layers <= 0:
            raise ValueError("Extrusion total_thickness and layers must be positive.")
        layer_thicknesses = (total / layers,) * layers
    return ExtrusionOptions(direction, layer_thicknesses)


def _prepare_backend_model(model: FVModel, adapter, config: dict) -> FVModel:
    if adapter.identifier == "tough2-eco2m" and model.dimension == 2:
        return _prepare_solver_model(model, _solver_extrusion(config))
    return model


def export_model(model_or_path, backend: str, config, output_dir):
    model = read_model(model_or_path) if isinstance(model_or_path, (str, Path)) else model_or_path
    adapter = get_backend(backend)
    config = _backend_config(config)
    model = _prepare_backend_model(model, adapter, config)
    errors = adapter.validate(model, config)
    if errors:
        raise ValueError(f"{adapter.display_name} validation failed:\n- " + "\n- ".join(errors))
    return adapter.export(model, config, output_dir)


def export_solver_mesh(model_or_path, backend: str, config, output_dir):
    """Export only the solver mesh stage, without flow.inp or INCON."""
    model = read_model(model_or_path) if isinstance(model_or_path, (str, Path)) else model_or_path
    adapter = get_backend(backend)
    config = _backend_config(config)
    model = _prepare_backend_model(model, adapter, config)
    if adapter.export_mesh is None:
        raise NotImplementedError(f"{adapter.display_name} does not provide a mesh-only export.")
    errors = adapter.validate(model, config)
    if errors:
        raise ValueError(f"{adapter.display_name} validation failed:\n- " + "\n- ".join(errors))
    return adapter.export_mesh(model, config, output_dir)


def read_results(path, model_or_path, backend: str = "eco2m"):
    model = read_model(model_or_path) if isinstance(model_or_path, (str, Path)) else model_or_path
    return get_backend(backend).parse_results(path, model)


def available_backends() -> list[dict[str, str]]:
    return [
        {"identifier": adapter.identifier, "display_name": adapter.display_name}
        for adapter in list_backends()
    ]
