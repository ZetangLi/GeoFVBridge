"""Model validation independent from any solver backend."""

from __future__ import annotations

import numpy as np

from .model import FVModel, ValidationReport


def validate_model(model: FVModel, *, report: ValidationReport | None = None) -> ValidationReport:
    report = report or ValidationReport(list(model.report.issues))
    tolerance = model.options.tolerance
    if model.dimension not in {2, 3}:
        report.add("error", "invalid_dimension", "Model dimension must be 2 or 3.")
    if not model.cells:
        report.add("error", "empty_model", "The model contains no control volumes.")
        return report

    node_count = len(model.points)
    used_cells: set[int] = set()
    cell_ids = {cell.id for cell in model.cells}
    for cell in model.cells:
        if not np.isfinite(cell.measure) or cell.measure <= tolerance:
            report.add("error", "invalid_measure", "Cell measure is non-positive.", "cell", cell.id)
        if any(node < 0 or node >= node_count for node in cell.nodes):
            report.add("error", "invalid_node_reference", "Cell references an invalid node.", "cell", cell.id)

    for face in model.faces:
        if not np.isfinite(face.measure) or face.measure <= tolerance:
            report.add("error", "invalid_face_measure", "Face measure is non-positive.", "face", face.id)
        if not np.isclose(np.linalg.norm(face.normal), 1.0, rtol=1e-8, atol=1e-10):
            report.add("error", "invalid_face_normal", "Face normal is not unit length.", "face", face.id)

    for connection in model.connections:
        used_cells.update((connection.cell1, connection.cell2))
        disabled_geometry_issue = False
        if not np.all(np.isfinite(connection.intersection)):
            disabled_geometry_issue = True
            if connection.enabled:
                report.add(
                    "error",
                    "invalid_interface_intersection",
                    "Connection interface intersection is not finite.",
                    "connection",
                    connection.id,
                )
        if connection.d1 <= tolerance or connection.d2 <= tolerance:
            disabled_geometry_issue = True
            if connection.enabled:
                report.add(
                    "error",
                    "invalid_intersection_distance",
                    "A centroid-to-interface intersection distance is non-positive.",
                    "connection",
                    connection.id,
                )
        elif not np.isclose(
            connection.d1 + connection.d2,
            connection.center_distance,
            rtol=1.0e-9,
            atol=max(tolerance, 1.0e-12),
        ):
            disabled_geometry_issue = True
            if connection.enabled:
                report.add(
                    "error",
                    "interface_not_between_centroids",
                    "The interface intersection is not between the adjacent centroids.",
                    "connection",
                    connection.id,
                )
        if disabled_geometry_issue and not connection.enabled:
            report.add(
                "warning",
                "disabled_connection_geometry",
                "One or more invalid geometric connections are disabled for solver export.",
            )
        if connection.normal_d1 <= tolerance or connection.normal_d2 <= tolerance:
            report.add(
                "warning",
                "small_normal_distance",
                "A cell centroid lies on or very near its shared-face plane.",
                "connection",
                connection.id,
            )
        if not 0.0 <= connection.orthogonality <= 1.0 + 1e-12:
            report.add(
                "error",
                "invalid_orthogonality",
                "Connection orthogonality is outside [0, 1].",
                "connection",
                connection.id,
            )
        elif connection.orthogonality < 0.1:
            report.add(
                "warning",
                "poor_orthogonality",
                "Connection orthogonality is below 0.1.",
                "connection",
                connection.id,
            )

    for name, cell_field in model.cell_fields.items():
        if len(cell_field.values) != len(model.cells):
            report.add(
                "error",
                "invalid_cell_field_length",
                (
                    f"Cell field {name!r} has {len(cell_field.values)} values "
                    f"for {len(model.cells)} cells."
                ),
            )

    seen_source_pairs: set[tuple[int, int, str, str | None]] = set()
    for connection in model.source_connections:
        if connection.cell1 not in cell_ids or connection.cell2 not in cell_ids:
            report.add(
                "error",
                "invalid_source_connection_cell",
                "A source connection references an unknown cell.",
                "source_connection",
                connection.id,
            )
        if connection.cell1 == connection.cell2:
            report.add(
                "error",
                "source_connection_self_loop",
                "A source connection connects a cell to itself.",
                "source_connection",
                connection.id,
            )
        if not np.isfinite(connection.transmissibility) or connection.transmissibility < 0.0:
            report.add(
                "error",
                "invalid_source_transmissibility",
                "Source transmissibility must be finite and non-negative.",
                "source_connection",
                connection.id,
            )
        pair = (
            min(connection.cell1, connection.cell2),
            max(connection.cell1, connection.cell2),
            connection.kind,
            connection.direction,
        )
        if pair in seen_source_pairs:
            report.add(
                "warning",
                "duplicate_source_connection",
                "More than one source connection has the same cell pair, kind, and direction.",
                "source_connection",
                connection.id,
            )
        seen_source_pairs.add(pair)

    boundary_cells = {boundary.cell for boundary in model.boundaries}
    for cell in model.cells:
        if cell.id not in used_cells and cell.id not in boundary_cells:
            report.add(
                "warning", "isolated_cell", "Cell has no internal or boundary faces.", "cell", cell.id
            )
    if any(boundary.name == "UNASSIGNED" for boundary in model.boundaries):
        report.add(
            "warning",
            "unassigned_boundaries",
            "One or more exterior faces do not belong to a named physical group.",
        )
    return report
