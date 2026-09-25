"""Native Petrel and ECLIPSE corner-point grid import."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Sequence

import meshio
import numpy as np

from .converter import convert_meshio
from .eclio import (
    cell_corners,
    first_values,
    local_to_map,
    neighbor_global,
    parse_grdecl_property,
    parse_nnc,
    read_ecl_records,
    read_first_restart,
)
from .model import CellField, ConversionOptions, FVModel, SourceConnection


class PetrelImportError(ValueError):
    """Raised when a Petrel source cannot be imported without data loss."""


class PetrelImportCancelled(PetrelImportError):
    """Raised when a caller cancels a long-running import."""


ProgressCallback = Callable[[str, int, int], None]
CancelCallback = Callable[[], bool]


PETREL_TO_GMSH_NEGATIVE_DEPTH = (4, 6, 7, 5, 0, 2, 3, 1)
PETREL_TO_GMSH_POSITIVE_DEPTH = (0, 1, 3, 2, 4, 5, 7, 6)
DIRECTION_CORNERS = {
    "X": ((3, 0), (2, 1), (6, 5), (7, 4)),
    "Y": ((1, 0), (2, 3), (6, 7), (5, 4)),
    "Z": ((0, 4), (1, 5), (2, 6), (3, 7)),
}

INIT_FIELD_KEYS = {
    "PORV",
    "DEPTH",
    "TRANX",
    "TRANY",
    "TRANZ",
    "DX",
    "DY",
    "DZ",
    "PERMX",
    "PERMY",
    "PERMZ",
    "PORO",
    "NTG",
    "MULTX",
    "MULTY",
    "MULTZ",
    "TOPS",
    "FIPNUM",
    "SATNUM",
    "PVTNUM",
    "EQLNUM",
    "SWL",
    "SWCR",
    "SWU",
    "SGL",
    "SGCR",
    "SGU",
    "SOWCR",
    "SOGCR",
}

FIELD_UNITS = {
    "PORV": "m3",
    "DEPTH": "m",
    "DX": "m",
    "DY": "m",
    "DZ": "m",
    "TOPS": "m",
    "TRANX": "simulator transmissibility",
    "TRANY": "simulator transmissibility",
    "TRANZ": "simulator transmissibility",
    "PERMX": "mD",
    "PERMY": "mD",
    "PERMZ": "mD",
    "PRESSURE": "Pa",
    "TEMP": "degC",
    "TEMPERATURE": "degC",
    "PGAS": "Pa",
    "POIL": "Pa",
    "PWAT": "Pa",
    "PSAT": "Pa",
    "PCOINIT": "Pa",
    "PCGINIT": "Pa",
    "PCWINIT": "Pa",
    "DENG": "kg/m3",
    "DENO": "kg/m3",
    "DENW": "kg/m3",
}

SUM_FIELDS = {"PORV"}
INTEGER_FIELDS = {"FIPNUM", "SATNUM", "PVTNUM", "EQLNUM"}
PRESSURE_FIELDS = {
    "PRESSURE",
    "PGAS",
    "POIL",
    "PWAT",
    "PSAT",
    "PCOINIT",
    "PCGINIT",
    "PCWINIT",
}


@dataclass(frozen=True, slots=True)
class PetrelInputFiles:
    """Files belonging to one Petrel simulator export."""

    egrid: Path
    init: Path | None = None
    nnc: Path | None = None
    unrst: Path | None = None
    properties: tuple[Path, ...] = ()

    @classmethod
    def discover(cls, source: str | Path) -> "PetrelInputFiles":
        source = Path(source).resolve()
        if source.is_dir():
            egrids = sorted(source.glob("*.EGRID"))
            if not egrids:
                egrids = sorted(source.glob("*.egrid"))
            if len(egrids) != 1:
                raise PetrelImportError(
                    f"Expected exactly one EGRID file in {source}; found {len(egrids)}."
                )
            egrid = egrids[0]
        elif source.is_file() and source.suffix.upper() == ".EGRID":
            egrid = source
            source = source.parent
        else:
            raise PetrelImportError("Petrel input must be an EGRID file or its directory.")

        grid_stem = egrid.stem
        case_stem = grid_stem[:-5] if grid_stem.upper().endswith("_GRID") else grid_stem

        def unique_or_named(named: Path, pattern: str) -> Path | None:
            if named.is_file():
                return named
            matches = sorted(source.glob(pattern))
            return matches[0] if len(matches) == 1 else None

        init = unique_or_named(source / f"{case_stem}.INIT", "*.INIT")
        nnc = unique_or_named(source / f"{grid_stem}_NNC.GRDECL", "*_GRID_NNC.GRDECL")
        unrst = unique_or_named(source / f"{case_stem}.UNRST", "*.UNRST")
        properties = tuple(sorted(source.glob(f"{case_stem}_PROP_*.GRDECL")))
        return cls(egrid=egrid, init=init, nnc=nnc, unrst=unrst, properties=properties)

    def as_dict(self) -> dict[str, object]:
        return {
            "egrid": str(self.egrid),
            "init": str(self.init) if self.init else None,
            "nnc": str(self.nnc) if self.nnc else None,
            "unrst": str(self.unrst) if self.unrst else None,
            "properties": [str(path) for path in self.properties],
        }


@dataclass(slots=True)
class PetrelImportOptions:
    """Options controlling native corner-point grid import."""

    grid_mode: str = "native"
    initial_state: str = "none"
    coordinate_mode: str = "map"
    origin_x: float = 0.0
    origin_y: float = 0.0
    z_mode: str = "negative-depth"
    tolerance: float = 1.0e-6
    property_paths: tuple[Path, ...] = ()
    nnc_path: Path | None = None
    conversion_options: ConversionOptions = field(
        default_factory=lambda: ConversionOptions(tolerance=1.0e-9)
    )

    def validate(self) -> None:
        if self.grid_mode not in {"native", "vertical_runs"}:
            raise PetrelImportError("grid_mode must be native or vertical_runs.")
        if self.initial_state not in {"none", "first"}:
            raise PetrelImportError("initial_state must be none or first.")
        if self.coordinate_mode not in {"map", "local"}:
            raise PetrelImportError("coordinate_mode must be map or local.")
        if self.z_mode not in {"negative-depth", "positive-depth"}:
            raise PetrelImportError("z_mode must be negative-depth or positive-depth.")
        if self.tolerance <= 0.0:
            raise PetrelImportError("Petrel corner matching tolerance must be positive.")


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
    stage: str,
    current: int,
    total: int,
) -> None:
    if cancelled is not None and cancelled():
        raise PetrelImportCancelled(f"Petrel import cancelled during {stage}.")
    if callback is not None:
        callback(stage, current, total)


def _grid_values(files: PetrelInputFiles) -> tuple[dict[str, object], int, int, int]:
    values = first_values(
        read_ecl_records(
            files.egrid,
            load_keys={"GRIDHEAD", "COORD", "ZCORN", "ACTNUM", "MAPAXES"},
        )
    )
    missing = sorted({"GRIDHEAD", "COORD", "ZCORN", "ACTNUM"} - values.keys())
    if missing:
        raise PetrelImportError(f"EGRID is missing required keyword(s): {', '.join(missing)}.")
    header = values["GRIDHEAD"]
    nx, ny, nz = (int(header[index]) for index in (1, 2, 3))
    total = nx * ny * nz
    if len(values["ACTNUM"]) != total:
        raise PetrelImportError("ACTNUM length does not agree with GRIDHEAD.")
    if len(values["COORD"]) != 6 * (nx + 1) * (ny + 1):
        raise PetrelImportError("COORD length does not agree with GRIDHEAD.")
    if len(values["ZCORN"]) != 8 * total:
        raise PetrelImportError("ZCORN length does not agree with GRIDHEAD.")
    return values, nx, ny, nz


def inspect_petrel(source: str | Path | PetrelInputFiles) -> dict[str, object]:
    """Inspect the discovered Petrel case without building finite-volume geometry."""

    files = source if isinstance(source, PetrelInputFiles) else PetrelInputFiles.discover(source)
    values, nx, ny, nz = _grid_values(files)
    active = sum(bool(value) for value in values["ACTNUM"])
    return {
        "input_kind": "petrel",
        "files": files.as_dict(),
        "dimensions": [nx, ny, nz],
        "logical_cells": nx * ny * nz,
        "active_cells": active,
        "inactive_cells": nx * ny * nz - active,
        "mapaxes": [float(value) for value in values.get("MAPAXES", [])],
    }


def _face_matches(
    corners: Sequence[tuple[float, float, float]],
    left_offset: int,
    right_offset: int,
    pairs: Sequence[tuple[int, int]],
    tolerance: float,
) -> tuple[bool, float]:
    maximum = 0.0
    for left, right in pairs:
        point = corners[left_offset + left]
        other = corners[right_offset + right]
        maximum = max(maximum, *(abs(point[axis] - other[axis]) for axis in range(3)))
    return maximum <= tolerance, maximum


def _active_values(
    raw_values: Sequence[float],
    active_globals: Sequence[int],
    total_cells: int,
    keyword: str,
) -> np.ndarray:
    values = np.asarray(raw_values)
    if len(values) == len(active_globals):
        return values.astype(float, copy=True)
    if len(values) == total_cells:
        return values[np.asarray(active_globals, dtype=int)].astype(float, copy=True)
    raise PetrelImportError(
        f"{keyword} has {len(values)} values; expected {len(active_globals)} active "
        f"values or {total_cells} logical values."
    )


def _field(
    keyword: str,
    values: np.ndarray,
    source: Path,
    *,
    role: str = "property",
) -> CellField:
    aggregation = "sum" if keyword in SUM_FIELDS else "mode" if keyword in INTEGER_FIELDS else "mean"
    return CellField(
        values=np.asarray(values, dtype=float),
        unit=FIELD_UNITS.get(keyword, ""),
        source=str(source),
        keyword=keyword,
        aggregation=aggregation,
        role=role,
    )


def _load_fields(
    files: PetrelInputFiles,
    options: PetrelImportOptions,
    active_globals: Sequence[int],
    total_cells: int,
) -> tuple[dict[str, CellField], dict[str, np.ndarray]]:
    fields: dict[str, CellField] = {}
    init_arrays: dict[str, np.ndarray] = {}
    if files.init:
        values = first_values(read_ecl_records(files.init, load_keys=INIT_FIELD_KEYS))
        for keyword, raw in values.items():
            active = _active_values(raw, active_globals, total_cells, keyword)
            init_arrays[keyword] = active
            fields[keyword] = _field(
                keyword,
                active,
                files.init,
                role="transmissibility" if keyword.startswith("TRAN") else "property",
            )

    property_paths: list[Path] = list(files.properties)
    for path in options.property_paths:
        candidate = Path(path)
        if candidate.is_file():
            resolved = candidate.resolve()
        else:
            keyword = candidate.name.upper()
            matches = [
                item
                for item in files.properties
                if item.stem.upper().endswith(f"_PROP_{keyword}")
            ]
            if len(matches) != 1:
                raise PetrelImportError(
                    f"Property {path!s} is neither a file nor a unique discovered keyword."
                )
            resolved = matches[0]
        if resolved not in property_paths:
            property_paths.append(resolved)
    for path in property_paths:
        keyword, raw, defaults = parse_grdecl_property(path)
        if defaults:
            raise PetrelImportError(
                f"{path.name} contains {defaults} GRDECL default values that cannot be inferred."
            )
        active = _active_values(raw, active_globals, total_cells, keyword)
        fields[keyword] = _field(keyword, active, path)

    if options.initial_state == "first":
        if files.unrst is None:
            raise PetrelImportError("initial_state=first requires an UNRST file.")
        restart = read_first_restart(files.unrst)["values"]
        for keyword, raw in restart.items():
            if keyword in {"SEQNUM", "INTEHEAD", "DOUBHEAD", "ZCOMPS", "ZPHASE", "ZFLUID"}:
                continue
            try:
                active = _active_values(raw, active_globals, total_cells, keyword)
            except PetrelImportError:
                continue
            if keyword in PRESSURE_FIELDS:
                active *= 1.0e5
            fields[keyword] = _field(keyword, active, files.unrst, role="initial_state")
    return fields, init_arrays


def _classify_petrel_geometry_diagnostics(model: FVModel) -> set[int]:
    """Preserve Petrel pinch diagnostics while disabling unsafe TOUGH links."""

    collapsed = [
        issue
        for issue in model.report.issues
        if issue.code == "degenerate_face" and issue.entity == "cell"
    ]
    outside = [
        issue
        for issue in model.report.issues
        if issue.code == "interface_not_between_centroids"
    ]
    invalid_face_ids = {
        int(issue.entity_id)
        for issue in outside
        if issue.entity == "face" and issue.entity_id is not None
    }
    invalid_connection_ids = {
        int(issue.entity_id)
        for issue in outside
        if issue.entity == "connection" and issue.entity_id is not None
    }
    disabled: set[int] = set()
    for connection in model.connections:
        if connection.face in invalid_face_ids or connection.id in invalid_connection_ids:
            connection.enabled = False
            disabled.add(connection.id)

    if collapsed or outside:
        model.report.issues = [
            issue
            for issue in model.report.issues
            if issue.code not in {"degenerate_face", "interface_not_between_centroids"}
        ]
        model.report.__post_init__()
    diagnostics = model.metadata.setdefault("diagnostics", {})
    if collapsed:
        cell_ids = sorted(
            {
                int(issue.entity_id)
                for issue in collapsed
                if issue.entity_id is not None
            }
        )
        diagnostics["collapsed_petrel_faces"] = {
            "count": len(collapsed),
            "cell_count": len(cell_ids),
            "cell_ids": cell_ids,
            "sample_cell_ids": cell_ids[:20],
            "handling": "zero-area face omitted; positive-volume source cell retained",
        }
        model.report.add(
            "warning",
            "collapsed_petrel_faces",
            (
                f"{len(collapsed)} zero-area Petrel pinch face(s) were omitted; "
                "affected source cell IDs are retained in metadata."
            ),
        )
    if disabled:
        diagnostics["disabled_petrel_connections"] = {
            "count": len(disabled),
            "connection_ids": sorted(disabled),
            "sample_connection_ids": sorted(disabled)[:20],
            "reason": "shared-face plane is not between adjacent cell centroids",
            "handling": "geometry retained for audit but disabled for TOUGH export",
        }
        model.report.add(
            "warning",
            "disabled_petrel_connections",
            (
                f"{len(disabled)} Petrel geometric connection(s) have an unsafe "
                "centroid/interface relation and are disabled for solver export."
            ),
        )
    return disabled


def _source_graph_statistics(
    cell_count: int, connections: Sequence[SourceConnection]
) -> dict[str, int]:
    union = _UnionFind(cell_count)
    degree = np.zeros(cell_count, dtype=np.int64)
    positive = 0
    for connection in connections:
        if not connection.flow_connected or connection.transmissibility <= 0.0:
            continue
        positive += 1
        union.union(connection.cell1, connection.cell2)
        degree[connection.cell1] += 1
        degree[connection.cell2] += 1
    components = Counter(union.find(index) for index in range(cell_count))
    return {
        "positive_source_connections": positive,
        "components": len(components),
        "largest_component_cells": max(components.values()) if components else 0,
        "smallest_component_cells": min(components.values()) if components else 0,
        "isolated_cells": int(np.count_nonzero(degree == 0)),
    }


def convert_petrel(
    source: str | Path | PetrelInputFiles,
    options: PetrelImportOptions | None = None,
    *,
    progress: ProgressCallback | None = None,
    cancelled: CancelCallback | None = None,
) -> FVModel:
    """Convert a Petrel corner-point export directly to an FVModel."""

    options = options or PetrelImportOptions()
    options.validate()
    files = source if isinstance(source, PetrelInputFiles) else PetrelInputFiles.discover(source)
    if options.nnc_path is not None:
        nnc_path = Path(options.nnc_path).resolve()
        if not nnc_path.is_file():
            raise PetrelImportError(f"NNC file does not exist: {nnc_path}")
        files = PetrelInputFiles(
            egrid=files.egrid,
            init=files.init,
            nnc=nnc_path,
            unrst=files.unrst,
            properties=files.properties,
        )
    _progress(progress, cancelled, "read_grid", 0, 1)
    grid, nx, ny, nz = _grid_values(files)
    total_cells = nx * ny * nz
    actnum = grid["ACTNUM"]
    active_globals = [index for index, value in enumerate(actnum) if value]
    active_count = len(active_globals)
    if not active_count:
        raise PetrelImportError("The EGRID contains no active cells.")
    cell_of_global = {
        global_index: active_index
        for active_index, global_index in enumerate(active_globals)
    }
    fields, init_arrays = _load_fields(files, options, active_globals, total_cells)
    trans_available = all(
        f"TRAN{direction}" in init_arrays for direction in ("X", "Y", "Z")
    )
    if any(f"TRAN{direction}" in init_arrays for direction in ("X", "Y", "Z")):
        if not trans_available:
            raise PetrelImportError("INIT must provide TRANX, TRANY and TRANZ together.")
    _progress(progress, cancelled, "read_grid", 1, 1)

    permutation = (
        PETREL_TO_GMSH_NEGATIVE_DEPTH
        if options.z_mode == "negative-depth"
        else PETREL_TO_GMSH_POSITIVE_DEPTH
    )
    mapaxes = grid.get("MAPAXES", [])
    corner_points: list[tuple[float, float, float]] = [
        (0.0, 0.0, 0.0)
    ] * (active_count * 8)
    ijks: list[tuple[int, int, int]] = []
    _progress(progress, cancelled, "build_geometry", 0, active_count)
    for active_index, global_index in enumerate(active_globals):
        raw_corners, ijk = cell_corners(
            global_index,
            nx,
            ny,
            grid["COORD"],
            grid["ZCORN"],
        )
        transformed: list[tuple[float, float, float]] = []
        for x_value, y_value, depth in raw_corners:
            if options.coordinate_mode == "map":
                x_value, y_value = local_to_map(x_value, y_value, mapaxes)
            z_value = -depth if options.z_mode == "negative-depth" else depth
            transformed.append(
                (
                    x_value - options.origin_x,
                    y_value - options.origin_y,
                    z_value,
                )
            )
        ordered = [transformed[index] for index in permutation]
        corner_points[active_index * 8 : active_index * 8 + 8] = ordered
        ijks.append(ijk)
        if (active_index + 1) % 5000 == 0 or active_index + 1 == active_count:
            _progress(
                progress,
                cancelled,
                "build_geometry",
                active_index + 1,
                active_count,
            )

    topology = _UnionFind(active_count * 8)
    regular_rows: list[dict[str, object]] = []
    logical_pairs = 0
    nonconforming_pairs = 0
    maximum_face_mismatch = 0.0
    _progress(progress, cancelled, "build_topology", 0, active_count)
    for active_index, global_index in enumerate(active_globals):
        left_offset = active_index * 8
        for direction in ("X", "Y", "Z"):
            neighbor_global_index = neighbor_global(
                global_index, direction, nx, ny, nz
            )
            if (
                neighbor_global_index is None
                or not actnum[neighbor_global_index]
            ):
                continue
            logical_pairs += 1
            neighbor_index = cell_of_global[neighbor_global_index]
            right_offset = neighbor_index * 8
            pairs = DIRECTION_CORNERS[direction]
            conforming, mismatch = _face_matches(
                corner_points,
                left_offset,
                right_offset,
                pairs,
                options.tolerance,
            )
            maximum_face_mismatch = max(maximum_face_mismatch, mismatch)
            nonconforming_pairs += int(not conforming)
            transmissibility = (
                float(init_arrays[f"TRAN{direction}"][active_index])
                if trans_available
                else None
            )
            if transmissibility is not None:
                regular_rows.append(
                    {
                        "cell1": active_index,
                        "cell2": neighbor_index,
                        "direction": direction,
                        "transmissibility": transmissibility,
                        "conforming": conforming,
                        "corner_mismatch": mismatch,
                    }
                )
            if conforming and (transmissibility is None or transmissibility > 0.0):
                for left_corner, right_corner in pairs:
                    topology.union(
                        left_offset + left_corner,
                        right_offset + right_corner,
                    )
        if (active_index + 1) % 5000 == 0 or active_index + 1 == active_count:
            _progress(
                progress,
                cancelled,
                "build_topology",
                active_index + 1,
                active_count,
            )

    root_to_node: dict[int, int] = {}
    points: list[tuple[float, float, float]] = []
    corner_nodes = np.empty(active_count * 8, dtype=np.int64)
    maximum_merged_corner_error = 0.0
    for corner_index, point in enumerate(corner_points):
        root = topology.find(corner_index)
        node = root_to_node.get(root)
        if node is None:
            node = len(points)
            root_to_node[root] = node
            points.append(point)
        else:
            representative = points[node]
            maximum_merged_corner_error = max(
                maximum_merged_corner_error,
                *(abs(point[axis] - representative[axis]) for axis in range(3)),
            )
        corner_nodes[corner_index] = node
    hexahedra = corner_nodes.reshape(active_count, 8)
    mesh = meshio.Mesh(
        points=np.asarray(points, dtype=float),
        cells=[("hexahedron", hexahedra)],
        cell_data={"gmsh:physical": [np.ones(active_count, dtype=np.int32)]},
        field_data={"Reservoir": np.asarray([1, 3], dtype=np.int32)},
    )
    _progress(progress, cancelled, "finite_volume_geometry", 0, 1)
    model = convert_meshio(
        mesh,
        source_path=files.egrid,
        options=options.conversion_options,
    )
    if len(model.cells) != active_count:
        raise PetrelImportError(
            f"Only {len(model.cells)} of {active_count} active Petrel cells produced "
            "valid finite-volume geometry."
        )
    disabled_geometry = _classify_petrel_geometry_diagnostics(model)
    _progress(progress, cancelled, "finite_volume_geometry", 1, 1)

    for active_index, cell in enumerate(model.cells):
        global_index = active_globals[active_index]
        cell.source_kind = "petrel_active_cell"
        cell.source_global_index = global_index
        cell.active_index = active_index
        cell.ijk = ijks[active_index]
        cell.source_members = (global_index,)
    model.cell_fields = fields

    geometry_by_pair = {
        tuple(sorted((connection.cell1, connection.cell2))): connection.id
        for connection in model.connections
    }
    _progress(
        progress,
        cancelled,
        "source_connections",
        0,
        len(regular_rows) + (1 if files.nnc else 0),
    )
    matched_regular = 0
    disabled_regular = 0
    nonconforming_positive = 0
    zero_regular = 0
    for row_index, row in enumerate(regular_rows):
        cell1 = int(row["cell1"])
        cell2 = int(row["cell2"])
        transmissibility = float(row["transmissibility"])
        conforming = bool(row["conforming"])
        pair = tuple(sorted((cell1, cell2)))
        matched = geometry_by_pair.get(pair) if transmissibility > 0.0 and conforming else None
        if matched is not None:
            if matched in disabled_geometry:
                status = "disabled_geometry"
                disabled_regular += 1
            else:
                status = "matched"
            matched_regular += 1
        elif transmissibility <= 0.0:
            status = "zero_trans"
            zero_regular += 1
        elif not conforming:
            status = "nonconforming"
            nonconforming_positive += 1
        else:
            status = "geometry_error"
        source_connection = SourceConnection(
            id=len(model.source_connections),
            cell1=cell1,
            cell2=cell2,
            kind="regular",
            direction=str(row["direction"]),
            transmissibility=transmissibility,
            flow_connected=transmissibility > 0.0,
            matched_connection=matched,
            geometry_status=status,
            metadata={"corner_mismatch": float(row["corner_mismatch"])},
        )
        model.source_connections.append(source_connection)
        if matched is not None and model.connections[matched].source_connection_id is None:
            model.connections[matched].source_connection_id = source_connection.id
        if (row_index + 1) % 10000 == 0:
            _progress(
                progress,
                cancelled,
                "source_connections",
                row_index + 1,
                len(regular_rows) + (1 if files.nnc else 0),
            )

    nnc_stats: dict[str, object] = {}
    excluded_nnc = 0
    if files.nnc:
        nnc_rows, nnc_stats = parse_nnc(
            files.nnc, nx, ny, nz, active_globals
        )
        for row in nnc_rows:
            global1 = int(row["global1"])
            global2 = int(row["global2"])
            if (
                global1 not in cell_of_global
                or global2 not in cell_of_global
                or global1 == global2
            ):
                excluded_nnc += 1
                continue
            transmissibility = float(row["transmissibility"])
            model.source_connections.append(
                SourceConnection(
                    id=len(model.source_connections),
                    cell1=cell_of_global[global1],
                    cell2=cell_of_global[global2],
                    kind="nnc",
                    direction=None,
                    transmissibility=transmissibility,
                    flow_connected=transmissibility > 0.0,
                    matched_connection=None,
                    geometry_status="nnc",
                    metadata={
                        "source_ijk1": [
                            int(row["i1"]),
                            int(row["j1"]),
                            int(row["k1"]),
                        ],
                        "source_ijk2": [
                            int(row["i2"]),
                            int(row["j2"]),
                            int(row["k2"]),
                        ],
                    },
                )
            )

    model.metadata.update(
        {
            "source_path": str(files.egrid),
            "source_format": "petrel-eclipse",
            "input_kind": "petrel",
            "petrel": {
                "files": files.as_dict(),
                "dimensions": [nx, ny, nz],
                "logical_cells": total_cells,
                "active_cells": active_count,
                "inactive_cells": total_cells - active_count,
                "grid_mode": options.grid_mode,
                "initial_state": options.initial_state,
                "coordinate_transform": {
                    "xy": options.coordinate_mode,
                    "origin_x": options.origin_x,
                    "origin_y": options.origin_y,
                    "z": options.z_mode,
                    "corner_tolerance": options.tolerance,
                    "mapaxes": [float(value) for value in mapaxes],
                },
                "topology": {
                    "logical_active_pairs": logical_pairs,
                    "nonconforming_logical_pairs": nonconforming_pairs,
                    "maximum_logical_face_mismatch": maximum_face_mismatch,
                    "maximum_merged_corner_error": maximum_merged_corner_error,
                    "regular_rows": len(regular_rows),
                    "matched_regular": matched_regular,
                    "disabled_regular_geometry": disabled_regular,
                    "zero_regular": zero_regular,
                    "nonconforming_positive_regular": nonconforming_positive,
                    "nnc_rows": int(nnc_stats.get("rows", 0)),
                    "excluded_nnc_rows": excluded_nnc,
                    "flow_graph": _source_graph_statistics(
                        len(model.cells), model.source_connections
                    ),
                },
            },
        }
    )
    _progress(
        progress,
        cancelled,
        "source_connections",
        len(regular_rows) + (1 if files.nnc else 0),
        len(regular_rows) + (1 if files.nnc else 0),
    )

    from .validation import validate_model

    validate_model(model, report=model.report)
    if options.grid_mode == "vertical_runs":
        from .coarsening import coarsen_vertical_runs

        return coarsen_vertical_runs(
            model,
            progress=progress,
            cancelled=cancelled,
        )
    return model
