"""Cached, mutually exclusive TOUGH infinite-volume cell selection."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
from numpy.typing import NDArray

from .model import FVModel

IntArray = NDArray[np.int64]
FloatArray = NDArray[np.float64]


@dataclass(slots=True, frozen=True)
class BoundaryGroupIndex:
    """Faces and unique owner cells for one named exterior boundary group."""

    name: str
    face_ids: IntArray
    cell_ids: IntArray
    node_min: FloatArray
    node_max: FloatArray


@dataclass(slots=True)
class BoundarySelectionIndex:
    """Reusable NumPy index for inexpensive selector changes."""

    material_cells: dict[str, IntArray]
    boundary_groups: dict[str, BoundaryGroupIndex]
    centroids: FloatArray
    centroid_order: tuple[IntArray, IntArray, IntArray]
    centroid_sorted: tuple[FloatArray, FloatArray, FloatArray]
    boundary_face_ids: IntArray
    boundary_owner_cells: IntArray
    boundary_normals: FloatArray
    boundary_node_min: FloatArray
    boundary_node_max: FloatArray
    point_min: FloatArray
    point_max: FloatArray


@dataclass(slots=True, frozen=True)
class BoundarySelectionResult:
    """Resolved cells and supporting exterior faces for one selector."""

    method: str
    label: str
    cell_ids: IntArray
    face_ids: IntArray
    node_min: FloatArray | None = None
    node_max: FloatArray | None = None

    @property
    def cell_count(self) -> int:
        return int(self.cell_ids.size)

    @property
    def face_count(self) -> int:
        return int(self.face_ids.size)


def _axis(value: Any) -> int:
    axis = int(value)
    if axis not in (0, 1, 2):
        raise ValueError("Selection axis must be 0 (X), 1 (Y), or 2 (Z).")
    return axis


def _named(mapping: dict[str, Any], requested: Any, kind: str) -> tuple[str, Any]:
    name = str(requested).strip()
    if not name:
        raise ValueError(f"Select a {kind}.")
    if name in mapping:
        return name, mapping[name]
    matches = [(key, value) for key, value in mapping.items() if key.casefold() == name.casefold()]
    if len(matches) == 1:
        return matches[0]
    raise ValueError(f"Unknown {kind}: {name}")


def build_boundary_selection_index(model: FVModel) -> BoundarySelectionIndex:
    """Build material, boundary, coordinate, and normal lookup arrays once."""
    materials: dict[str, list[int]] = {}
    for cell in model.cells:
        materials.setdefault(cell.material, []).append(cell.id)
    material_cells = {
        name: np.asarray(ids, dtype=np.int64) for name, ids in materials.items()
    }

    grouped_faces: dict[str, list[int]] = {}
    grouped_cells: dict[str, list[int]] = {}
    grouped_min: dict[str, FloatArray] = {}
    grouped_max: dict[str, FloatArray] = {}
    face_ids: list[int] = []
    owner_cells: list[int] = []
    normals: list[FloatArray] = []
    node_min: list[FloatArray] = []
    node_max: list[FloatArray] = []
    for boundary in model.boundaries:
        face = model.faces[boundary.face]
        coordinates = np.asarray(model.points[np.asarray(face.nodes, dtype=int)], dtype=float)
        minimum = np.min(coordinates, axis=0)
        maximum = np.max(coordinates, axis=0)
        name = str(boundary.name or "UNASSIGNED")
        grouped_faces.setdefault(name, []).append(face.id)
        grouped_cells.setdefault(name, []).append(boundary.cell)
        grouped_min[name] = np.minimum(grouped_min.get(name, minimum), minimum)
        grouped_max[name] = np.maximum(grouped_max.get(name, maximum), maximum)
        face_ids.append(face.id)
        owner_cells.append(boundary.cell)
        normals.append(np.asarray(face.normal, dtype=float))
        node_min.append(minimum)
        node_max.append(maximum)

    boundary_groups = {
        name: BoundaryGroupIndex(
            name=name,
            face_ids=np.asarray(grouped_faces[name], dtype=np.int64),
            cell_ids=np.asarray(sorted(set(grouped_cells[name])), dtype=np.int64),
            node_min=np.asarray(grouped_min[name], dtype=float),
            node_max=np.asarray(grouped_max[name], dtype=float),
        )
        for name in grouped_faces
    }
    empty_vectors = np.empty((0, 3), dtype=float)
    points = np.asarray(model.points, dtype=float)
    centroids = np.asarray([cell.centroid for cell in model.cells], dtype=float)
    centroid_order = tuple(
        np.argsort(centroids[:, axis], kind="stable").astype(np.int64)
        for axis in range(3)
    )
    centroid_sorted = tuple(
        np.asarray(centroids[centroid_order[axis], axis], dtype=float)
        for axis in range(3)
    )
    return BoundarySelectionIndex(
        material_cells=material_cells,
        boundary_groups=boundary_groups,
        centroids=centroids,
        centroid_order=centroid_order,
        centroid_sorted=centroid_sorted,
        boundary_face_ids=np.asarray(face_ids, dtype=np.int64),
        boundary_owner_cells=np.asarray(owner_cells, dtype=np.int64),
        boundary_normals=np.vstack(normals) if normals else empty_vectors.copy(),
        boundary_node_min=np.vstack(node_min) if node_min else empty_vectors.copy(),
        boundary_node_max=np.vstack(node_max) if node_max else empty_vectors.copy(),
        point_min=np.min(points, axis=0) if points.size else np.zeros(3, dtype=float),
        point_max=np.max(points, axis=0) if points.size else np.zeros(3, dtype=float),
    )


def _coordinate_bounds(
    index: BoundarySelectionIndex,
    face_mask: NDArray[np.bool_],
) -> tuple[FloatArray | None, FloatArray | None]:
    if not np.any(face_mask):
        return None, None
    return (
        np.min(index.boundary_node_min[face_mask], axis=0),
        np.max(index.boundary_node_max[face_mask], axis=0),
    )


def resolve_boundary_selection(
    model: FVModel,
    selection: dict[str, Any],
    index: BoundarySelectionIndex | None = None,
) -> BoundarySelectionResult:
    """Resolve exactly one canonical infinite-volume selection method."""
    if not isinstance(selection, dict):
        raise TypeError("inactive_selection must be an object.")
    index = index or build_boundary_selection_index(model)
    method = str(selection.get("method", "")).strip().lower()
    if method == "material":
        name, cells = _named(index.material_cells, selection.get("material"), "material group")
        result = BoundarySelectionResult(method, name, cells.copy(), np.empty(0, dtype=np.int64))
    elif method == "boundary_group":
        name, group = _named(
            index.boundary_groups,
            selection.get("boundary_group"),
            "boundary face group",
        )
        result = BoundarySelectionResult(
            method,
            name,
            group.cell_ids.copy(),
            group.face_ids.copy(),
            group.node_min.copy(),
            group.node_max.copy(),
        )
    elif method == "coordinate":
        axis = _axis(selection.get("axis", 2))
        operator = str(selection.get("operator", "ge")).strip().lower()
        value = float(selection["value"])
        if operator in {"ge", ">="}:
            start = int(np.searchsorted(index.centroid_sorted[axis], value, side="left"))
            cells = index.centroid_order[axis][start:]
            symbol = ">="
        elif operator in {"le", "<="}:
            stop = int(np.searchsorted(index.centroid_sorted[axis], value, side="right"))
            cells = index.centroid_order[axis][:stop]
            symbol = "<="
        else:
            raise ValueError("Coordinate operator must be ge (>=) or le (<=).")
        result = BoundarySelectionResult(
            method,
            f"{'XYZ'[axis]}{symbol}{value:g}",
            np.sort(cells).astype(np.int64, copy=False),
            np.empty(0, dtype=np.int64),
        )
    elif method == "exposed_face":
        axis = _axis(selection.get("axis", 2))
        direction = int(selection.get("direction", 1))
        if direction not in (-1, 1):
            raise ValueError("Exposed-face direction must be 1 or -1.")
        threshold = float(selection.get("minimum_normal", 0.1))
        if not 0.0 <= threshold <= 1.0:
            raise ValueError("Minimum normal component must be between 0 and 1.")
        mask = direction * index.boundary_normals[:, axis] >= threshold
        cells = np.unique(index.boundary_owner_cells[mask]).astype(np.int64)
        minimum, maximum = _coordinate_bounds(index, mask)
        result = BoundarySelectionResult(
            method,
            f"exposed {'+' if direction > 0 else '-'}{'XYZ'[axis]}",
            cells,
            index.boundary_face_ids[mask].copy(),
            minimum,
            maximum,
        )
    elif method == "global_plane":
        axis = _axis(selection.get("axis", 2))
        side = str(selection.get("side", "max")).strip().lower()
        if side not in {"max", "min"}:
            raise ValueError("Global-plane side must be max or min.")
        span = float(index.point_max[axis] - index.point_min[axis])
        raw_tolerance = selection.get("tolerance")
        tolerance = (
            max(span, 1.0) * 1.0e-8
            if raw_tolerance in (None, "")
            else float(raw_tolerance)
        )
        if tolerance < 0.0:
            raise ValueError("Global-plane tolerance cannot be negative.")
        if side == "max":
            extreme = float(index.point_max[axis])
            mask = index.boundary_node_min[:, axis] >= extreme - tolerance
        else:
            extreme = float(index.point_min[axis])
            mask = index.boundary_node_max[:, axis] <= extreme + tolerance
        cells = np.unique(index.boundary_owner_cells[mask]).astype(np.int64)
        minimum, maximum = _coordinate_bounds(index, mask)
        result = BoundarySelectionResult(
            method,
            f"global {side} {'XYZ'[axis]}={extreme:g}",
            cells,
            index.boundary_face_ids[mask].copy(),
            minimum,
            maximum,
        )
    else:
        raise ValueError(
            "Selection method must be material, boundary_group, coordinate, "
            "exposed_face, or global_plane."
        )
    if result.cell_count == 0:
        raise ValueError(f"The {result.method} selection matched no cells.")
    return result


def selection_preview(
    model: FVModel,
    selection: dict[str, Any],
    index: BoundarySelectionIndex | None = None,
    *,
    sample_limit: int = 20,
) -> tuple[BoundarySelectionResult, dict[str, Any]]:
    """Return a compact GUI report without constructing every TOUGH export cell."""
    result = resolve_boundary_selection(model, selection, index)
    samples = [
        {
            "cell_id": int(cell_id),
            "material": model.cells[int(cell_id)].material,
            "centroid": model.cells[int(cell_id)].centroid.tolist(),
        }
        for cell_id in result.cell_ids[: max(int(sample_limit), 0)]
    ]
    return result, {
        "valid": True,
        "selection_method": result.method,
        "selection_label": result.label,
        "boundary_face_count": result.face_count,
        "inactive_count": result.cell_count,
        "node_coordinate_min": result.node_min.tolist() if result.node_min is not None else None,
        "node_coordinate_max": result.node_max.tolist() if result.node_max is not None else None,
        "sample_cells": samples,
        "sample_limit": int(sample_limit),
    }
