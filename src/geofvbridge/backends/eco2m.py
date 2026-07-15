"""TOUGH2/ECO2M fixed-width export and result extraction.

The backend consumes only :class:`geofvbridge.model.FVModel`; no solver-specific
assumptions are present in the finite-volume conversion core.
"""

from __future__ import annotations

import csv
import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import meshio
import numpy as np

from ..model import FVModel
from ..validation import validate_model

HEADER = "----1----*----2----*----3----*----4----*----5----*----6----*----7----*----8"
TOUGH_LABEL_ALPHA = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
TOUGH_LABEL_NOMEN = "123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
TOUGH_LABEL_NUMBER_COUNT = 100
TOUGH_LABEL_CAPACITY = (
    len(TOUGH_LABEL_ALPHA)
    * len(TOUGH_LABEL_NOMEN)
    * len(TOUGH_LABEL_NOMEN)
    * TOUGH_LABEL_NUMBER_COUNT
)


def _float_field(value: float | int | str, width: int = 10, precision: int = 8) -> str:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("TOUGH fixed-width fields require finite numbers.")
    # Regular scientific notation spends three characters on an exponent such
    # as E+02. TOUGH conventionally accepts a compact exponent such as e2/e-2,
    # leaving room for extra significant digits in a 10-column geometry field.
    for digits in range(precision, -1, -1):
        mantissa, exponent = f"{number:.{digits}e}".split("e")
        text = f"{mantissa}e{int(exponent)}"
        if len(text) <= width:
            return text.rjust(width)
    raise ValueError(f"Value {number!r} does not fit a {width}-character TOUGH field.")


def _label(index: int) -> str:
    """Return a deterministic five-character TOUGH A3,I2 label.

    The rightmost field is a two-column integer, so values below 10 retain a
    leading blank (for example A11 0). The two preceding nomenclature
    positions use the 1..9,A..Z progression.
    """
    if index < 0 or index >= TOUGH_LABEL_CAPACITY:
        raise ValueError(
            "The five-character A3,I2 label scheme supports at most "
            f"{TOUGH_LABEL_CAPACITY:,} cells."
        )
    nomen_index, number = divmod(index, TOUGH_LABEL_NUMBER_COUNT)
    leading_index, third_index = divmod(nomen_index, len(TOUGH_LABEL_NOMEN))
    first_index, second_index = divmod(leading_index, len(TOUGH_LABEL_NOMEN))
    return (
        f"{TOUGH_LABEL_ALPHA[first_index]}"
        f"{TOUGH_LABEL_NOMEN[second_index]}"
        f"{TOUGH_LABEL_NOMEN[third_index]}"
        f"{number:2d}"
    )


def _is_a3_i2(value: str) -> bool:
    if len(value) != 5 or not value.isascii():
        return False
    number = value[3:5]
    return number.isdigit() or (number[0] == " " and number[1].isdigit())


def _generator_label(value: Any, index: int, used: set[str]) -> str:
    requested = str(value)
    if _is_a3_i2(requested) and requested not in used:
        used.add(requested)
        return requested
    prefix = (re.sub(r"[^A-Za-z0-9]", "", requested)[:3] or "GEN").ljust(3)
    for offset in range(TOUGH_LABEL_NUMBER_COUNT):
        candidate = f"{prefix}{(index + offset + 1) % TOUGH_LABEL_NUMBER_COUNT:2d}"
        if candidate not in used:
            used.add(candidate)
            return candidate
    raise ValueError(f"More than 100 GENER names use the same A3 prefix {prefix!r}.")


def labels_for_model(model: FVModel) -> dict[int, str]:
    """Return the stable five-character TOUGH label for every FV cell."""
    return {cell.id: _label(cell.id) for cell in model.cells}


def _material_name(name: str, used: set[str]) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]", "", name.upper()) or "DFALT"
    base = cleaned[:5]
    candidate = base
    counter = 0
    while candidate in used:
        counter += 1
        suffix = np.base_repr(counter, base=36).upper()
        candidate = (base[: 5 - len(suffix)] + suffix)[-5:]
    used.add(candidate)
    return candidate.ljust(5)


def _config(config: dict[str, Any] | str | Path) -> dict[str, Any]:
    if isinstance(config, (str, Path)):
        return json.loads(Path(config).read_text(encoding="utf-8"))
    return dict(config)


