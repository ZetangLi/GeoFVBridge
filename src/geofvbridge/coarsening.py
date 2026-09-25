"""Conservative vertical-run coarsening for imported Petrel grids."""

from __future__ import annotations

import copy
from collections import Counter, defaultdict
from typing import Callable

import meshio
import numpy as np

from .converter import convert_meshio
from .model import CellField, FVModel, SourceConnection


class CoarseningError(ValueError):
    """Raised when a model cannot be coarsened without losing its mapping."""


ProgressCallback = Callable[[str, int, int], None]
CancelCallback = Callable[[], bool]

DIRECTION_CORNERS = {
    "X": ((3, 0), (2, 1), (6, 5), (7, 4)),
    "Y": ((1, 0), (2, 3), (6, 7), (5, 4)),
    "Z": ((0, 4), (1, 5), (2, 6), (3, 7)),
}


class _UnionFind:
    def __init__(self, size: int) -> None:
        self.parent = list(range(size))
        self.rank = bytearray(size)

    def find(self, item: int) -> int:
        parent = self.parent
        root = item
        while parent[root] != root:
            root = parent[root]
        while parent[item] != item:
            next_item = parent[item]
            parent[item] = root
            item = next_item
        return root

    def union(self, left: int, right: int) -> None:
        left_root = self.find(left)
        right_root = self.find(right)
        if left_root == right_root:
            return
        if self.rank[left_root] < self.rank[right_root]:
            left_root, right_root = right_root, left_root
        self.parent[right_root] = left_root
        if self.rank[left_root] == self.rank[right_root]:
            self.rank[left_root] += 1


def _progress(
    callback: ProgressCallback | None,
    cancelled: CancelCallback | None,
    current: int,
    total: int,
) -> None:
    if cancelled is not None and cancelled():
        from .petrel import PetrelImportCancelled

        raise PetrelImportCancelled("Petrel import cancelled during vertical coarsening.")
    if callback is not None:
        callback("vertical_coarsening", current, total)


def _face_matches(
    corners: list[tuple[float, float, float]],
    left_offset: int,
    right_offset: int,
    pairs: tuple[tuple[int, int], ...],
    tolerance: float,
) -> bool:
    for left, right in pairs:
        point = corners[left_offset + left]
        other = corners[right_offset + right]
        if max(abs(point[axis] - other[axis]) for axis in range(3)) > tolerance:
            return False
    return True


def _weighted_average(values: np.ndarray, weights: np.ndarray) -> float:
    finite = np.isfinite(values) & np.isfinite(weights) & (weights >= 0.0)
    if not np.any(finite):
        return float("nan")
    denominator = float(weights[finite].sum())
    if denominator <= 0.0:
        return float(np.mean(values[finite]))
    return float(np.dot(values[finite], weights[finite]) / denominator)


def _mode(values: np.ndarray) -> float:
    finite = values[np.isfinite(values)]
    if not len(finite):
        return float("nan")
    unique, counts = np.unique(finite, return_counts=True)
    return float(unique[int(np.argmax(counts))])


def _component_count(cell_count: int, connections: list[SourceConnection]) -> tuple[int, int]:
    union = _UnionFind(cell_count)
    degree = np.zeros(cell_count, dtype=np.int64)
    for connection in connections:
        if not connection.flow_connected or connection.transmissibility <= 0.0:
            continue
        union.union(connection.cell1, connection.cell2)
        degree[connection.cell1] += 1
        degree[connection.cell2] += 1
    roots = Counter(union.find(index) for index in range(cell_count))
    return len(roots), int(np.count_nonzero(degree == 0))


