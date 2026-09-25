"""Meshio and optional PyVista views of the solver-independent FV model."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import meshio
import numpy as np

from .model import FVModel


@dataclass(slots=True)
class VisualizationBundle:
    grid: Any
    overlay: Any | None = None
    scalars: str | None = None
    categorical: bool = False


def _block_layout(model: FVModel):
    cell_types = list(dict.fromkeys(cell.cell_type for cell in model.cells))
    ids_by_block = [
        [cell.id for cell in model.cells if cell.cell_type == cell_type]
        for cell_type in cell_types
    ]
    blocks = [
        (cell_type, np.asarray([model.cells[cell_id].nodes for cell_id in ids], dtype=int))
        for cell_type, ids in zip(cell_types, ids_by_block, strict=True)
    ]
    return blocks, ids_by_block


def model_to_meshio(model: FVModel) -> meshio.Mesh:
    """Create a portable visualization mesh with FV cell attributes."""
    blocks, ids_by_block = _block_layout(model)
    materials = list(dict.fromkeys(cell.material for cell in model.cells))
    material_ids = {name: index for index, name in enumerate(materials)}
    orthogonality = np.ones(len(model.cells), dtype=float)
    for connection in model.connections:
        orthogonality[connection.cell1] = min(
            orthogonality[connection.cell1], connection.orthogonality
        )
        orthogonality[connection.cell2] = min(
            orthogonality[connection.cell2], connection.orthogonality
        )
    boundary_count = np.zeros(len(model.cells), dtype=int)
    for boundary in model.boundaries:
        boundary_count[boundary.cell] += 1
    values = {
        'cell_id': np.asarray([cell.id for cell in model.cells], dtype=int),
        'material_id': np.asarray([material_ids[cell.material] for cell in model.cells], dtype=int),
        'cell_measure': np.asarray([cell.measure for cell in model.cells], dtype=float),
        'orthogonality_min': orthogonality,
        'boundary_face_count': boundary_count,
    }
    cell_data = {
        name: [array[np.asarray(ids, dtype=int)] for ids in ids_by_block]
        for name, array in values.items()
    }
    field_data = {
        f'MATERIAL_{index}_{name}': np.asarray([index, model.dimension], dtype=int)
        for name, index in material_ids.items()
    }
    return meshio.Mesh(model.points, blocks, cell_data=cell_data, field_data=field_data)


def write_vtu(model: FVModel, path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    meshio.write(path, model_to_meshio(model), binary=True)
    return path


def _boundary_overlay(pv, model: FVModel):
    faces: list[int] = []
    boundary_ids: list[int] = []
    owner_cell_ids: list[int] = []
    for boundary in model.boundaries:
        nodes = model.faces[boundary.face].nodes
        faces.extend((len(nodes), *nodes))
        boundary_ids.append(boundary.id)
        owner_cell_ids.append(boundary.cell)
    overlay = pv.PolyData(model.points, faces=np.asarray(faces, dtype=int))
    overlay.cell_data['boundary_id'] = np.asarray(boundary_ids, dtype=int)
    overlay.cell_data['face_id'] = np.asarray(
        [boundary.face for boundary in model.boundaries], dtype=int
    )
    overlay.cell_data['owner_cell_id'] = np.asarray(owner_cell_ids, dtype=int)
    return overlay


def _connection_overlay(pv, model: FVModel):
    if not model.connections:
        return pv.PolyData()
    points = np.vstack(
        [
            coordinate
            for connection in model.connections
            for coordinate in (
                model.cells[connection.cell1].centroid,
                connection.intersection,
                model.cells[connection.cell2].centroid,
            )
        ]
    )
    lines: list[int] = []
    values: list[float] = []
    cell1_ids: list[int] = []
    cell2_ids: list[int] = []
    for index, connection in enumerate(model.connections):
        start = 3 * index
        lines.extend((2, start, start + 1, 2, start + 1, start + 2))
        values.extend((connection.orthogonality, connection.orthogonality))
        cell1_ids.extend((connection.cell1, connection.cell1))
        cell2_ids.extend((connection.cell2, connection.cell2))
    overlay = pv.PolyData(points, lines=np.asarray(lines, dtype=int))
    overlay.cell_data['orthogonality'] = np.asarray(values, dtype=float)
    overlay.cell_data['cell1_id'] = np.asarray(cell1_ids, dtype=int)
    overlay.cell_data['cell2_id'] = np.asarray(cell2_ids, dtype=int)
    return overlay


def _extract_grid_cells(grid, visible_cell_ids: set[int]):
    cell_ids = np.asarray(grid.cell_data['cell_id'], dtype=int)
    indices = np.flatnonzero(np.isin(cell_ids, tuple(visible_cell_ids)))
    return grid.extract_cells(indices)


def filter_visualization_bundle(
    bundle: VisualizationBundle,
    visible_cell_ids: Iterable[int] | None,
    display_mode: str,
) -> VisualizationBundle:
    """Return a display-only subset without mutating the cached full bundle."""
    if visible_cell_ids is None:
        return bundle
    try:
        import pyvista as pv
    except ImportError as error:
        raise RuntimeError(
            "PyVista visualization requires the 'visualization' optional dependencies."
        ) from error
    visible = {int(value) for value in visible_cell_ids}
    mode = display_mode.lower().replace('-', '_')
    grid = _extract_grid_cells(bundle.grid, visible)
    overlay = bundle.overlay
    if overlay is not None:
        if mode in {'boundary', 'boundaries', 'tough_inactive'}:
            owners = np.asarray(overlay.cell_data.get('owner_cell_id', ()), dtype=int)
            overlay = overlay.extract_cells(np.flatnonzero(np.isin(owners, tuple(visible))))
        elif mode in {'connection', 'connections', 'fv_topology'}:
            cell1 = np.asarray(overlay.cell_data.get('cell1_id', ()), dtype=int)
            cell2 = np.asarray(overlay.cell_data.get('cell2_id', ()), dtype=int)
            mask = np.isin(cell1, tuple(visible)) & np.isin(cell2, tuple(visible))
            overlay = overlay.extract_cells(np.flatnonzero(mask))
        elif mode in {'source', 'sources'}:
            owner_ids = np.asarray(overlay.point_data.get('cell_id', ()), dtype=int)
            mask = np.isin(owner_ids, tuple(visible))
            filtered = pv.PolyData(np.asarray(overlay.points)[mask])
            for name, values in overlay.point_data.items():
                filtered.point_data[name] = np.asarray(values)[mask]
            overlay = filtered
    return VisualizationBundle(
        grid,
        overlay,
        scalars=bundle.scalars,
        categorical=bundle.categorical,
    )


def to_pyvista(
    model: FVModel,
    display_mode: str = 'material',
    *,
    inactive_cells: Iterable[int] | None = None,
    visible_materials: Iterable[str] | None = None,
) -> VisualizationBundle:
    """Return a PyVista grid and the optional FV topology/semantic overlay."""
    try:
        import pyvista as pv
    except ImportError as error:
        raise RuntimeError(
            "PyVista visualization requires the 'visualization' optional dependencies."
        ) from error
    grid = pv.from_meshio(model_to_meshio(model))
    mode = display_mode.lower().replace('-', '_')
    bundle: VisualizationBundle
    if mode in {'material', 'materials'}:
        bundle = VisualizationBundle(grid, scalars='material_id', categorical=True)
    elif mode in {'quality', 'orthogonality'}:
        bundle = VisualizationBundle(grid, scalars='orthogonality_min')
    elif mode in {'boundary', 'boundaries'}:
        bundle = VisualizationBundle(
            grid, _boundary_overlay(pv, model), 'boundary_id', categorical=True
        )
    elif mode in {'connection', 'connections', 'fv_topology'}:
        bundle = VisualizationBundle(grid, _connection_overlay(pv, model), 'orthogonality')
    elif mode in {'source', 'sources'}:
        points = (
            np.vstack([model.cells[source.cell].centroid for source in model.sources])
            if model.sources
            else np.empty((0, 3), dtype=float)
        )
        overlay = pv.PolyData(points)
        overlay.point_data['source_id'] = np.asarray(
            [source.id for source in model.sources], dtype=int
        )
        overlay.point_data['cell_id'] = np.asarray(
            [source.cell for source in model.sources], dtype=int
        )
        bundle = VisualizationBundle(grid, overlay)
    elif mode in {'inactive', 'tough_inactive'}:
        inactive = set(int(value) for value in (inactive_cells or ()))
        grid.cell_data['tough_inactive'] = np.asarray(
            [int(cell_id in inactive) for cell_id in grid.cell_data['cell_id']], dtype=int
        )
        bundle = VisualizationBundle(grid, scalars='tough_inactive', categorical=True)
    elif mode == 'wireframe':
        bundle = VisualizationBundle(grid)
    else:
        raise ValueError(f'Unknown visualization mode: {display_mode}')
    if visible_materials is None:
        return bundle
    selected = {str(value) for value in visible_materials}
    visible_ids = {cell.id for cell in model.cells if cell.material in selected}
    return filter_visualization_bundle(bundle, visible_ids, mode)