def _effective_measure(model: FVModel, cell_measure: float) -> float:
    if model.dimension == 3:
        return cell_measure
    if model.options.thickness is None or model.options.thickness <= 0.0:
        raise ValueError("A positive model thickness is required for 2-D TOUGH2 export.")
    return cell_measure * model.options.thickness


def _effective_interface(model: FVModel, face_measure: float) -> float:
    return face_measure if model.dimension == 3 else face_measure * float(model.options.thickness)


def _inactive_cells(model: FVModel, config: dict[str, Any]) -> tuple[set[int], dict[int, list[str]]]:
    selected = {int(value) for value in config.get("inactive_cells", [])}
    reasons: dict[int, list[str]] = {cell_id: ["explicit"] for cell_id in selected}
    materials = {str(value) for value in config.get("inactive_materials", [])}
    for cell in model.cells:
        if cell.material in materials:
            selected.add(cell.id)
            reasons.setdefault(cell.id, []).append(f"material:{cell.material}")
    if config.get("inactive_z_min") is not None:
        threshold = float(config["inactive_z_min"])
        for cell in model.cells:
            if float(cell.centroid[2]) >= threshold:
                selected.add(cell.id)
                reasons.setdefault(cell.id, []).append(f"z>={threshold:g}")
    if bool(config.get("inactive_top", False)):
        axis = int(config.get("vertical_axis", 2))
        values = model.points[:, axis]
        maximum = float(np.max(values))
        tolerance = float(config.get("boundary_coordinate_tolerance", max(np.ptp(values), 1.0) * 1.0e-8))
        for boundary in model.boundaries:
            face = model.faces[boundary.face]
            face_values = model.points[np.asarray(face.nodes, dtype=int), axis]
            if np.all(np.abs(face_values - maximum) <= tolerance):
                selected.add(boundary.cell)
                reasons.setdefault(boundary.cell, []).append("exposed_top")
    invalid = sorted(value for value in selected if value < 0 or value >= len(model.cells))
    if invalid:
        raise ValueError(f"Inactive cell IDs are outside the model: {invalid[:10]}")
    return selected, reasons


def _cell_ahtx(model: FVModel, config: dict[str, Any]) -> np.ndarray:
    settings = dict(config.get("ahtx", {}))
    mode = str(settings.get("mode", "none")).lower()
    values = np.zeros(len(model.cells), dtype=float)
    overrides = settings.get("material_overrides", {})
    if mode not in {"none", "extrusion", "lateral", "all"}:
        raise ValueError("AHTX mode must be none, extrusion, lateral, or all.")
    if mode != "none":
        heat_axis = int(settings.get("heat_axis", 1))
        vertical_axis = int(settings.get("vertical_axis", 2))
        normal_tolerance = float(settings.get("normal_tolerance", 0.95))
        coordinates = model.points[:, vertical_axis]
        minimum, maximum = float(np.min(coordinates)), float(np.max(coordinates))
        coordinate_tolerance = float(
            settings.get("coordinate_tolerance", max(maximum - minimum, 1.0) * 1.0e-8)
        )
        for boundary in model.boundaries:
            face = model.faces[boundary.face]
            include = True
            if mode == "extrusion":
                include = abs(float(face.normal[heat_axis])) >= normal_tolerance
            elif mode == "lateral":
                face_values = model.points[np.asarray(face.nodes, dtype=int), vertical_axis]
                horizontal = abs(float(face.normal[vertical_axis])) >= normal_tolerance
                at_extreme = bool(
                    np.all(np.abs(face_values - minimum) <= coordinate_tolerance)
                    or np.all(np.abs(face_values - maximum) <= coordinate_tolerance)
                )
                include = not (horizontal and at_extreme)
            if include:
                values[boundary.cell] += _effective_interface(model, face.measure)
    for cell in model.cells:
        if cell.material in overrides:
            values[cell.id] = float(overrides[cell.material])
    return values


def _ahtx_field(value: float) -> str:
    return " " * 10 if abs(value) == 0.0 else _float_field(value)


@dataclass(slots=True)
class ExportCell:
    label: str
    material: str
    material_key: str
    volume: float
    ahtx: float
    centroid: np.ndarray
    model_cell: int | None
    inactive: bool = False
    primary: list[float] | None = None