def _apply_conservative_cell_geometry(
    result: FVModel,
    source: FVModel,
    groups: list[dict[str, object]],
    source_volumes: np.ndarray,
) -> tuple[float, set[int]]:
    """Use additive source volume/centroid and refresh connection distances."""

    envelope_volume = float(sum(cell.measure for cell in result.cells))
    for cell, group in zip(result.cells, groups):
        members = np.asarray(group["members"], dtype=int)
        weights = source_volumes[members]
        volume = float(weights.sum())
        if volume <= 0.0:
            raise CoarseningError("A vertical run has non-positive source volume.")
        centroids = np.vstack([source.cells[index].centroid for index in members])
        cell.measure = volume
        cell.centroid = np.average(centroids, axis=0, weights=weights)

    tolerance = result.options.tolerance
    gravity = np.asarray(result.options.gravity, dtype=float)
    gravity_norm = float(np.linalg.norm(gravity))
    gravity_unit = (
        gravity / gravity_norm if gravity_norm > tolerance else np.zeros(3)
    )
    disabled: set[int] = {
        connection.id for connection in result.connections if not connection.enabled
    }
    for connection in result.connections:
        face = result.faces[connection.face]
        owner = result.cells[connection.cell1]
        neighbour = result.cells[connection.cell2]
        delta = neighbour.centroid - owner.centroid
        distance = float(np.linalg.norm(delta))
        if distance <= tolerance:
            connection.enabled = False
            disabled.add(connection.id)
            continue
        if float(np.dot(face.normal, delta)) < 0.0:
            face.normal = -face.normal
        denominator = float(np.dot(delta, face.normal))
        if abs(denominator) <= tolerance:
            connection.enabled = False
            disabled.add(connection.id)
            continue
        parameter = (
            float(np.dot(face.centroid - owner.centroid, face.normal))
            / denominator
        )
        intersection = owner.centroid + parameter * delta
        direction = delta / distance
        connection.intersection = np.asarray(intersection, dtype=float)
        connection.d1 = float(np.linalg.norm(intersection - owner.centroid))
        connection.d2 = float(np.linalg.norm(neighbour.centroid - intersection))
        connection.normal_d1 = abs(
            float(np.dot(face.centroid - owner.centroid, face.normal))
        )
        connection.normal_d2 = abs(
            float(np.dot(neighbour.centroid - face.centroid, face.normal))
        )
        connection.center_distance = distance
        connection.normal = face.normal.copy()
        connection.gravity_projection = float(np.dot(direction, gravity_unit))
        connection.gravity_delta = float(np.dot(delta, gravity_unit))
        connection.orthogonality = abs(float(np.dot(direction, face.normal)))
        if parameter <= 0.0 or parameter >= 1.0:
            connection.enabled = False
            disabled.add(connection.id)
    return envelope_volume, disabled


