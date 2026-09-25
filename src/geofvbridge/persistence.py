"""Versioned HDF5 persistence and compact JSON summaries."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import h5py
import numpy as np

from .model import (
    Boundary,
    Cell,
    CellField,
    Connection,
    ConversionOptions,
    Face,
    FVModel,
    Source,
    SourceConnection,
    ValidationIssue,
    ValidationReport,
)

SCHEMA_VERSION = "1.2"
READABLE_SCHEMA_VERSIONS = {"1.0", "1.1", SCHEMA_VERSION}


def _ragged(rows):
    offsets = [0]
    flat: list[int] = []
    for row in rows:
        flat.extend(row)
        offsets.append(len(flat))
    return np.asarray(flat, dtype=np.int64), np.asarray(offsets, dtype=np.int64)


def _strings(values):
    return np.asarray(list(values), dtype=h5py.string_dtype("utf-8"))


def _decode(value):
    return value.decode("utf-8") if isinstance(value, bytes) else str(value)


def write_model(model: FVModel, path: str | Path, summary_path: str | Path | None = None) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with h5py.File(temporary, "w") as handle:
        handle.attrs["schema_version"] = SCHEMA_VERSION
        handle.attrs["dimension"] = model.dimension
        handle.attrs["options_json"] = json.dumps(asdict(model.options), ensure_ascii=False)
        handle.attrs["metadata_json"] = json.dumps(model.metadata, ensure_ascii=False, default=str)
        handle.attrs["report_json"] = json.dumps(model.report.as_dict(), ensure_ascii=False)
        handle.create_dataset("nodes/coordinates", data=model.points)

        flat, offsets = _ragged(cell.nodes for cell in model.cells)
        cells = handle.require_group("cells")
        cells.create_dataset("id", data=[cell.id for cell in model.cells])
        cells.create_dataset("type", data=_strings(cell.cell_type for cell in model.cells))
        cells.create_dataset("connectivity", data=flat)
        cells.create_dataset("offsets", data=offsets)
        cells.create_dataset("measure", data=[cell.measure for cell in model.cells])
        cells.create_dataset("centroid", data=[cell.centroid for cell in model.cells])
        cells.create_dataset("material", data=_strings(cell.material for cell in model.cells))
        cells.create_dataset(
            "physical_tag", data=[cell.physical_tag if cell.physical_tag is not None else -1 for cell in model.cells]
        )
        cells.create_dataset(
            "source_id", data=[cell.source_id if cell.source_id is not None else -1 for cell in model.cells]
        )
        cells.create_dataset(
            "source_kind", data=_strings(cell.source_kind or "" for cell in model.cells)
        )
        cells.create_dataset(
            "source_global_index",
            data=[
                cell.source_global_index if cell.source_global_index is not None else -1
                for cell in model.cells
            ],
        )
        cells.create_dataset(
            "active_index",
            data=[cell.active_index if cell.active_index is not None else -1 for cell in model.cells],
        )
        cells.create_dataset(
            "ijk",
            data=[
                cell.ijk if cell.ijk is not None else (-1, -1, -1)
                for cell in model.cells
            ],
        )
        member_values, member_offsets = _ragged(cell.source_members for cell in model.cells)
        cells.create_dataset("source_members", data=member_values)
        cells.create_dataset("source_member_offsets", data=member_offsets)

        cell_fields = handle.require_group("cell_fields")
        for name, item in sorted(model.cell_fields.items()):
            if len(item.values) != len(model.cells):
                raise ValueError(
                    f"Cell field {name!r} has {len(item.values)} values for {len(model.cells)} cells."
                )
            field_group = cell_fields.require_group(name)
            field_group.create_dataset("values", data=np.asarray(item.values))
            field_group.attrs["unit"] = item.unit
            field_group.attrs["source"] = item.source
            field_group.attrs["keyword"] = item.keyword
            field_group.attrs["aggregation"] = item.aggregation
            field_group.attrs["role"] = item.role

        flat, offsets = _ragged(face.nodes for face in model.faces)
        faces = handle.require_group("faces")
        faces.create_dataset("id", data=[face.id for face in model.faces])
        faces.create_dataset("connectivity", data=flat)
        faces.create_dataset("offsets", data=offsets)
        faces.create_dataset("owner", data=[face.owner for face in model.faces])
        faces.create_dataset(
            "neighbour", data=[face.neighbour if face.neighbour is not None else -1 for face in model.faces]
        )
        faces.create_dataset("measure", data=[face.measure for face in model.faces])
        faces.create_dataset("centroid", data=[face.centroid for face in model.faces])
        faces.create_dataset("normal", data=[face.normal for face in model.faces])
        faces.create_dataset("planarity", data=[face.planarity for face in model.faces])
        faces.create_dataset(
            "physical_group", data=_strings(face.physical_group or "" for face in model.faces)
        )

        connections = handle.require_group("connections")
        for name in ("id", "cell1", "cell2", "face"):
            connections.create_dataset(name, data=[getattr(item, name) for item in model.connections])
        for name in (
            "interface_measure",
            "d1",
            "d2",
            "normal_d1",
            "normal_d2",
            "center_distance",
            "gravity_projection",
            "gravity_delta",
            "orthogonality",
        ):
            connections.create_dataset(name, data=[getattr(item, name) for item in model.connections])
        connections.create_dataset(
            "normal",
            data=np.asarray([item.normal for item in model.connections], dtype=float).reshape((-1, 3)),
        )
        connections.create_dataset(
            "intersection",
            data=np.asarray([item.intersection for item in model.connections], dtype=float).reshape((-1, 3)),
        )
        connections.create_dataset(
            "enabled", data=np.asarray([item.enabled for item in model.connections], dtype=np.uint8)
        )
        connections.create_dataset(
            "source_connection_id",
            data=[
                item.source_connection_id if item.source_connection_id is not None else -1
                for item in model.connections
            ],
        )

        source_connections = handle.require_group("source_connections")
        for name in ("id", "cell1", "cell2", "source_count"):
            source_connections.create_dataset(
                name, data=[getattr(item, name) for item in model.source_connections]
            )
        source_connections.create_dataset(
            "kind", data=_strings(item.kind for item in model.source_connections)
        )
        source_connections.create_dataset(
            "direction", data=_strings(item.direction or "" for item in model.source_connections)
        )
        source_connections.create_dataset(
            "transmissibility",
            data=[item.transmissibility for item in model.source_connections],
        )
        source_connections.create_dataset(
            "flow_connected",
            data=np.asarray(
                [item.flow_connected for item in model.source_connections], dtype=np.uint8
            ),
        )
        source_connections.create_dataset(
            "matched_connection",
            data=[
                item.matched_connection if item.matched_connection is not None else -1
                for item in model.source_connections
            ],
        )
        source_connections.create_dataset(
            "geometry_status",
            data=_strings(item.geometry_status for item in model.source_connections),
        )
        source_connections.create_dataset(
            "metadata_json",
            data=_strings(
                json.dumps(item.metadata, ensure_ascii=False, default=str)
                for item in model.source_connections
            ),
        )

        boundaries = handle.require_group("boundaries")
        for name in ("id", "face", "cell"):
            boundaries.create_dataset(name, data=[getattr(item, name) for item in model.boundaries])
        boundaries.create_dataset("name", data=_strings(item.name for item in model.boundaries))
        boundaries.create_dataset("kind", data=_strings(item.kind for item in model.boundaries))
        boundaries.create_dataset(
            "value", data=[item.value if item.value is not None else np.nan for item in model.boundaries]
        )

        sources = handle.require_group("sources")
        sources.create_dataset("id", data=[item.id for item in model.sources])
        sources.create_dataset("name", data=_strings(item.name for item in model.sources))
        sources.create_dataset(
            "location", data=np.asarray([item.location for item in model.sources], dtype=float).reshape((-1, 3))
        )
        sources.create_dataset("cell", data=[item.cell for item in model.sources])
        sources.create_dataset("distance", data=[item.distance for item in model.sources])
        sources.create_dataset("kind", data=_strings(item.kind for item in model.sources))
        sources.create_dataset(
            "rate", data=[item.rate if item.rate is not None else np.nan for item in model.sources]
        )
    temporary.replace(path)
    if summary_path is None:
        summary_path = path.with_suffix(".summary.json")
    Path(summary_path).write_text(
        json.dumps(model.summary(), indent=2, ensure_ascii=False, default=str), encoding="utf-8"
    )
    return path


def read_model(path: str | Path) -> FVModel:
    with h5py.File(path, "r") as handle:
        schema_version = _decode(handle.attrs.get("schema_version", ""))
        if schema_version not in READABLE_SCHEMA_VERSIONS:
            raise ValueError("Unsupported GeoFVBridge HDF5 schema version.")
        dimension = int(handle.attrs["dimension"])
        options = ConversionOptions(**json.loads(_decode(handle.attrs["options_json"])))
        metadata = json.loads(_decode(handle.attrs["metadata_json"]))
        report_data = json.loads(_decode(handle.attrs["report_json"]))
        points = np.asarray(handle["nodes/coordinates"], dtype=float)

        cells_group = handle["cells"]
        connectivity = np.asarray(cells_group["connectivity"], dtype=int)
        offsets = np.asarray(cells_group["offsets"], dtype=int)
        cell_ids = np.asarray(cells_group["id"], dtype=int)
        cell_types = [_decode(value) for value in cells_group["type"][...]]
        cell_measures = np.asarray(cells_group["measure"], dtype=float)
        cell_centroids = np.asarray(cells_group["centroid"], dtype=float)
        cell_materials = [_decode(value) for value in cells_group["material"][...]]
        physical_tags = np.asarray(cells_group["physical_tag"], dtype=int)
        source_ids = np.asarray(cells_group["source_id"], dtype=int)
        source_kinds = (
            [_decode(value) for value in cells_group["source_kind"][...]]
            if "source_kind" in cells_group
            else [""] * len(cell_ids)
        )
        source_global_indices = (
            np.asarray(cells_group["source_global_index"], dtype=int)
            if "source_global_index" in cells_group
            else np.full(len(cell_ids), -1, dtype=int)
        )
        active_indices = (
            np.asarray(cells_group["active_index"], dtype=int)
            if "active_index" in cells_group
            else np.full(len(cell_ids), -1, dtype=int)
        )
        ijk_values = (
            np.asarray(cells_group["ijk"], dtype=int)
            if "ijk" in cells_group
            else np.full((len(cell_ids), 3), -1, dtype=int)
        )
        source_member_values = (
            np.asarray(cells_group["source_members"], dtype=int)
            if "source_members" in cells_group
            else np.empty(0, dtype=int)
        )
        source_member_offsets = (
            np.asarray(cells_group["source_member_offsets"], dtype=int)
            if "source_member_offsets" in cells_group
            else np.zeros(len(cell_ids) + 1, dtype=int)
        )
        cells = []
        for index, cell_id in enumerate(cell_ids):
            tag = int(physical_tags[index])
            source_id = int(source_ids[index])
            source_global_index = int(source_global_indices[index])
            active_index = int(active_indices[index])
            raw_ijk = tuple(int(value) for value in ijk_values[index])
            cells.append(
                Cell(
                    id=int(cell_id),
                    cell_type=cell_types[index],
                    nodes=tuple(int(v) for v in connectivity[offsets[index] : offsets[index + 1]]),
                    dimension=dimension,
                    measure=float(cell_measures[index]),
                    centroid=cell_centroids[index].copy(),
                    material=cell_materials[index],
                    physical_tag=None if tag < 0 else tag,
                    source_id=None if source_id < 0 else source_id,
                    source_kind=source_kinds[index] or None,
                    source_global_index=(
                        None if source_global_index < 0 else source_global_index
                    ),
                    active_index=None if active_index < 0 else active_index,
                    ijk=None if any(value < 0 for value in raw_ijk) else raw_ijk,
                    source_members=tuple(
                        int(value)
                        for value in source_member_values[
                            source_member_offsets[index] : source_member_offsets[index + 1]
                        ]
                    ),
                )
            )

        cell_fields: dict[str, CellField] = {}
        if "cell_fields" in handle:
            for name, field_group in handle["cell_fields"].items():
                cell_fields[name] = CellField(
                    values=np.asarray(field_group["values"]),
                    unit=_decode(field_group.attrs.get("unit", "")),
                    source=_decode(field_group.attrs.get("source", "")),
                    keyword=_decode(field_group.attrs.get("keyword", "")),
                    aggregation=_decode(field_group.attrs.get("aggregation", "none")),
                    role=_decode(field_group.attrs.get("role", "property")),
                )

        faces_group = handle["faces"]
        connectivity = np.asarray(faces_group["connectivity"], dtype=int)
        offsets = np.asarray(faces_group["offsets"], dtype=int)
        face_ids = np.asarray(faces_group["id"], dtype=int)
        face_owners = np.asarray(faces_group["owner"], dtype=int)
        face_neighbours = np.asarray(faces_group["neighbour"], dtype=int)
        face_measures = np.asarray(faces_group["measure"], dtype=float)
        face_centroids = np.asarray(faces_group["centroid"], dtype=float)
        face_normals = np.asarray(faces_group["normal"], dtype=float)
        face_planarity = (
            np.asarray(faces_group["planarity"], dtype=float)
            if "planarity" in faces_group
            else np.zeros(len(face_ids), dtype=float)
        )
        face_groups = [_decode(value) for value in faces_group["physical_group"][...]]
        faces = []
        for index, face_id in enumerate(face_ids):
            neighbour = int(face_neighbours[index])
            physical_group = face_groups[index]
            faces.append(
                Face(
                    id=int(face_id),
                    nodes=tuple(int(v) for v in connectivity[offsets[index] : offsets[index + 1]]),
                    owner=int(face_owners[index]),
                    neighbour=None if neighbour < 0 else neighbour,
                    measure=float(face_measures[index]),
                    centroid=face_centroids[index].copy(),
                    normal=face_normals[index].copy(),
                    planarity=float(face_planarity[index]),
                    physical_group=physical_group or None,
                )
            )

        group = handle["connections"]
        connection_ids = np.asarray(group["id"], dtype=int)
        connection_cell1 = np.asarray(group["cell1"], dtype=int)
        connection_cell2 = np.asarray(group["cell2"], dtype=int)
        connection_faces = np.asarray(group["face"], dtype=int)
        interface_measures = np.asarray(group["interface_measure"], dtype=float)
        stored_d1 = np.asarray(group["d1"], dtype=float)
        stored_d2 = np.asarray(group["d2"], dtype=float)
        center_distances = np.asarray(group["center_distance"], dtype=float)
        connection_normals = np.asarray(group["normal"], dtype=float)
        gravity_projections = np.asarray(group["gravity_projection"], dtype=float)
        gravity_deltas = np.asarray(group["gravity_delta"], dtype=float)
        orthogonality = np.asarray(group["orthogonality"], dtype=float)
        connection_enabled = (
            np.asarray(group["enabled"], dtype=bool)
            if "enabled" in group
            else np.ones(len(connection_ids), dtype=bool)
        )
        connection_source_ids = (
            np.asarray(group["source_connection_id"], dtype=int)
            if "source_connection_id" in group
            else np.full(len(connection_ids), -1, dtype=int)
        )
        intersections = (
            np.asarray(group["intersection"], dtype=float)
            if "intersection" in group
            else None
        )
        stored_normal_d1 = (
            np.asarray(group["normal_d1"], dtype=float)
            if "normal_d1" in group
            else None
        )
        stored_normal_d2 = (
            np.asarray(group["normal_d2"], dtype=float)
            if "normal_d2" in group
            else None
        )
        connections = []
        for i, connection_id in enumerate(connection_ids):
            cell1 = int(connection_cell1[i])
            cell2 = int(connection_cell2[i])
            face_id = int(connection_faces[i])
            if intersections is not None:
                intersection = intersections[i].copy()
                d1 = float(stored_d1[i])
                d2 = float(stored_d2[i])
            else:
                face = faces[face_id]
                delta = cells[cell2].centroid - cells[cell1].centroid
                denominator = float(np.dot(delta, face.normal))
                if abs(denominator) <= options.tolerance:
                    raise ValueError("Schema 1.0 connection cannot be migrated: parallel geometry.")
                parameter = float(
                    np.dot(face.centroid - cells[cell1].centroid, face.normal) / denominator
                )
                intersection = cells[cell1].centroid + parameter * delta
                d1 = float(np.linalg.norm(intersection - cells[cell1].centroid))
                d2 = float(np.linalg.norm(cells[cell2].centroid - intersection))
            normal_d1 = (
                float(stored_normal_d1[i])
                if stored_normal_d1 is not None
                else abs(float(np.dot(faces[face_id].centroid - cells[cell1].centroid, faces[face_id].normal)))
            )
            normal_d2 = (
                float(stored_normal_d2[i])
                if stored_normal_d2 is not None
                else abs(float(np.dot(cells[cell2].centroid - faces[face_id].centroid, faces[face_id].normal)))
            )
            connections.append(
                Connection(
                    id=int(connection_id),
                    cell1=cell1,
                    cell2=cell2,
                    face=face_id,
                    interface_measure=float(interface_measures[i]),
                    d1=d1,
                    d2=d2,
                    intersection=intersection,
                    normal_d1=normal_d1,
                    normal_d2=normal_d2,
                    center_distance=float(center_distances[i]),
                    normal=connection_normals[i].copy(),
                    gravity_projection=float(gravity_projections[i]),
                    gravity_delta=float(gravity_deltas[i]),
                    orthogonality=float(orthogonality[i]),
                    enabled=bool(connection_enabled[i]),
                    source_connection_id=(
                        None
                        if int(connection_source_ids[i]) < 0
                        else int(connection_source_ids[i])
                    ),
                )
            )

        source_connections: list[SourceConnection] = []
        if "source_connections" in handle:
            source_group = handle["source_connections"]
            source_connection_ids = np.asarray(source_group["id"], dtype=int)
            source_cell1 = np.asarray(source_group["cell1"], dtype=int)
            source_cell2 = np.asarray(source_group["cell2"], dtype=int)
            source_counts = np.asarray(source_group["source_count"], dtype=int)
            source_kinds_data = [_decode(value) for value in source_group["kind"][...]]
            source_directions = [_decode(value) for value in source_group["direction"][...]]
            source_transmissibilities = np.asarray(
                source_group["transmissibility"], dtype=float
            )
            source_flow = np.asarray(source_group["flow_connected"], dtype=bool)
            source_matches = np.asarray(source_group["matched_connection"], dtype=int)
            source_geometry = [
                _decode(value) for value in source_group["geometry_status"][...]
            ]
            source_metadata = [
                json.loads(_decode(value)) for value in source_group["metadata_json"][...]
            ]
            for index, connection_id in enumerate(source_connection_ids):
                matched = int(source_matches[index])
                source_connections.append(
                    SourceConnection(
                        id=int(connection_id),
                        cell1=int(source_cell1[index]),
                        cell2=int(source_cell2[index]),
                        kind=source_kinds_data[index],
                        transmissibility=float(source_transmissibilities[index]),
                        flow_connected=bool(source_flow[index]),
                        direction=source_directions[index] or None,
                        matched_connection=None if matched < 0 else matched,
                        geometry_status=source_geometry[index],
                        source_count=int(source_counts[index]),
                        metadata=source_metadata[index],
                    )
                )

        group = handle["boundaries"]
        boundary_ids = np.asarray(group["id"], dtype=int)
        boundary_faces = np.asarray(group["face"], dtype=int)
        boundary_cells = np.asarray(group["cell"], dtype=int)
        boundary_names = [_decode(value) for value in group["name"][...]]
        boundary_kinds = [_decode(value) for value in group["kind"][...]]
        boundary_values = np.asarray(group["value"], dtype=float)
        boundaries = []
        for i, boundary_id in enumerate(boundary_ids):
            value = float(boundary_values[i])
            boundaries.append(
                Boundary(
                    id=int(boundary_id),
                    face=int(boundary_faces[i]),
                    cell=int(boundary_cells[i]),
                    name=boundary_names[i],
                    kind=boundary_kinds[i],
                    value=None if np.isnan(value) else value,
                )
            )

        group = handle["sources"]
        source_record_ids = np.asarray(group["id"], dtype=int)
        source_names = [_decode(value) for value in group["name"][...]]
        source_locations = np.asarray(group["location"], dtype=float)
        source_cells = np.asarray(group["cell"], dtype=int)
        source_distances = np.asarray(group["distance"], dtype=float)
        source_kinds = [_decode(value) for value in group["kind"][...]]
        source_rates = np.asarray(group["rate"], dtype=float)
        sources = []
        for i, source_record_id in enumerate(source_record_ids):
            rate = float(source_rates[i])
            sources.append(
                Source(
                    id=int(source_record_id),
                    name=source_names[i],
                    location=source_locations[i].copy(),
                    cell=int(source_cells[i]),
                    distance=float(source_distances[i]),
                    kind=source_kinds[i],
                    rate=None if np.isnan(rate) else rate,
                )
            )
    report = ValidationReport(
        [
            ValidationIssue(
                issue["severity"],
                issue["code"],
                issue["message"],
                issue.get("entity"),
                issue.get("entity_id"),
            )
            for issue in report_data.get("issues", [])
        ]
    )
    return FVModel(
        points=points,
        cells=cells,
        faces=faces,
        connections=connections,
        boundaries=boundaries,
        sources=sources,
        dimension=dimension,
        cell_fields=cell_fields,
        source_connections=source_connections,
        options=options,
        metadata=metadata,
        report=report,
    )