@dataclass(slots=True)
class ExportConnection:
    label1: str
    label2: str
    d1: float
    d2: float
    area: float
    gravity: float
    model_connection: int | None


@dataclass(slots=True)
class ResultStep:
    time_seconds: float
    time_days: float
    elements: dict[str, list[float]] = field(default_factory=dict)
    connections: dict[tuple[str, str], list[float]] = field(default_factory=dict)
    element_headers: list[str] = field(default_factory=list)
    connection_headers: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ResultDataset:
    steps: list[ResultStep]
    label_to_cell: dict[str, int]


def _prepare_export(model: FVModel, config: dict[str, Any]):
    labels = labels_for_model(model)
    used_materials: set[str] = set()
    material_map = {
        material: _material_name(material, used_materials)
        for material in dict.fromkeys(cell.material for cell in model.cells)
    }
    inactive, inactive_reasons = _inactive_cells(model, config)
    ahtx = _cell_ahtx(model, config)
    volume_overrides = {
        str(name): float(value) for name, value in config.get("volume_overrides", {}).items()
    }
    infinite_volume = float(config.get("infinite_volume", 1.0e50))
    cells = []
    for cell in model.cells:
        volume = volume_overrides.get(cell.material, _effective_measure(model, cell.measure))
        if cell.id in inactive:
            volume = infinite_volume
        cells.append(
            ExportCell(
                label=labels[cell.id],
                material=material_map[cell.material],
                material_key=cell.material,
                volume=volume,
                ahtx=float(ahtx[cell.id]),
                centroid=cell.centroid.copy(),
                model_cell=cell.id,
                inactive=cell.id in inactive,
            )
        )
    connections = [
        ExportConnection(
            label1=labels[item.cell1],
            label2=labels[item.cell2],
            d1=item.d1,
            d2=item.d2,
            area=_effective_interface(model, item.interface_measure),
            gravity=item.gravity_projection,
            model_connection=item.id,
        )
        for item in model.connections
    ]
    boundary_generators: list[dict[str, Any]] = []
    boundary_mode = config.get("boundary_mode", "auto")
    if boundary_mode not in {"auto", "prebuilt"}:
        raise ValueError("boundary_mode must be 'auto' or 'prebuilt'.")
    boundary_config = config.get("boundaries", {})
    if boundary_mode == "auto":
        ghost_index = 0
        for boundary in model.boundaries:
            rule = boundary_config.get(boundary.name, {"kind": "no_flow"})
            kind = rule.get("kind", "no_flow")
            if kind in {"no_flow", "none", "unassigned"}:
                continue
            face = model.faces[boundary.face]
            owner = model.cells[boundary.cell]
            if kind in {"state", "pressure", "dirichlet"}:
                ghost_label = _label(max(labels, default=-1) + 1 + ghost_index)
                ghost_index += 1
                ghost_center = 2.0 * face.centroid - owner.centroid
                ghost_material = str(rule.get("material", owner.material))
                if ghost_material not in material_map:
                    material_map[ghost_material] = _material_name(ghost_material, used_materials)
                cells.append(
                    ExportCell(
                        label=ghost_label,
                        material=material_map[ghost_material],
                        material_key=ghost_material,
                        volume=float(rule.get("volume", 1.0e50)),
                        ahtx=float(rule.get("ahtx", 0.0)),
                        centroid=ghost_center,
                        model_cell=None,
                        inactive=True,
                        primary=[float(v) for v in rule.get("primary", [])] or None,
                    )
                )
                d1 = abs(float(np.dot(face.centroid - owner.centroid, face.normal)))
                d2 = abs(float(np.dot(ghost_center - face.centroid, face.normal)))
                connections.append(
                    ExportConnection(
                        labels[owner.id],
                        ghost_label,
                        d1,
                        d2,
                        _effective_interface(model, face.measure),
                        float(np.dot((ghost_center - owner.centroid) / np.linalg.norm(ghost_center - owner.centroid), np.asarray(model.options.gravity) / max(np.linalg.norm(model.options.gravity), 1e-30))),
                        None,
                    )
                )
            elif kind in {"flux", "neumann"}:
                flux = float(rule.get("value", 0.0))
                boundary_generators.append(
                    {
                        "element": labels[owner.id],
                        "name": str(rule.get("name", boundary.name))[:5],
                        "rate": flux * _effective_interface(model, face.measure),
                        "enthalpy": float(rule.get("enthalpy", 0.0)),
                        "type": str(rule.get("type", "COM3"))[:5],
                    }
                )
            else:
                raise ValueError(f"Unknown boundary kind {kind!r} for group {boundary.name!r}.")
    source_config = config.get("sources", {})
    for source in model.sources:
        rule = source_config.get(source.name, {})
        rate = rule.get("rate", source.rate)
        if rate is None:
            continue
        boundary_generators.append(
            {
                "element": labels[source.cell],
                "name": str(rule.get("name", source.name))[:5],
                "rate": float(rate),
                "enthalpy": float(rule.get("enthalpy", 0.0)),
                "type": str(rule.get("type", "COM3"))[:5],
            }
        )
    return cells, connections, labels, material_map, boundary_generators, inactive_reasons


