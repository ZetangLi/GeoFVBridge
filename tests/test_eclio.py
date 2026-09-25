from __future__ import annotations

import struct
from pathlib import Path

import pytest

from geofvbridge.eclio import (
    cell_corners,
    first_values,
    local_to_map,
    parse_grdecl_property,
    parse_nnc,
    read_ecl_records,
)
from geofvbridge.petrel import PetrelImportOptions, convert_petrel, inspect_petrel


def _write_fortran_record(handle, payload: bytes) -> None:
    handle.write(struct.pack(">i", len(payload)))
    handle.write(payload)
    handle.write(struct.pack(">i", len(payload)))


def _write_keyword(handle, keyword: str, type_name: str, values) -> None:
    if type_name == "INTE":
        payload = struct.pack(f">{len(values)}i", *values)
    elif type_name == "REAL":
        payload = struct.pack(f">{len(values)}f", *values)
    elif type_name == "DOUB":
        payload = struct.pack(f">{len(values)}d", *values)
    elif type_name == "CHAR":
        payload = b"".join(str(value).encode("ascii").ljust(8)[:8] for value in values)
    else:
        raise AssertionError(type_name)
    header = keyword.encode("ascii").ljust(8)[:8]
    header += struct.pack(">i", len(values)) + type_name.encode("ascii")
    _write_fortran_record(handle, header)
    _write_fortran_record(handle, payload)


def test_binary_reader_selects_keywords_without_loading_others(tmp_path: Path) -> None:
    path = tmp_path / "tiny.EGRID"
    with path.open("wb") as handle:
        _write_keyword(handle, "GRIDHEAD", "INTE", [1, 2, 3, 4])
        _write_keyword(handle, "COORD", "REAL", [0.0, 1.5, 2.5])
        _write_keyword(handle, "TITLE", "CHAR", ["tiny"])

    records = read_ecl_records(path, load_keys={"GRIDHEAD", "TITLE"})
    values = first_values(records)
    assert list(values["GRIDHEAD"]) == [1, 2, 3, 4]
    assert values["TITLE"] == ["tiny"]
    assert "COORD" not in values
    assert records[1]["value"] is None


def test_corner_interpolation_and_mapaxes() -> None:
    coord = [
        0, 0, 0, 0, 0, 1,
        1, 0, 0, 1, 0, 1,
        0, 1, 0, 0, 1, 1,
        1, 1, 0, 1, 1, 1,
    ]
    corners, ijk = cell_corners(0, 1, 1, coord, [0, 0, 0, 0, 1, 1, 1, 1])
    assert ijk == (1, 1, 1)
    assert corners == [
        (0.0, 0.0, 0.0),
        (1.0, 0.0, 0.0),
        (0.0, 1.0, 0.0),
        (1.0, 1.0, 0.0),
        (0.0, 0.0, 1.0),
        (1.0, 0.0, 1.0),
        (0.0, 1.0, 1.0),
        (1.0, 1.0, 1.0),
    ]
    assert local_to_map(2.0, 3.0, [100, 201, 100, 200, 101, 200]) == pytest.approx(
        (102.0, 203.0)
    )


def test_grdecl_repeat_defaults_and_nnc_indices(tmp_path: Path) -> None:
    prop = tmp_path / "CASE_PROP_PORO.GRDECL"
    prop.write_text("PORO\n2*0.1 1* 0.25 /\n", encoding="ascii")
    keyword, values, defaults = parse_grdecl_property(prop)
    assert keyword == "PORO"
    assert list(values[:2]) == pytest.approx([0.1, 0.1])
    assert values[2] != values[2]
    assert values[3] == pytest.approx(0.25)
    assert defaults == 1

    nnc = tmp_path / "CASE_GRID_NNC.GRDECL"
    nnc.write_text(
        "NNC\n"
        "1 1 1 2 1 1 1.5 /\n"
        "2 1 1 2 1 1 0 /\n"
        "3 1 1 1 1 1 2 /\n"
        "/\n",
        encoding="ascii",
    )
    rows, stats = parse_nnc(nnc, 2, 1, 1, {0, 1})
    assert rows[0]["global1"] == 0
    assert rows[0]["global2"] == 1
    assert stats["rows"] == 3
    assert stats["positive"] == 2
    assert stats["nonpositive"] == 1
    assert stats["self_connection"] == 1
    assert stats["invalid_index"] == 1


