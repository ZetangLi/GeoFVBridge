"""Prepare solver-specific meshes without mutating the reusable FV dataset."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import meshio
import numpy as np

from .converter import ConversionError, convert_file, convert_meshio
from .extrusion import extrude_meshio
from .model import ExtrusionOptions, FVModel
from .persistence import read_model


def _unique_name(name: str, used: set[str], prefix: str) -> str:
    candidate = name or prefix
    if candidate not in used:
        used.add(candidate)
        return candidate
    index = 2
    while f"{prefix}_{candidate}_{index}" in used:
        index += 1
    candidate = f"{prefix}_{candidate}_{index}"
    used.add(candidate)
    return candidate


def fv_model_to_extrusion_mesh(model: FVModel) -> meshio.Mesh:
    """Reconstruct the semantic 2-D mesh needed for native extrusion.

    Only the reusable FV dataset is consulted: top-dimensional cells retain
    their nodes and materials, named FV boundary edges become physical lines,
    and source candidates become physical vertices at their stored locations.
    """
    if model.dimension != 2:
        raise ConversionError("Only a two-dimensional FV model can be reconstructed for extrusion.")

    points = np.asarray(model.points, dtype=float).copy()
    used_names: set[str] = set()
    next_tag = 1
    material_tags: dict[str, int] = {}
    field_data: dict[str, np.ndarray] = {}
    for material in dict.fromkeys(cell.material for cell in model.cells):
        name = _unique_name(material, used_names, "MATERIAL")
        material_tags[material] = next_tag
        field_data[name] = np.asarray([next_tag, 2], dtype=int)
        next_tag += 1

    cells: list[tuple[str, np.ndarray]] = []
    physical: list[np.ndarray] = []
    for cell_type in dict.fromkeys(cell.cell_type for cell in model.cells):
        selected = [cell for cell in model.cells if cell.cell_type == cell_type]
        cells.append((cell_type, np.asarray([cell.nodes for cell in selected], dtype=int)))
        physical.append(
            np.asarray([material_tags[cell.material] for cell in selected], dtype=int)
        )

    boundary_rows: dict[str, list[tuple[int, ...]]] = {}
    for boundary in model.boundaries:
        boundary_rows.setdefault(boundary.name, []).append(model.faces[boundary.face].nodes)
    for boundary_name, rows in boundary_rows.items():
        name = _unique_name(boundary_name, used_names, "BOUNDARY")
        tag = next_tag
        next_tag += 1
        field_data[name] = np.asarray([tag, 1], dtype=int)
        cells.append(("line", np.asarray(rows, dtype=int)))
        physical.append(np.full(len(rows), tag, dtype=int))

    if model.sources:
        source_points = np.vstack([source.location for source in model.sources])
        offset = len(points)
        points = np.vstack((points, source_points))
        for index, source in enumerate(model.sources):
            name = _unique_name(source.name, used_names, "SOURCE")
            tag = next_tag
            next_tag += 1
            field_data[name] = np.asarray([tag, 0], dtype=int)
            cells.append(("vertex", np.asarray([[offset + index]], dtype=int)))
            physical.append(np.asarray([tag], dtype=int))

    return meshio.Mesh(
        points,
        cells,
        cell_data={"gmsh:physical": physical},
        field_data=field_data,
    )


def prepare_solver_model(
    model_or_path: FVModel | str | Path,
    extrusion: ExtrusionOptions | None = None,
) -> FVModel:
    """Return an independent three-dimensional model for a solver backend.

    Three-dimensional datasets are copied unchanged. Two-dimensional datasets
    require explicit extrusion settings and are extruded only in this solver
    preparation stage.
    """
    if isinstance(model_or_path, FVModel):
        native = model_or_path
    else:
        path = Path(model_or_path)
        native = read_model(path) if path.name.lower().endswith((".geofv.h5", ".h5")) else convert_file(path)

    if native.dimension == 3:
        prepared = deepcopy(native)
        prepared.metadata = {
            **prepared.metadata,
            "solver_preparation": {"mode": "direct_3d", "native_dimension": 3},
        }
        return prepared
    if native.dimension != 2:
        raise ConversionError("Solver preparation requires a two- or three-dimensional FV model.")
    if extrusion is None:
        raise ConversionError("A two-dimensional FV model requires solver-stage extrusion settings.")

    reconstructed = fv_model_to_extrusion_mesh(native)
    extruded = extrude_meshio(
        reconstructed,
        direction=extrusion.direction,
        layer_thicknesses=extrusion.layer_thicknesses,
    )
    prepared = convert_meshio(extruded, options=deepcopy(native.options))
    prepared.metadata = {
        **prepared.metadata,
        "source_path": str(native.source_path) if native.source_path else None,
        "solver_preparation": {
            "mode": "extruded_2d",
            "native_dimension": 2,
            "direction": list(extrusion.direction),
            "layer_thicknesses": list(extrusion.layer_thicknesses),
        },
    }
    return prepared