def _write_mesh(path: Path, cells: list[ExportCell], connections: list[ExportConnection]) -> None:
    with path.open("w", encoding="ascii", newline="\n") as stream:
        stream.write(f"ELEME{HEADER}\n")
        for cell in cells:
            line = (
                f"{cell.label:<5}{'':10}{cell.material[:5]:<5}"
                f"{_float_field(cell.volume)}{_ahtx_field(cell.ahtx)}{'':10}"
                f"{_float_field(cell.centroid[0])}"
                f"{_float_field(cell.centroid[1])}"
                f"{_float_field(cell.centroid[2])}"
            )
            stream.write(line[:80].ljust(80) + "\n")
        stream.write("\n")
        stream.write(f"CONNE{HEADER}\n")
        for connection in connections:
            line = (
                f"{connection.label1:<5}{connection.label2:<5}{'':15}{1:5d}"
                f"{_float_field(connection.d1)}{_float_field(connection.d2)}"
                f"{_float_field(connection.area)}{_float_field(connection.gravity)}"
            )
            stream.write(line[:80].ljust(80) + "\n")
        stream.write("\n")


def _initial_primary(cell: ExportCell, config: dict[str, Any]) -> list[float]:
    initial = config.get("initial_conditions", {})
    if cell.primary:
        return cell.primary
    by_material = initial.get("by_material", {})
    material_key = cell.material.strip()
    values = by_material.get(
        cell.material_key,
        by_material.get(material_key, initial.get("default", [101325.0, 0.0, 0.0, 20.0])),
    )
    values = [float(value) for value in values]
    profile = initial.get("depth_profile")
    if profile and len(values) >= 4:
        z_reference = float(profile.get("z_reference", 0.0))
        depth = z_reference - float(cell.centroid[2])
        values[0] += float(profile.get("pressure_gradient", 0.0)) * depth
        values[3] += float(profile.get("temperature_gradient", 0.0)) * depth
    return values


def _write_incon(path: Path, cells: list[ExportCell], config: dict[str, Any]) -> None:
    with path.open("w", encoding="ascii", newline="\n") as stream:
        stream.write(f"INCON{HEADER}\n")
        for cell in cells:
            values = _initial_primary(cell, config)
            stream.write(f"{cell.label:<5}\n")
            stream.write("".join(_float_field(value, 20, 13) for value in values) + "\n")
        stream.write("\n")


def _default_rock(name: str) -> dict[str, Any]:
    return {
        "name": name,
        "nad": 2,
        "density": 2600.0,
        "porosity": 0.2,
        "permeability": [1.0e-15, 1.0e-15, 1.0e-15],
        "conductivity": 2.0,
        "specific_heat": 1000.0,
        "compressibility": 0.0,
        "relative_permeability": {"type": 12, "parameters": [0.3, 0.01, 0.01, 3.0]},
        "capillarity": {"type": 8, "parameters": [0.0, 1.84, 3.16, 3.48]},
    }


