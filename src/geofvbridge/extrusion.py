"""Native extrusion of first-order 2-D meshes into 3-D control-volume meshes."""

from __future__ import annotations

import meshio
import numpy as np

from .converter import ConversionError, cell_type_dimension


def extrude_meshio(
    mesh: meshio.Mesh,
    direction=(0.0, 0.0, 1.0),
    layer_thicknesses=(1.0,),
    physical_roles: dict[str, str] | None = None,
) -> meshio.Mesh:
    """Extrude triangle/quad blocks into wedge/hexahedron blocks.

    The direction is normalized; layer_thicknesses therefore carry the length
    unit of the input coordinates. Boundary edges become side quadrilaterals,
    while the original and final surfaces are named ``BOTTOM`` and ``TOP``.
    """
    points = np.asarray(mesh.points, dtype=float)
    if points.shape[1] == 2:
        points = np.column_stack((points, np.zeros(len(points))))
    direction = np.asarray(direction, dtype=float)
    norm = float(np.linalg.norm(direction))
    if norm == 0.0:
        raise ConversionError("Extrusion direction cannot be zero.")
    direction /= norm
    layers = np.asarray(layer_thicknesses, dtype=float)
    if layers.ndim != 1 or len(layers) == 0 or np.any(layers <= 0.0):
        raise ConversionError("Every extrusion layer thickness must be positive.")

    top_blocks = [
        (index, block)
        for index, block in enumerate(mesh.cells)
        if cell_type_dimension(block.type) == 2
    ]
    unsupported = [block.type for _, block in top_blocks if block.type not in {"triangle", "quad"}]
    if unsupported:
        raise ConversionError(f"Unsupported 2-D extrusion cell types: {sorted(set(unsupported))}")
    if not top_blocks:
        raise ConversionError("The input mesh contains no triangles or quadrilaterals to extrude.")

    heights = np.concatenate(([0.0], np.cumsum(layers)))
    count = len(points)
    out_points = np.vstack([points + height * direction for height in heights])
    physical = mesh.cell_data.get("gmsh:physical", [])
    physical_roles = physical_roles or {}
    name_by_key = {}
    for name, raw in mesh.field_data.items():
        values = np.asarray(raw, dtype=int).ravel()
        if values.size >= 2:
            name_by_key[(int(values[1]), int(values[0]))] = str(name)
    boundary_edge_tags: dict[tuple[int, int], int] = {}
    retained_blocks: list[tuple[str, np.ndarray, np.ndarray]] = []
    for block_index, block in enumerate(mesh.cells):
        dimension = cell_type_dimension(block.type)
        if dimension not in {0, 1}:
            continue
        tags = (
            np.asarray(physical[block_index], dtype=int)
            if block_index < len(physical)
            else np.full(len(block.data), -1, dtype=int)
        )
        kept_rows, kept_tags = [], []
        for row_index, raw in enumerate(np.asarray(block.data, dtype=int)):
            tag = int(tags[row_index])
            name = name_by_key.get((dimension, tag))
            default_role = "source" if dimension == 0 else "boundary"
            role = physical_roles.get(name or "", default_role)
            if dimension == 1 and block.type == "line" and role == "boundary":
                boundary_edge_tags[tuple(sorted(int(value) for value in raw))] = tag
            elif role == "source":
                kept_rows.append([int(value) for value in raw])
                kept_tags.append(tag)
        if kept_rows:
            retained_blocks.append(
                (block.type, np.asarray(kept_rows, dtype=int), np.asarray(kept_tags, dtype=int))
            )
    volume_blocks: dict[str, list[list[int]]] = {"wedge": [], "hexahedron": []}
    volume_tags: dict[str, list[int]] = {"wedge": [], "hexahedron": []}
    bottom_blocks: dict[str, list[list[int]]] = {"triangle": [], "quad": []}
    top_surface_blocks: dict[str, list[list[int]]] = {"triangle": [], "quad": []}
    edge_occurrences: dict[tuple[int, int], tuple[int, int]] = {}
    edge_count: dict[tuple[int, int], int] = {}
    local_edges = {
        "triangle": ((0, 1), (1, 2), (2, 0)),
        "quad": ((0, 1), (1, 2), (2, 3), (3, 0)),
    }
    for block_index, block in top_blocks:
        tags = (
            np.asarray(physical[block_index], dtype=int)
            if block_index < len(physical)
            else np.full(len(block.data), -1, dtype=int)
        )
        for row_index, raw in enumerate(np.asarray(block.data, dtype=int)):
            row = [int(v) for v in raw]
            for edge in local_edges[block.type]:
                pair = tuple(sorted((row[edge[0]], row[edge[1]])))
                edge_count[pair] = edge_count.get(pair, 0) + 1
                edge_occurrences[pair] = (row[edge[0]], row[edge[1]])
            bottom_blocks[block.type].append(row)
            top_surface_blocks[block.type].append([value + len(layers) * count for value in row])
            for layer in range(len(layers)):
                lower = [value + layer * count for value in row]
                upper = [value + (layer + 1) * count for value in row]
                volume_type = "wedge" if block.type == "triangle" else "hexahedron"
                volume_blocks[volume_type].append(lower + upper)
                volume_tags[volume_type].append(int(tags[row_index]))

    existing_tags = [int(values[0]) for values in mesh.field_data.values() if len(values) >= 2]
    next_tag = max(existing_tags, default=0) + 1
    bottom_tag, top_tag, side_tag = next_tag, next_tag + 1, next_tag + 2
    side_faces: list[list[int]] = []
    side_tags: list[int] = []
    for pair, occurrences in edge_count.items():
        if occurrences != 1:
            continue
        a, b = edge_occurrences[pair]
        for layer in range(len(layers)):
            side_faces.append(
                [a + layer * count, b + layer * count, b + (layer + 1) * count, a + (layer + 1) * count]
            )
            side_tags.append(boundary_edge_tags.get(pair, side_tag))

    cells = []
    cell_tags = []
    for cell_type, data, tags in retained_blocks:
        cells.append((cell_type, data))
        cell_tags.append(tags)
    for cell_type in ("wedge", "hexahedron"):
        if volume_blocks[cell_type]:
            cells.append((cell_type, np.asarray(volume_blocks[cell_type], dtype=int)))
            cell_tags.append(np.asarray(volume_tags[cell_type], dtype=int))
    for cell_type in ("triangle", "quad"):
        if bottom_blocks[cell_type]:
            cells.append((cell_type, np.asarray(bottom_blocks[cell_type], dtype=int)))
            cell_tags.append(np.full(len(bottom_blocks[cell_type]), bottom_tag, dtype=int))
        if top_surface_blocks[cell_type]:
            cells.append((cell_type, np.asarray(top_surface_blocks[cell_type], dtype=int)))
            cell_tags.append(np.full(len(top_surface_blocks[cell_type]), top_tag, dtype=int))
    if side_faces:
        cells.append(("quad", np.asarray(side_faces, dtype=int)))
        cell_tags.append(np.asarray(side_tags, dtype=int))

    field_data = {}
    for name, raw in mesh.field_data.items():
        values = np.asarray(raw, dtype=int).ravel()
        if values.size < 2:
            continue
        dimension, tag = int(values[1]), int(values[0])
        role = physical_roles.get(name, "source" if dimension == 0 else "boundary" if dimension == 1 else "material")
        if dimension == 2:
            field_data[name] = np.asarray([tag, 3], dtype=int)
        elif dimension == 1 and role == "boundary":
            field_data[name] = np.asarray([tag, 2], dtype=int)
        elif dimension in {0, 1} and role == "source":
            field_data[name] = np.asarray([tag, dimension], dtype=int)
    field_data.update(
        {
            "BOTTOM": np.asarray([bottom_tag, 2], dtype=int),
            "TOP": np.asarray([top_tag, 2], dtype=int),
            "SIDE": np.asarray([side_tag, 2], dtype=int),
        }
    )
    return meshio.Mesh(
        out_points,
        cells,
        cell_data={"gmsh:physical": cell_tags},
        field_data=field_data,
    )