def coarsen_vertical_runs(
    source: FVModel,
    *,
    progress: ProgressCallback | None = None,
    cancelled: CancelCallback | None = None,
) -> FVModel:
    """Merge every continuous active K run within each Petrel I,J column."""

    if source.dimension != 3 or not source.cells:
        raise CoarseningError("Vertical-run coarsening requires a non-empty 3-D model.")
    if any(cell.ijk is None for cell in source.cells):
        raise CoarseningError("Every source cell must have a Petrel I,J,K index.")
    if any(cell.cell_type != "hexahedron" for cell in source.cells):
        raise CoarseningError("Vertical-run coarsening currently requires hexahedral cells.")

    by_column: dict[tuple[int, int], list[int]] = defaultdict(list)
    for cell in source.cells:
        i_value, j_value, _ = cell.ijk
        by_column[(i_value, j_value)].append(cell.id)
    for members in by_column.values():
        members.sort(key=lambda cell_id: source.cells[cell_id].ijk[2])

    groups: list[dict[str, object]] = []
    old_to_group = np.full(len(source.cells), -1, dtype=np.int64)
    for (i_value, j_value), members in sorted(
        by_column.items(), key=lambda item: (item[0][1], item[0][0])
    ):
        run: list[int] = []
        previous_k: int | None = None
        for cell_id in members:
            k_value = source.cells[cell_id].ijk[2]
            if run and previous_k is not None and k_value != previous_k + 1:
                group_id = len(groups)
                groups.append({"i": i_value, "j": j_value, "members": tuple(run)})
                old_to_group[np.asarray(run, dtype=int)] = group_id
                run = []
            run.append(cell_id)
            previous_k = k_value
        if run:
            group_id = len(groups)
            groups.append({"i": i_value, "j": j_value, "members": tuple(run)})
            old_to_group[np.asarray(run, dtype=int)] = group_id
    if np.any(old_to_group < 0):
        raise CoarseningError("Not every source cell was assigned to a vertical run.")

    z_mode = (
        source.metadata.get("petrel", {})
        .get("coordinate_transform", {})
        .get("z", "negative-depth")
    )
    merged_corners: list[tuple[float, float, float]] = []
    for group in groups:
        members = group["members"]
        top_cell = source.cells[members[0]]
        bottom_cell = source.cells[members[-1]]
        top_points = source.points[np.asarray(top_cell.nodes, dtype=int)]
        bottom_points = source.points[np.asarray(bottom_cell.nodes, dtype=int)]
        if z_mode == "negative-depth":
            corners = np.vstack((bottom_points[:4], top_points[4:]))
        else:
            corners = np.vstack((top_points[:4], bottom_points[4:]))
        group["k_top"] = top_cell.ijk[2]
        group["k_bottom"] = bottom_cell.ijk[2]
        group["corners"] = corners
        merged_corners.extend(tuple(float(value) for value in point) for point in corners)

    aggregates: dict[tuple[int, int], dict[str, object]] = {}
    internal_source_count = 0
    internal_positive_trans = 0.0
    for connection in source.source_connections:
        left = int(old_to_group[connection.cell1])
        right = int(old_to_group[connection.cell2])
        if left == right:
            internal_source_count += connection.source_count
            if connection.transmissibility > 0.0:
                internal_positive_trans += connection.transmissibility
            continue
        key = tuple(sorted((left, right)))
        item = aggregates.setdefault(
            key,
            {
                "regular_trans": 0.0,
                "nnc_trans": 0.0,
                "positive_trans": 0.0,
                "source_count": 0,
                "positive_count": 0,
                "zero_count": 0,
                "nonconforming_count": 0,
                "matched_regular_count": 0,
                "directions": set(),
            },
        )
        item["source_count"] += connection.source_count
        if connection.transmissibility > 0.0:
            item["positive_trans"] += connection.transmissibility
            item["positive_count"] += connection.source_count
            if connection.kind == "nnc":
                item["nnc_trans"] += connection.transmissibility
            else:
                item["regular_trans"] += connection.transmissibility
        else:
            item["zero_count"] += connection.source_count
        if connection.kind == "regular":
            if connection.direction:
                item["directions"].add(connection.direction)
            if connection.geometry_status == "nonconforming":
                item["nonconforming_count"] += connection.source_count
            if (
                connection.matched_connection is not None
                and connection.transmissibility > 0.0
            ):
                item["matched_regular_count"] += connection.source_count

    tolerance = float(
        source.metadata.get("petrel", {})
        .get("coordinate_transform", {})
        .get("corner_tolerance", 1.0e-6)
    )
    topology = _UnionFind(len(groups) * 8)
    shared_pairs: set[tuple[int, int]] = set()
    if source.source_connections:
        for key, item in aggregates.items():
            left, right = key
            left_group = groups[left]
            right_group = groups[right]
            directions = item["directions"]
            required = len(left_group["members"])
            share = (
                len(directions) == 1
                and next(iter(directions)) in {"X", "Y"}
                and left_group["k_top"] == right_group["k_top"]
                and left_group["k_bottom"] == right_group["k_bottom"]
                and len(right_group["members"]) == required
                and item["positive_count"] == required
                and item["matched_regular_count"] == required
                and item["zero_count"] == 0
                and item["nnc_trans"] == 0.0
            )
            if not share:
                continue
            direction = next(iter(directions))
            pairs = DIRECTION_CORNERS[direction]
            if not _face_matches(merged_corners, left * 8, right * 8, pairs, tolerance):
                continue
            for left_corner, right_corner in pairs:
                topology.union(left * 8 + left_corner, right * 8 + right_corner)
            shared_pairs.add(key)
    else:
        original_geometry = {
            tuple(sorted((connection.cell1, connection.cell2)))
            for connection in source.connections
        }
        for left, left_group in enumerate(groups):
            for right in range(left + 1, len(groups)):
                right_group = groups[right]
                if (
                    left_group["k_top"] != right_group["k_top"]
                    or left_group["k_bottom"] != right_group["k_bottom"]
                ):
                    continue
                delta_i = right_group["i"] - left_group["i"]
                delta_j = right_group["j"] - left_group["j"]
                direction = "X" if (delta_i, delta_j) == (1, 0) else "Y" if (delta_i, delta_j) == (0, 1) else None
                if direction is None:
                    continue
                member_pairs = zip(left_group["members"], right_group["members"])
                if not all(tuple(sorted(pair)) in original_geometry for pair in member_pairs):
                    continue
                pairs = DIRECTION_CORNERS[direction]
                if not _face_matches(merged_corners, left * 8, right * 8, pairs, tolerance):
                    continue
                for left_corner, right_corner in pairs:
                    topology.union(left * 8 + left_corner, right * 8 + right_corner)
                shared_pairs.add((left, right))

    root_to_node: dict[int, int] = {}
    points: list[tuple[float, float, float]] = []
    corner_nodes = np.empty(len(groups) * 8, dtype=np.int64)
    maximum_merge_error = 0.0
    for corner_index, point in enumerate(merged_corners):
        root = topology.find(corner_index)
        node = root_to_node.get(root)
        if node is None:
            node = len(points)
            root_to_node[root] = node
            points.append(point)
        else:
            representative = points[node]
            maximum_merge_error = max(
                maximum_merge_error,
                *(abs(point[axis] - representative[axis]) for axis in range(3)),
            )
        corner_nodes[corner_index] = node

    _progress(progress, cancelled, 1, 3)
    mesh = meshio.Mesh(
        points=np.asarray(points, dtype=float),
        cells=[("hexahedron", corner_nodes.reshape(len(groups), 8))],
        cell_data={"gmsh:physical": [np.ones(len(groups), dtype=np.int32)]},
        field_data={"Reservoir": np.asarray([1, 3], dtype=np.int32)},
    )
    result = convert_meshio(
        mesh,
        source_path=source.source_path,
        options=source.options,
    )
    if len(result.cells) != len(groups):
        raise CoarseningError(
            f"Only {len(result.cells)} of {len(groups)} vertical runs have valid geometry."
        )

    source_volumes = np.asarray([cell.measure for cell in source.cells], dtype=float)
    from .petrel import _classify_petrel_geometry_diagnostics

    _classify_petrel_geometry_diagnostics(result)
    envelope_volume_total, conservative_disabled = _apply_conservative_cell_geometry(
        result, source, groups, source_volumes
    )
    if conservative_disabled:
        result.metadata.setdefault("diagnostics", {})[
            "disabled_coarse_connections"
        ] = {
            "count": len(conservative_disabled),
            "connection_ids": sorted(conservative_disabled),
            "sample_connection_ids": sorted(conservative_disabled)[:20],
            "handling": "disabled for solver export after conservative centroid update",
        }
        result.report.add(
            "warning",
            "disabled_coarse_connections",
            (
                f"{len(conservative_disabled)} coarse connection(s) are disabled "
                "after conservative centroid geometry was applied."
            ),
        )
    coarse_diagnostics = copy.deepcopy(result.metadata.get("diagnostics", {}))
    porv_values = (
        np.asarray(source.cell_fields["PORV"].values, dtype=float)
        if "PORV" in source.cell_fields
        else None
    )
    result.cell_fields = {}
    for name, source_field in source.cell_fields.items():
        raw = np.asarray(source_field.values, dtype=float)
        output = np.empty(len(groups), dtype=float)
        for group_id, group in enumerate(groups):
            members = np.asarray(group["members"], dtype=int)
            values = raw[members]
            if source_field.aggregation == "sum":
                output[group_id] = float(np.nansum(values))
            elif source_field.aggregation == "mode":
                output[group_id] = _mode(values)
            else:
                weights = (
                    porv_values[members]
                    if source_field.role == "initial_state" and porv_values is not None
                    else source_volumes[members]
                )
                output[group_id] = _weighted_average(values, weights)
        result.cell_fields[name] = CellField(
            values=output,
            unit=source_field.unit,
            source=source_field.source,
            keyword=source_field.keyword,
            aggregation=source_field.aggregation,
            role=source_field.role,
        )

    if porv_values is not None:
        effective = np.asarray(result.cell_fields["PORV"].values, dtype=float) / np.asarray(
            [cell.measure for cell in result.cells], dtype=float
        )
        result.cell_fields["PORO_EFFECTIVE"] = CellField(
            values=effective,
            unit="",
            source="derived during vertical-run coarsening",
            keyword="PORO_EFFECTIVE",
            aggregation="derived",
            role="derived",
        )

    for group_id, (cell, group) in enumerate(zip(result.cells, groups)):
        members = tuple(int(value) for value in group["members"])
        global_members = tuple(
            int(source.cells[cell_id].source_global_index)
            for cell_id in members
            if source.cells[cell_id].source_global_index is not None
        )
        cell.source_kind = "petrel_vertical_run"
        cell.source_global_index = global_members[0] if global_members else None
        cell.active_index = group_id
        cell.ijk = (int(group["i"]), int(group["j"]), int(group["k_top"]))
        cell.source_members = global_members

    geometry_by_pair = {
        tuple(sorted((connection.cell1, connection.cell2))): connection.id
        for connection in result.connections
    }
    for key, item in sorted(aggregates.items()):
        transmissibility = float(item["positive_trans"])
        matched = geometry_by_pair.get(key) if transmissibility > 0.0 else None
        status = (
            "matched"
            if matched is not None
            else "zero_trans"
            if transmissibility <= 0.0
            else "aggregated_unrepresented"
        )
        directions = item["directions"]
        source_connection = SourceConnection(
            id=len(result.source_connections),
            cell1=key[0],
            cell2=key[1],
            kind="aggregated",
            direction=next(iter(directions)) if len(directions) == 1 else None,
            transmissibility=transmissibility,
            flow_connected=transmissibility > 0.0,
            matched_connection=matched,
            geometry_status=status,
            source_count=int(item["source_count"]),
            metadata={
                "regular_transmissibility": float(item["regular_trans"]),
                "nnc_transmissibility": float(item["nnc_trans"]),
                "positive_source_count": int(item["positive_count"]),
                "zero_trans_source_count": int(item["zero_count"]),
                "nonconforming_source_count": int(item["nonconforming_count"]),
            },
        )
        result.source_connections.append(source_connection)
        if matched is not None:
            result.connections[matched].source_connection_id = source_connection.id

    source_geometry_total = float(source_volumes.sum())
    coarse_geometry_total = float(sum(cell.measure for cell in result.cells))
    source_components, source_isolated = _component_count(
        len(source.cells), source.source_connections
    )
    coarse_components, coarse_isolated = _component_count(
        len(result.cells), result.source_connections
    )
    conservation: dict[str, object] = {
        "source_cells": len(source.cells),
        "coarse_cells": len(result.cells),
        "reduction_fraction": 1.0 - len(result.cells) / len(source.cells),
        "geometry_volume_source": source_geometry_total,
        "geometry_volume_coarse": coarse_geometry_total,
        "geometry_volume_difference": coarse_geometry_total - source_geometry_total,
        "geometry_volume_relative_difference": (
            (coarse_geometry_total - source_geometry_total) / source_geometry_total
            if source_geometry_total
            else None
        ),
        "envelope_geometry_volume": envelope_volume_total,
        "envelope_geometry_volume_difference": (
            envelope_volume_total - source_geometry_total
        ),
        "envelope_geometry_volume_relative_difference": (
            (envelope_volume_total - source_geometry_total) / source_geometry_total
            if source_geometry_total
            else None
        ),
        "porv_source": float(np.nansum(porv_values)) if porv_values is not None else None,
        "porv_coarse": (
            float(np.nansum(result.cell_fields["PORV"].values))
            if "PORV" in result.cell_fields
            else None
        ),
        "external_positive_trans_source": float(
            sum(
                max(connection.transmissibility, 0.0)
                for connection in source.source_connections
                if old_to_group[connection.cell1] != old_to_group[connection.cell2]
            )
        ),
        "external_positive_trans_coarse": float(
            sum(connection.transmissibility for connection in result.source_connections)
        ),
        "internal_source_connections_removed": internal_source_count,
        "internal_positive_trans_removed": internal_positive_trans,
        "source_graph_components": source_components,
        "coarse_graph_components": coarse_components,
        "source_isolated_cells": source_isolated,
        "coarse_isolated_cells": coarse_isolated,
        "shared_full_face_pairs": len(shared_pairs),
        "maximum_node_merge_error": maximum_merge_error,
    }
    result.metadata = copy.deepcopy(source.metadata)
    source_diagnostics = copy.deepcopy(result.metadata.get("diagnostics", {}))
    result.metadata["diagnostics"] = coarse_diagnostics
    result.metadata["diagnostics"]["source_native"] = source_diagnostics
    result.metadata["source_format"] = "petrel-eclipse-vertical-runs"
    result.metadata.setdefault("petrel", {})["grid_mode"] = "vertical_runs"
    result.metadata["petrel"]["coarsening"] = conservation
    _progress(progress, cancelled, 2, 3)

    from .validation import validate_model

    validate_model(result, report=result.report)
    _progress(progress, cancelled, 3, 3)
    return result