def _write_flow_input(
    path: Path,
    cells: list[ExportCell],
    material_map: dict[str, str],
    generators: list[dict[str, Any]],
    config: dict[str, Any],
) -> None:
    flow = config.get("flow", {})
    rocks_by_name = {str(item["name"]): item for item in flow.get("rocks", [])}
    rocks = []
    for original, encoded in material_map.items():
        supplied = rocks_by_name.get(original) or rocks_by_name.get(encoded.strip())
        rock = _default_rock(encoded.strip())
        if supplied:
            rock.update(supplied)
            rock["name"] = encoded.strip()
        rocks.append(rock)
    all_generators = list(flow.get("generators", [])) + generators
    label_by_cell = {cell.model_cell: cell.label for cell in cells if cell.model_cell is not None}
    used_generator_labels: set[str] = set()
    for source in config.get("model_sources", []):
        all_generators.append(source)
    with path.open("w", encoding="ascii", newline="\n") as stream:
        # Record 1 is the optional TOUGH2 problem title. Keep it blank and
        # start the first keyword block on the second line.
        stream.write("\n")
        stream.write(f"ROCKS{HEADER}\n")
        for rock in rocks:
            permeability = list(rock.get("permeability", [1e-15] * 3))
            line = (
                f"{str(rock['name'])[:5]:<5}{int(rock.get('nad', 2)):5d}"
                f"{_float_field(rock.get('density', 2600.0))}"
                f"{_float_field(rock.get('porosity', 0.2))}"
                + "".join(_float_field(value) for value in permeability[:3])
                + f"{_float_field(rock.get('conductivity', 2.0))}"
                + f"{_float_field(rock.get('specific_heat', 1000.0))}"
            )
            stream.write(line[:80] + "\n")
            if int(rock.get("nad", 2)) >= 1:
                stream.write(_float_field(rock.get("compressibility", 0.0)) + "\n")
            if int(rock.get("nad", 2)) >= 2:
                rp = rock.get("relative_permeability", {})
                cp = rock.get("capillarity", {})
                stream.write(
                    f"{int(rp.get('type', 12)):5d}{'':5}"
                    + "".join(_float_field(v) for v in rp.get("parameters", []))
                    + "\n"
                )
                stream.write(
                    f"{int(cp.get('type', 8)):5d}{'':5}"
                    + "".join(_float_field(v) for v in cp.get("parameters", []))
                    + "\n"
                )
        stream.write("\n")
        stream.write(f"MULTI{HEADER}\n")
        stream.write("".join(f"{int(value):5d}" for value in flow.get("multi", [3, 4, 4, 6])) + "\n")
        stream.write(f"SELEC{HEADER}\n")
        selec = flow.get("selec", {})
        integers = [0] * 16
        integers[0] = int(selec.get("ie1", 1))
        integers[8] = int(selec.get("ie9", 3))
        stream.write("".join(f"{value:5d}" for value in integers) + "\n")
        stream.write("".join(_float_field(v) for v in selec.get("fe", [0.8, 0.8, 1e-3])) + "\n")
        stream.write(f"START{HEADER}\n")
        stream.write("----*----1-MOP: 123456789*123456789*1234----*----5----*----6----*----7----*----8\n")
        stream.write(f"PARAM{HEADER}\n")
        param = flow.get("param", {})
        stream.write(
            f"{int(param.get('mcyc', 29999)):8d}{int(param.get('mcypr', 9999)):8d}"
            f"{str(param.get('mop', '1000300000000'))[:13]:13}{str(param.get('texp', '4')):>3}"
            f"{str(param.get('be', '3')):>5} \n"
        )
        stream.write(
            f"{str(param.get('tstart', '0.')):>10}{str(param.get('timax', '4.32E5')):>10}"
            f"{str(param.get('delten', '-1.')):>10}{str(param.get('deltmx', '')):>10}"
            f"{'':10}{float(param.get('gravity', 9.81)):10.2f}\n"
        )
        stream.write(f"{str(param.get('re1', '1.')):>10}\n")
        stream.write(f"{str(param.get('re2', '1.E-3')):>10}{str(param.get('dlt', '1.E0')):>10}\n")
        default_primary = config.get("initial_conditions", {}).get(
            "default", [101325.0, 0.0, 0.0, 20.0]
        )
        stream.write("".join(_float_field(v, 20, 13) for v in default_primary) + "\n")
        times = flow.get("times", [])
        if times:
            stream.write(f"TIMES{HEADER}\n{len(times):5d}\n")
            for index in range(0, len(times), 8):
                stream.write("".join(_float_field(v) for v in times[index : index + 8]) + "\n")
        model_source_generators = config.get("source_generators", [])
        if all_generators or model_source_generators:
            all_generators.extend(model_source_generators)
            stream.write(f"GENER{HEADER}\n")
            for index, generator in enumerate(all_generators):
                element = generator.get("element")
                if element is None and "cell" in generator:
                    element = label_by_cell[int(generator["cell"])]
                if element is None:
                    continue
                element = str(element)
                if not _is_a3_i2(element):
                    raise ValueError(
                        f"GENER element name {element!r} is not a five-character A3,I2 label."
                    )
                name = _generator_label(generator.get("name", "GEN"), index, used_generator_labels)
                kind = str(generator.get("type", "COM3"))[:5]
                rate = float(generator.get("rate", 0.0))
                enthalpy = float(generator.get("enthalpy", 0.0))
                stream.write(f"{element:<5}{name:<5}{'':20}{1:5d}{kind:>5}\n")
                stream.write(f"{_float_field(rate, 20, 13)}{_float_field(enthalpy, 20, 13)}\n")
            stream.write("\n")
        stream.write(f"OUTPU{HEADER}\n")
        output = flow.get("output", ["SATURATION              1", "COORDINATE"])
        stream.write(f"{len(output)}\n")
        for line in output:
            stream.write(str(line).rstrip() + "\n")
        stream.write("\n")
        stream.write(f"ENDCY{HEADER}\n")