def test_native_petrel_import_preserves_cells_fields_and_trans(tmp_path: Path) -> None:
    egrid = tmp_path / "CASE_GRID.EGRID"
    coord = []
    for y_value in (0.0, 1.0):
        for x_value in (0.0, 1.0, 2.0):
            coord.extend([x_value, y_value, 0.0, x_value, y_value, 1.0])
    with egrid.open("wb") as handle:
        _write_keyword(handle, "GRIDHEAD", "INTE", [0, 2, 1, 1])
        _write_keyword(handle, "COORD", "REAL", coord)
        _write_keyword(handle, "ZCORN", "REAL", [0.0] * 8 + [1.0] * 8)
        _write_keyword(handle, "ACTNUM", "INTE", [1, 1])

    init = tmp_path / "CASE.INIT"
    with init.open("wb") as handle:
        _write_keyword(handle, "TRANX", "REAL", [1.5, 0.0])
        _write_keyword(handle, "TRANY", "REAL", [0.0, 0.0])
        _write_keyword(handle, "TRANZ", "REAL", [0.0, 0.0])
        _write_keyword(handle, "PORV", "REAL", [0.2, 0.3])
    (tmp_path / "CASE_PROP_PORO.GRDECL").write_text(
        "PORO\n0.2 0.3 /\n", encoding="ascii"
    )

    inspection = inspect_petrel(tmp_path)
    assert inspection["dimensions"] == [2, 1, 1]
    assert inspection["active_cells"] == 2

    model = convert_petrel(
        tmp_path,
        PetrelImportOptions(coordinate_mode="local", z_mode="negative-depth"),
    )
    assert len(model.cells) == 2
    assert len(model.connections) == 1
    assert [cell.ijk for cell in model.cells] == [(1, 1, 1), (2, 1, 1)]
    assert [cell.measure for cell in model.cells] == pytest.approx([1.0, 1.0])
    assert model.cells[0].centroid.tolist() == pytest.approx([0.5, 0.5, -0.5])
    assert model.cell_fields["PORO"].values.tolist() == pytest.approx([0.2, 0.3])
    regular = [row for row in model.source_connections if row.kind == "regular"]
    assert len(regular) == 1
    assert regular[0].transmissibility == pytest.approx(1.5)
    assert regular[0].matched_connection == 0
    assert model.connections[0].source_connection_id == regular[0].id
    assert model.metadata["petrel"]["topology"]["flow_graph"]["components"] == 1
    assert model.metadata["petrel"]["topology"]["flow_graph"]["isolated_cells"] == 0
    assert model.report.valid


def test_vertical_run_import_aggregates_fields_and_parallel_trans(tmp_path: Path) -> None:
    egrid = tmp_path / "STACK_GRID.EGRID"
    coord = []
    for y_value in (0.0, 1.0):
        for x_value in (0.0, 1.0, 2.0):
            coord.extend([x_value, y_value, 0.0, x_value, y_value, 2.0])
    with egrid.open("wb") as handle:
        _write_keyword(handle, "GRIDHEAD", "INTE", [0, 2, 1, 2])
        _write_keyword(handle, "COORD", "REAL", coord)
        _write_keyword(
            handle,
            "ZCORN",
            "REAL",
            [0.0] * 8 + [1.0] * 8 + [1.0] * 8 + [2.0] * 8,
        )
        _write_keyword(handle, "ACTNUM", "INTE", [1, 1, 1, 1])

    with (tmp_path / "STACK.INIT").open("wb") as handle:
        _write_keyword(handle, "TRANX", "REAL", [1.0, 0.0, 2.0, 0.0])
        _write_keyword(handle, "TRANY", "REAL", [0.0] * 4)
        _write_keyword(handle, "TRANZ", "REAL", [4.0, 5.0, 0.0, 0.0])
        _write_keyword(handle, "PORV", "REAL", [0.2, 0.3, 0.4, 0.5])
    (tmp_path / "STACK_PROP_PORO.GRDECL").write_text(
        "PORO\n0.2 0.3 0.4 0.5 /\n", encoding="ascii"
    )

    model = convert_petrel(
        tmp_path,
        PetrelImportOptions(
            grid_mode="vertical_runs",
            coordinate_mode="local",
            z_mode="negative-depth",
        ),
    )
    assert len(model.cells) == 2
    assert len(model.connections) == 1
    assert [cell.measure for cell in model.cells] == pytest.approx([2.0, 2.0])
    assert [len(cell.source_members) for cell in model.cells] == [2, 2]
    assert model.cell_fields["PORV"].values.tolist() == pytest.approx([0.6, 0.8])
    assert model.cell_fields["PORO"].values.tolist() == pytest.approx([0.3, 0.4])
    assert model.cell_fields["PORO_EFFECTIVE"].values.tolist() == pytest.approx([0.3, 0.4])
    assert len(model.source_connections) == 1
    assert model.source_connections[0].transmissibility == pytest.approx(3.0)
    assert model.source_connections[0].source_count == 2
    assert model.source_connections[0].matched_connection == 0
    conservation = model.metadata["petrel"]["coarsening"]
    assert conservation["porv_source"] == pytest.approx(conservation["porv_coarse"])
    assert conservation["external_positive_trans_source"] == pytest.approx(
        conservation["external_positive_trans_coarse"]
    )
    assert model.report.valid
