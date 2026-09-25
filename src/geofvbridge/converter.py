"""Gmsh/meshio to solver-independent finite-volume conversion."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

import meshio
import numpy as np

from .elements import CELL_DIMENSION, EXPECTED_NODES, LOCAL_FACES, canonical_cycle
from .geometry import GeometryError, cell_geometry, face_geometry
from .model import (
    Boundary,
    Cell,
    Connection,
    ConversionOptions,
    ExtrusionOptions,
    Face,
    FVModel,
    Source,
)
from .validation import validate_model


class ConversionError(ValueError):
    pass


def cell_type_dimension(cell_type: str) -> int | None:
    prefixes = (
        ("vertex", 0),
        ("line", 1),
        ("triangle", 2),
        ("quad", 2),
        ("tetra", 3),
        ("wedge", 3),
        ("hexahedron", 3),
        ("pyramid", 3),
        ("voxel", 3),
    )
    for prefix, dimension in prefixes:
        if cell_type.startswith(prefix):
            return dimension
    return None


def _physical_maps(mesh: meshio.Mesh):
    name_by_key: dict[tuple[int, int], str] = {}
    for name, raw in mesh.field_data.items():
        values = np.asarray(raw, dtype=int).ravel()
        if values.size >= 2:
            name_by_key[(int(values[1]), int(values[0]))] = str(name)
    physical_by_block = mesh.cell_data.get("gmsh:physical", [])
    return name_by_key, physical_by_block


def _block_tags(physical_by_block: list, block_index: int, count: int):
    if block_index < len(physical_by_block):
        values = np.asarray(physical_by_block[block_index], dtype=int).ravel()
        if values.size == count:
            return values
    return np.full(count, -1, dtype=int)


def _as_points3(points) -> np.ndarray:
    array = np.asarray(points, dtype=float)
    if array.ndim != 2 or array.shape[1] not in {2, 3}:
        raise ConversionError("Mesh points must be an N x 2 or N x 3 array.")
    if array.shape[1] == 2:
        array = np.column_stack((array, np.zeros(len(array), dtype=float)))
    if not np.all(np.isfinite(array)):
        raise ConversionError("Mesh contains non-finite point coordinates.")
    return array


def _lower_entities(
    mesh: meshio.Mesh,
    dimension: int,
    name_by_key: dict[tuple[int, int], str],
    physical_by_block: list,
):
    for block_index, block in enumerate(mesh.cells):
        block_dimension = cell_type_dimension(block.type)
        if block_dimension != dimension:
            continue
        tags = _block_tags(physical_by_block, block_index, len(block.data))
        for entity_index, row in enumerate(np.asarray(block.data, dtype=int)):
            tag = int(tags[entity_index])
            yield tuple(int(value) for value in row), name_by_key.get((dimension, tag)), tag


def convert_meshio(
    mesh: meshio.Mesh,
    *,
    source_path: str | Path | None = None,
    options: ConversionOptions | None = None,
) -> FVModel:
    options = options or ConversionOptions()
    points = _as_points3(mesh.points)
    dimensions = [cell_type_dimension(block.type) for block in mesh.cells]
    dimensions = [dimension for dimension in dimensions if dimension is not None]
    if not dimensions:
        raise ConversionError("No recognizable cells were found in the mesh.")
    top_dimension = max(dimensions)
    if top_dimension not in {2, 3}:
        raise ConversionError("GeoFVBridge requires a 2-D or 3-D top-dimensional mesh.")

    supported_types = {"vertex", "line", "triangle", "quad", *CELL_DIMENSION}
    unsupported_recognized = sorted(
        {
            block.type
            for block in mesh.cells
            if cell_type_dimension(block.type) is not None and block.type not in supported_types
        }
    )
    if unsupported_recognized:
        names = ", ".join(unsupported_recognized)
        raise ConversionError(
            f"Unsupported first/high-order cell representations: {names}. "
            "GeoFVBridge does not silently discard or linearize recognized Gmsh cells."
        )
    top_blocks = [block for block in mesh.cells if cell_type_dimension(block.type) == top_dimension]
    unsupported = sorted({block.type for block in top_blocks if block.type not in CELL_DIMENSION})
    if unsupported:
        names = ", ".join(unsupported)
        raise ConversionError(
            f"Unsupported top-dimensional cell types: {names}. "
            "Only first-order standard cells are accepted; high-order cells are not linearized."
        )

    name_by_key, physical_by_block = _physical_maps(mesh)
    model = FVModel(
        points=points,
        cells=[],
        faces=[],
        connections=[],
        boundaries=[],
        sources=[],
        dimension=top_dimension,
        options=options,
        metadata={
            "source_path": str(Path(source_path).resolve()) if source_path else None,
            "source_format": Path(source_path).suffix.lower().lstrip(".") if source_path else "meshio",
            "cell_types": sorted({block.type for block in top_blocks}),
        },
    )

    cell_normals: dict[int, np.ndarray | None] = {}
    source_id = 0
    for block_index, block in enumerate(mesh.cells):
        if cell_type_dimension(block.type) != top_dimension:
            continue
        tags = _block_tags(physical_by_block, block_index, len(block.data))
        for local_index, row in enumerate(np.asarray(block.data, dtype=int)):
            nodes = tuple(int(value) for value in row)
            if len(nodes) != EXPECTED_NODES[block.type]:
                raise ConversionError(
                    f"Cell type {block.type!r} has {len(nodes)} nodes; "
                    f"expected {EXPECTED_NODES[block.type]}."
                )
            normalized_type = block.type
            if block.type == "voxel":
                nodes = tuple(nodes[index] for index in (0, 1, 3, 2, 4, 5, 7, 6))
                normalized_type = "hexahedron"
            if len(set(nodes)) != len(nodes):
                model.report.add(
                    "error", "duplicate_cell_node", "Cell contains repeated node IDs.", "cell", source_id
                )
                source_id += 1
                continue
            try:
                measure, centroid, normal = cell_geometry(
                    points, normalized_type, nodes, options.tolerance
                )
            except GeometryError as error:
                model.report.add("error", "degenerate_cell", str(error), "cell", source_id)
                source_id += 1
                continue
            tag = int(tags[local_index])
            physical_name = name_by_key.get((top_dimension, tag))
            role = options.physical_roles.get(physical_name or "", "material")
            material = physical_name if physical_name and role == "material" else "DEFAULT"
            cell_id = len(model.cells)
            model.cells.append(
                Cell(
                    id=cell_id,
                    cell_type=normalized_type,
                    nodes=nodes,
                    dimension=top_dimension,
                    measure=measure,
                    centroid=np.asarray(centroid, dtype=float),
                    material=material,
                    physical_tag=tag if tag >= 0 else None,
                    source_id=source_id,
                )
            )
            cell_normals[cell_id] = normal
            source_id += 1

    if not model.cells:
        raise ConversionError("No valid top-dimensional cells remain after geometry checks.")

    boundary_names: dict[tuple[int, ...], str] = {}
    for nodes, name, _tag in _lower_entities(
        mesh, top_dimension - 1, name_by_key, physical_by_block
    ):
        if name and options.physical_roles.get(name, "boundary") == "boundary":
            key = tuple(sorted(nodes))
            previous = boundary_names.get(key)
            if previous is not None and previous != name:
                model.report.add(
                    "error",
                    "conflicting_boundary_groups",
                    f"Boundary face belongs to both {previous!r} and {name!r}.",
                )
            boundary_names[key] = name

    face_by_key: dict[tuple[int, ...], int] = {}
    nonmanifold: set[int] = set()
    nonplanar_count = 0
    nonplanar_max = 0.0
    nonplanar_threshold_max = 0.0
    nonplanar_samples: list[int] = []
    for cell in model.cells:
        for local_face in LOCAL_FACES[cell.cell_type]:
            local_nodes = tuple(cell.nodes[index] for index in local_face)
            ordered_nodes = canonical_cycle(local_nodes)
            key = tuple(sorted(ordered_nodes))
            if key not in face_by_key:
                try:
                    measure, centroid, normal, planarity = face_geometry(
                        points,
                        ordered_nodes,
                        top_dimension,
                        cell.centroid,
                        cell_normals[cell.id],
                        options.tolerance,
                    )
                except GeometryError as error:
                    model.report.add("error", "degenerate_face", str(error), "cell", cell.id)
                    continue
                face_id = len(model.faces)
                face_by_key[key] = face_id
                model.faces.append(
                    Face(
                        id=face_id,
                        nodes=ordered_nodes,
                        owner=cell.id,
                        neighbour=None,
                        measure=measure,
                        centroid=np.asarray(centroid, dtype=float),
                        normal=np.asarray(normal, dtype=float),
                        planarity=planarity,
                        physical_group=boundary_names.get(key),
                    )
                )
                scale = max(float(np.sqrt(measure)), options.tolerance)
                threshold = max(100.0 * options.tolerance, 1.0e-8 * scale)
                if planarity > threshold:
                    nonplanar_count += 1
                    nonplanar_max = max(nonplanar_max, float(planarity))
                    nonplanar_threshold_max = max(nonplanar_threshold_max, float(threshold))
                    if len(nonplanar_samples) < 20:
                        nonplanar_samples.append(face_id)
            else:
                face = model.faces[face_by_key[key]]
                if face.neighbour is None:
                    face.neighbour = cell.id
                    face.physical_group = None
                else:
                    nonmanifold.add(face.id)
                    model.report.add(
                        "error",
                        "nonmanifold_face",
                        "A face is shared by more than two top-dimensional cells.",
                        "face",
                        face.id,
                    )

    nonplanar_diagnostic = {
        "count": nonplanar_count,
        "fraction": nonplanar_count / len(model.faces) if model.faces else 0.0,
        "maximum": nonplanar_max,
        "maximum_threshold": nonplanar_threshold_max,
        "sample_face_ids": nonplanar_samples,
        "threshold_rule": "max(100*tolerance, 1e-8*sqrt(face_measure))",
    }
    model.metadata.setdefault("diagnostics", {})["nonplanar_faces"] = nonplanar_diagnostic
    if nonplanar_count:
        model.report.add(
            "warning",
            "nonplanar_face",
            (
                f"{nonplanar_count} face(s) are non-planar; representative planes are used "
                f"(maximum deviation {nonplanar_max:.6g})."
            ),
        )

    gravity = np.asarray(options.gravity, dtype=float)
    gravity_norm = float(np.linalg.norm(gravity))
    gravity_unit = gravity / gravity_norm if gravity_norm > options.tolerance else np.zeros(3)
    for face in model.faces:
        if face.id in nonmanifold:
            continue
        owner = model.cells[face.owner]
        if face.neighbour is None:
            name = face.physical_group or "UNASSIGNED"
            model.boundaries.append(
                Boundary(id=len(model.boundaries), face=face.id, cell=owner.id, name=name)
            )
            continue
        neighbour = model.cells[face.neighbour]
        delta = neighbour.centroid - owner.centroid
        distance = float(np.linalg.norm(delta))
        if distance <= options.tolerance:
            model.report.add(
                "error", "coincident_centroids", "Adjacent cells have coincident centroids.", "face", face.id
            )
            continue
        if float(np.dot(face.normal, delta)) < 0.0:
            face.normal = -face.normal
        direction = delta / distance
        denominator = float(np.dot(delta, face.normal))
        if abs(denominator) <= options.tolerance:
            model.report.add(
                "error",
                "centroid_line_parallel_to_face",
                "The adjacent-centroid line is parallel to the shared-face plane.",
                "face",
                face.id,
            )
            continue
        parameter = float(np.dot(face.centroid - owner.centroid, face.normal)) / denominator
        intersection = owner.centroid + parameter * delta
        d1 = float(np.linalg.norm(intersection - owner.centroid))
        d2 = float(np.linalg.norm(neighbour.centroid - intersection))
        normal_d1 = abs(float(np.dot(face.centroid - owner.centroid, face.normal)))
        normal_d2 = abs(float(np.dot(neighbour.centroid - face.centroid, face.normal)))
        if parameter <= 0.0 or parameter >= 1.0:
            model.report.add(
                "error",
                "interface_not_between_centroids",
                "The shared-face plane does not lie between the adjacent cell centroids.",
                "face",
                face.id,
            )
        model.connections.append(
            Connection(
                id=len(model.connections),
                cell1=owner.id,
                cell2=neighbour.id,
                face=face.id,
                interface_measure=face.measure,
                d1=d1,
                d2=d2,
                intersection=np.asarray(intersection, dtype=float),
                normal_d1=normal_d1,
                normal_d2=normal_d2,
                center_distance=distance,
                normal=face.normal.copy(),
                gravity_projection=float(np.dot(direction, gravity_unit)),
                gravity_delta=float(np.dot(delta, gravity_unit)),
                orthogonality=abs(float(np.dot(direction, face.normal))),
            )
        )

    seen_sources: set[tuple[str, tuple[int, ...]]] = set()
    cell_centroids = np.vstack([cell.centroid for cell in model.cells])
    for source_dimension in range(top_dimension):
        for nodes, name, _tag in _lower_entities(
            mesh, source_dimension, name_by_key, physical_by_block
        ):
            default_role = "boundary" if source_dimension == top_dimension - 1 else "source"
            if not name or options.physical_roles.get(name, default_role) != "source":
                continue
            key = (name, tuple(sorted(nodes)))
            if key in seen_sources:
                continue
            seen_sources.add(key)
            location = points[np.asarray(nodes, dtype=int)].mean(axis=0)
            distances = np.linalg.norm(cell_centroids - location, axis=1)
            cell_id = int(np.argmin(distances))
            model.sources.append(
                Source(
                    id=len(model.sources),
                    name=name,
                    location=location,
                    cell=cell_id,
                    distance=float(distances[cell_id]),
                )
            )

    validate_model(model, report=model.report)
    return model


def convert_file(
    path: str | Path,
    options: ConversionOptions | None = None,
    extrusion: ExtrusionOptions | None = None,
) -> FVModel:
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(path)
    mesh = meshio.read(path)
    dimensions = [cell_type_dimension(block.type) for block in mesh.cells]
    top_dimension = max((value for value in dimensions if value is not None), default=None)
    if top_dimension == 2 and extrusion is not None:
        from .extrusion import extrude_meshio

        mesh = extrude_meshio(
            mesh,
            direction=extrusion.direction,
            layer_thicknesses=extrusion.layer_thicknesses,
            physical_roles=options.physical_roles if options is not None else None,
        )
    model = convert_meshio(mesh, source_path=path, options=options)
    if top_dimension == 2 and extrusion is not None:
        model.metadata["extrusion"] = {
            "direction": list(extrusion.direction),
            "layer_thicknesses": list(extrusion.layer_thicknesses),
        }
    return model


def locate_sources(
    model: FVModel, sources: Iterable[tuple[str, Iterable[float]]]
) -> list[Source]:
    """Add coordinate-defined sources using the declared nearest-centroid rule."""
    centroids = np.vstack([cell.centroid for cell in model.cells])
    added: list[Source] = []
    for name, coordinates in sources:
        location = np.asarray(tuple(coordinates), dtype=float)
        if location.size == 2:
            location = np.append(location, 0.0)
        if location.shape != (3,) or not np.all(np.isfinite(location)):
            raise ConversionError(f"Invalid source coordinates for {name!r}.")
        distances = np.linalg.norm(centroids - location, axis=1)
        cell_id = int(np.argmin(distances))
        source = Source(
            id=len(model.sources),
            name=name,
            location=location,
            cell=cell_id,
            distance=float(distances[cell_id]),
        )
        model.sources.append(source)
        added.append(source)
    return added