def validate_eco2m(
    model: FVModel,
    config: dict[str, Any] | str | Path,
) -> list[str]:
    """Return blocking validation messages without writing solver files."""
    errors = [issue.message for issue in validate_model(model).errors]
    if model.dimension != 3:
        errors.append("TOUGH2/ECO2M export requires a three-dimensional FV dataset.")
    try:
        parsed = _config(config)
        _inactive_cells(model, parsed)
        _cell_ahtx(model, parsed)
        if float(parsed.get("infinite_volume", 1.0e50)) <= 0.0:
            errors.append("The TOUGH infinite volume must be positive.")
    except (TypeError, ValueError, KeyError) as error:
        errors.append(str(error))
    return list(dict.fromkeys(errors))


def preview_eco2m(model: FVModel, config: dict[str, Any] | str | Path) -> dict[str, Any]:
    parsed = _config(config)
    errors = validate_eco2m(model, parsed)
    if errors:
        return {
            "valid": False,
            "errors": errors,
            "inactive_cells": [],
            "inactive_count": 0,
            "ahtx_nonzero_cells": 0,
        }
    cells, _, _, _, _, inactive_reasons = _prepare_export(model, parsed)
    overridden = set(parsed.get("volume_overrides", {}))
    selected = [
        cell
        for cell in cells
        if cell.model_cell is not None and (cell.inactive or cell.material_key in overridden)
    ]
    return {
        "valid": True,
        "errors": [],
        "boundary_cells": [
            {
                "cell_id": cell.model_cell,
                "label": cell.label,
                "material": cell.material_key,
                "centroid": cell.centroid.tolist(),
                "volume": cell.volume,
                "ahtx": cell.ahtx,
                "reasons": [
                    *inactive_reasons.get(int(cell.model_cell), []),
                    *(
                        [f"volume_override:{cell.material_key}"]
                        if cell.material_key in overridden
                        else []
                    ),
                ],
            }
            for cell in selected
        ],
        "boundary_count": len(selected),
        "inactive_cells": [
            item
            for item in (
                {
                    "cell_id": cell.model_cell,
                    "label": cell.label,
                    "material": cell.material_key,
                    "centroid": cell.centroid.tolist(),
                    "volume": cell.volume,
                    "ahtx": cell.ahtx,
                    "reasons": inactive_reasons.get(int(cell.model_cell), []),
                }
                for cell in selected
                if cell.inactive
            )
        ],
        "inactive_count": sum(cell.inactive for cell in selected),
        "ahtx_nonzero_cells": sum(abs(cell.ahtx) > 0.0 for cell in cells),
    }


def _write_cell_map(path: Path, cells: list[ExportCell]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["cell_id", "tough_label", "material", "tough_material", "generated"])
        for cell in cells:
            writer.writerow(
                [
                    "" if cell.model_cell is None else cell.model_cell,
                    cell.label,
                    cell.material_key,
                    cell.material.strip(),
                    cell.model_cell is None,
                ]
            )


