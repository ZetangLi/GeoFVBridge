"""Solver-independent finite-volume data structures."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

FloatArray = NDArray[np.float64]


@dataclass(slots=True)
class ConversionOptions:
    length_unit: str = "m"
    gravity: tuple[float, float, float] = (0.0, 0.0, -1.0)
    thickness: float | None = None
    tolerance: float = 1.0e-12
    source_rule: str = "nearest_centroid"
    physical_roles: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class ExtrusionOptions:
    """Three-dimensional extrusion requested for a planar Gmsh mesh."""

    direction: tuple[float, float, float] = (0.0, 0.0, 1.0)
    layer_thicknesses: tuple[float, ...] = (1.0,)


@dataclass(slots=True)
class Cell:
    id: int
    cell_type: str
    nodes: tuple[int, ...]
    dimension: int
    measure: float
    centroid: FloatArray
    material: str = "DEFAULT"
    physical_tag: int | None = None
    source_id: int | None = None
    source_kind: str | None = None
    source_global_index: int | None = None
    active_index: int | None = None
    ijk: tuple[int, int, int] | None = None
    source_members: tuple[int, ...] = ()


@dataclass(slots=True)
class Face:
    id: int
    nodes: tuple[int, ...]
    owner: int
    neighbour: int | None
    measure: float
    centroid: FloatArray
    normal: FloatArray
    planarity: float = 0.0
    physical_group: str | None = None


@dataclass(slots=True)
class Connection:
    id: int
    cell1: int
    cell2: int
    face: int
    interface_measure: float
    d1: float
    d2: float
    intersection: FloatArray
    normal_d1: float
    normal_d2: float
    center_distance: float
    normal: FloatArray
    gravity_projection: float
    gravity_delta: float
    orthogonality: float
    enabled: bool = True
    source_connection_id: int | None = None


@dataclass(slots=True)
class CellField:
    values: np.ndarray
    unit: str = ""
    source: str = ""
    keyword: str = ""
    aggregation: str = "none"
    role: str = "property"


@dataclass(slots=True)
class SourceConnection:
    id: int
    cell1: int
    cell2: int
    kind: str
    transmissibility: float
    flow_connected: bool
    direction: str | None = None
    matched_connection: int | None = None
    geometry_status: str = "unmatched"
    source_count: int = 1
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Boundary:
    id: int
    face: int
    cell: int
    name: str
    kind: str = "unassigned"
    value: float | None = None


@dataclass(slots=True)
class Source:
    id: int
    name: str
    location: FloatArray
    cell: int
    distance: float
    kind: str = "source_candidate"
    rate: float | None = None


@dataclass(slots=True)
class ValidationIssue:
    severity: str
    code: str
    message: str
    entity: str | None = None
    entity_id: int | None = None


@dataclass(slots=True)
class ValidationReport:
    issues: list[ValidationIssue] = field(default_factory=list)
    _issue_keys: set[tuple[str, str, str, str | None, int | None]] = field(
        default_factory=set, init=False, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        self._issue_keys = {self._key(issue) for issue in self.issues}

    @staticmethod
    def _key(issue: ValidationIssue) -> tuple[str, str, str, str | None, int | None]:
        return (
            issue.severity,
            issue.code,
            issue.message,
            issue.entity,
            issue.entity_id,
        )

    @property
    def errors(self) -> list[ValidationIssue]:
        return [issue for issue in self.issues if issue.severity == "error"]

    @property
    def warnings(self) -> list[ValidationIssue]:
        return [issue for issue in self.issues if issue.severity == "warning"]

    @property
    def valid(self) -> bool:
        return not self.errors

    def add(
        self,
        severity: str,
        code: str,
        message: str,
        entity: str | None = None,
        entity_id: int | None = None,
    ) -> None:
        issue = ValidationIssue(severity, code, message, entity, entity_id)
        key = self._key(issue)
        if key in self._issue_keys:
            return
        self._issue_keys.add(key)
        self.issues.append(issue)

    def as_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "errors": len(self.errors),
            "warnings": len(self.warnings),
            "issues": [
                {
                    "severity": i.severity,
                    "code": i.code,
                    "message": i.message,
                    "entity": i.entity,
                    "entity_id": i.entity_id,
                }
                for i in self.issues
            ],
        }


@dataclass(slots=True)
class FVModel:
    points: FloatArray
    cells: list[Cell]
    faces: list[Face]
    connections: list[Connection]
    boundaries: list[Boundary]
    sources: list[Source]
    dimension: int
    cell_fields: dict[str, CellField] = field(default_factory=dict)
    source_connections: list[SourceConnection] = field(default_factory=list)
    options: ConversionOptions = field(default_factory=ConversionOptions)
    metadata: dict[str, Any] = field(default_factory=dict)
    report: ValidationReport = field(default_factory=ValidationReport)

    @property
    def source_path(self) -> Path | None:
        raw = self.metadata.get("source_path")
        return Path(raw) if raw else None

    def summary(self) -> dict[str, Any]:
        measures = np.asarray([cell.measure for cell in self.cells], dtype=float)
        quality = np.asarray([c.orthogonality for c in self.connections], dtype=float)
        nonplanarity = np.asarray([face.planarity for face in self.faces], dtype=float)
        materials: dict[str, int] = {}
        for cell in self.cells:
            materials[cell.material] = materials.get(cell.material, 0) + 1
        source_kinds: dict[str, int] = {}
        for connection in self.source_connections:
            source_kinds[connection.kind] = source_kinds.get(connection.kind, 0) + 1
        diagnostics = self.metadata.get("diagnostics", {})
        nonplanar = diagnostics.get("nonplanar_faces", {})

        def source_is_represented(connection: SourceConnection) -> bool:
            matched = connection.matched_connection
            return (
                matched is not None
                and 0 <= matched < len(self.connections)
                and self.connections[matched].enabled
            )

        return {
            "schema_version": "1.2",
            "dimension": self.dimension,
            "length_unit": self.options.length_unit,
            "points": int(len(self.points)),
            "cells": len(self.cells),
            "faces": len(self.faces),
            "connections": len(self.connections),
            "enabled_connections": sum(connection.enabled for connection in self.connections),
            "source_connections": len(self.source_connections),
            "source_connection_kinds": source_kinds,
            "unrepresented_positive_source_connections": sum(
                connection.flow_connected and not source_is_represented(connection)
                for connection in self.source_connections
            ),
            "boundaries": len(self.boundaries),
            "sources": len(self.sources),
            "cell_fields": sorted(self.cell_fields),
            "materials": materials,
            "measure_total": float(measures.sum()) if measures.size else 0.0,
            "measure_min": float(measures.min()) if measures.size else None,
            "orthogonality_min": float(quality.min()) if quality.size else None,
            "orthogonality_median": float(np.median(quality)) if quality.size else None,
            "face_nonplanarity_max": (
                float(nonplanarity.max()) if nonplanarity.size else None
            ),
            "face_nonplanarity_count": int(nonplanar.get("count", 0)),
            "face_nonplanarity_fraction": float(nonplanar.get("fraction", 0.0)),
            "validation": self.report.as_dict(),
            "metadata": self.metadata,
        }