def _export_manifest(
    cells: list[ExportCell],
    connections: list[ExportConnection],
    labels: dict[int, str],
    material_map: dict[str, str],
    inactive_reasons: dict[int, list[str]],
    config: dict[str, Any],
) -> dict[str, Any]:
    overridden = set(config.get("volume_overrides", {}))
    boundary_cells = [
        cell
        for cell in cells
        if cell.model_cell is not None and (cell.inactive or cell.material_key in overridden)
    ]
    return {
        "backend": "TOUGH2/ECO2M",
        "cell_label_format": "TOUGH A3,I2",
        "cells": len(cells),
        "connections": len(connections),
        "cell_labels": {str(cell): label for cell, label in labels.items()},
        "generated_boundary_cells": [
            {
                "label": cell.label,
                "material": cell.material_key,
                "centroid": cell.centroid.tolist(),
                "inactive": cell.inactive,
            }
            for cell in cells
            if cell.model_cell is None
        ],
        "inactive_cells": [
            {
                "cell_id": cell.model_cell,
                "label": cell.label,
                "material": cell.material_key,
                "volume": cell.volume,
                "ahtx": cell.ahtx,
                "reasons": inactive_reasons.get(int(cell.model_cell), []),
            }
            for cell in cells
            if cell.model_cell is not None and cell.inactive
        ],
        "boundary_cells": [
            {
                "cell_id": cell.model_cell,
                "label": cell.label,
                "material": cell.material_key,
                "volume": cell.volume,
                "ahtx": cell.ahtx,
                "reasons": [
                    *inactive_reasons.get(int(cell.model_cell), []),
                    *(
                        [f"volume_override:{cell.material_key}"]
                        if cell.material_key in overridden
                        else []
                    ),
                ],
            }
            for cell in boundary_cells
        ],
        "materials": {name: encoded.strip() for name, encoded in material_map.items()},
        "boundary_mode": config.get("boundary_mode", "auto"),
    }


def export_eco2m_mesh(
    model: FVModel,
    config: dict[str, Any] | str | Path,
    output_dir: str | Path,
) -> dict[str, Any]:
    """Write only MESH and its mapping/manifest files."""
    config = _config(config)
    errors = validate_eco2m(model, config)
    if errors:
        raise ValueError("TOUGH2/ECO2M export validation failed:\n- " + "\n- ".join(errors))
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    cells, connections, labels, material_map, _, inactive_reasons = _prepare_export(model, config)
    mesh_path = output_dir / "MESH"
    map_path = output_dir / "cell_map.csv"
    manifest_path = output_dir / "mesh_manifest.json"
    _write_mesh(mesh_path, cells, connections)
    _write_cell_map(map_path, cells)
    manifest = _export_manifest(
        cells, connections, labels, material_map, inactive_reasons, config
    )
    manifest["files"] = {
        "mesh": str(mesh_path),
        "cell_map": str(map_path),
        "manifest": str(manifest_path),
    }
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return manifest


def export_eco2m(
    model: FVModel,
    config: dict[str, Any] | str | Path,
    output_dir: str | Path,
) -> dict[str, Any]:
    config = _config(config)
    errors = validate_eco2m(model, config)
    if errors:
        raise ValueError("TOUGH2/ECO2M export validation failed:\n- " + "\n- ".join(errors))
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    cells, connections, labels, material_map, generators, inactive_reasons = _prepare_export(
        model, config
    )
    mesh_path = output_dir / "MESH"
    map_path = output_dir / "cell_map.csv"
    incon_path = output_dir / "INCON"
    flow_path = output_dir / "flow.inp"
    _write_mesh(mesh_path, cells, connections)
    _write_cell_map(map_path, cells)
    _write_incon(incon_path, cells, config)
    _write_flow_input(flow_path, cells, material_map, generators, config)
    manifest = _export_manifest(
        cells, connections, labels, material_map, inactive_reasons, config
    )
    manifest["files"] = {
        "mesh": str(mesh_path),
        "cell_map": str(map_path),
        "incon": str(incon_path),
        "flow_input": str(flow_path),
    }
    (output_dir / "export_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return manifest


def _fortran_float(text: str) -> float:
    text = text.strip().replace("D", "E").replace("d", "E")
    if "E" not in text.upper():
        match = re.match(r"^(.+?)([+-]\d+)$", text)
        if match:
            text = f"{match.group(1)}E{match.group(2)}"
    return float(text)


def _numeric_tokens(tokens: list[str]) -> list[float]:
    result = []
    for token in tokens:
        try:
            result.append(_fortran_float(token))
        except ValueError:
            continue
    return result


def read_flow_output(path: str | Path, model: FVModel) -> ResultDataset:
    path = Path(path)
    label_to_cell = {_label(cell.id): cell.id for cell in model.cells}
    known = set(label_to_cell)
    time_pattern = re.compile(
        r"OUTPUT DATA AFTER.*THE TIME IS\s+([\d.EeDd+\-]+)\s+DAYS", re.IGNORECASE
    )
    steps: list[ResultStep] = []
    current: ResultStep | None = None
    mode: str | None = None
    with path.open("r", encoding="latin-1", errors="replace") as stream:
        for raw in stream:
            match = time_pattern.search(raw)
            if match:
                days = _fortran_float(match.group(1))
                current = ResultStep(days * 86400.0, days)
                steps.append(current)
                mode = None
                continue
            if current is None:
                continue
            upper = raw.upper()
            if "ELEM." in upper and "INDEX" in upper:
                current.element_headers = raw.split()[2:]
                mode = "element"
                continue
            if "ELEM1" in upper and "ELEM2" in upper:
                current.connection_headers = raw.split()[2:]
                mode = "connection"
                continue
            raw = raw.replace("\f", "")
            stripped = raw.strip()
            if not stripped:
                continue
            labels_in_line: list[tuple[int, str]] = []
            for position in range(max(len(raw) - 4, 0)):
                candidate = raw[position : position + 5]
                if candidate in known and (
                    not labels_in_line or position >= labels_in_line[-1][0] + 5
                ):
                    labels_in_line.append((position, candidate))
            if mode == "connection" and len(labels_in_line) >= 2:
                values = _numeric_tokens(raw[labels_in_line[1][0] + 5 :].split())
                current.connections[(labels_in_line[0][1], labels_in_line[1][1])] = values
            elif labels_in_line:
                position, label = labels_in_line[0]
                values = _numeric_tokens(raw[position + 5 :].split())
                if values:
                    current.elements[label] = values
    return ResultDataset(steps, label_to_cell)


def write_results_csv(results: ResultDataset, output_dir: str | Path) -> list[Path]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for index, step in enumerate(results.steps):
        path = output_dir / f"elements_{index:04d}.csv"
        width = max((len(values) for values in step.elements.values()), default=0)
        headers = step.element_headers[:width] or [f"value_{i + 1}" for i in range(width)]
        with path.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.writer(stream)
            writer.writerow(["time_seconds", "label", "cell_id", *headers])
            for label, values in step.elements.items():
                writer.writerow([step.time_seconds, label, results.label_to_cell.get(label), *values])
        paths.append(path)
    return paths


def write_results_vtu(
    results: ResultDataset, model: FVModel, output_dir: str | Path
) -> list[Path]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    type_order = list(dict.fromkeys(cell.cell_type for cell in model.cells))
    blocks = []
    block_cells: list[list[int]] = []
    for cell_type in type_order:
        ids = [cell.id for cell in model.cells if cell.cell_type == cell_type]
        block_cells.append(ids)
        blocks.append((cell_type, np.asarray([model.cells[i].nodes for i in ids], dtype=int)))
    paths = []
    for step_index, step in enumerate(results.steps):
        width = max((len(values) for values in step.elements.values()), default=0)
        headers = step.element_headers[:width] or [f"value_{i + 1}" for i in range(width)]
        fields = np.full((len(model.cells), width), np.nan)
        for label, values in step.elements.items():
            cell_id = results.label_to_cell.get(label)
            if cell_id is not None:
                fields[cell_id, : len(values)] = values
        cell_data = {
            header: [fields[np.asarray(ids), column] for ids in block_cells]
            for column, header in enumerate(headers)
        }
        path = output_dir / f"results_{step_index:04d}.vtu"
        meshio.write(path, meshio.Mesh(model.points, blocks, cell_data=cell_data))
        paths.append(path)
    return paths
