# -*- coding: utf-8 -*-
"TOUGH output parsing and Tecplot export."

import os
import re
import time as time_module

from ..i18n import tr

# ============================================================


# ============================================================
def parse_mesh_coords(mesh_path):
    "Parse element coordinates from a TOUGH MESH file."
    coords = {}
    elem_order = []
    in_eleme = False

    with open(mesh_path, "r", encoding="latin-1") as f:
        for line in f:
            stripped = line.strip()

            if stripped.startswith("ELEME"):
                in_eleme = True
                continue

            if in_eleme and len(stripped) >= 5:
                if (
                    stripped.startswith("CONNE")
                    or stripped.startswith("GENER")
                    or stripped.startswith("INCON")
                ):
                    break

            if not in_eleme:
                continue
            if len(stripped) == 0:
                continue
            if len(line) < 70:
                continue

            elem_name = line[0:5].strip()
            if not elem_name:
                continue

            try:
                x = float(line[50:60].strip())
                y_str = line[60:70].strip() if len(line) >= 70 else ""
                z_str = line[70:80].strip() if len(line) >= 80 else ""

                def _fix_mesh_float(s):
                    if not s:
                        return 0.0
                    s = s.upper()
                    if "E" not in s:
                        for sign in ("+", "-"):
                            idx = s.rfind(sign)
                            if idx > 0 and s[idx - 1].isdigit():
                                return float(s[:idx] + "E" + s[idx:])
                    return float(s)

                y = _fix_mesh_float(y_str) if y_str else 0.0
                z = _fix_mesh_float(z_str) if z_str else 0.0

                coords[elem_name] = (x, y, z)
                elem_order.append(elem_name)
            except (ValueError, IndexError):
                continue

    print(tr("status.out.mesh_coordinates_parsed", count=len(coords)))
    return coords, elem_order


# ============================================================


# ============================================================
def parse_flow_out(flow_out_path, known_elements, progress_callback=None):
    "Parse supported time-step data from a TOUGH output file."
    time_steps = []

    time_pattern = re.compile(
        r"OUTPUT DATA AFTER.*THE TIME IS\s+([\d.E+\-]+)\s+DAYS", re.IGNORECASE
    )

    file_size = os.path.getsize(flow_out_path)
    print(f"{tr('status.out.reading_flow_out')} {flow_out_path}")
    print(f"  {tr('status.out.file_size')} {file_size / 1024 / 1024:.1f} MB")

    start_time = time_module.time()

    time_markers = []
    total_lines = 0
    with open(flow_out_path, "r", encoding="latin-1") as f:
        for i, line in enumerate(f):
            total_lines = i + 1
            match = time_pattern.search(line)
            if match:
                td = float(match.group(1))
                ts = td * 86400.0
                time_markers.append((i, td, ts))

    print(f"  {tr('status.out.time_steps_found', count=len(time_markers))}")
    if progress_callback:
        progress_callback(5, tr("status.out.time_steps_found", count=len(time_markers)))

    if len(time_markers) == 0:
        return []

    current_marker_idx = 0
    current_data = None
    current_ts = None
    current_td = None
    collecting = False

    with open(flow_out_path, "r", encoding="latin-1") as f:
        for i, line in enumerate(f):
            if progress_callback and i % 50000 == 0:
                pct = 5 + int(85 * i / max(total_lines, 1))
                elapsed = time_module.time() - start_time
                progress_callback(
                    min(pct, 90), f"{tr('status.out.parsing')} {i}/{total_lines} ({elapsed:.1f}s)"
                )

            if current_marker_idx < len(time_markers) and i == time_markers[current_marker_idx][0]:
                if current_data is not None and len(current_data) > 0:
                    time_steps.append((current_ts, current_td, current_data))

                _, current_td, current_ts = time_markers[current_marker_idx]
                current_data = {}
                collecting = True
                current_marker_idx += 1
                continue

            if not collecting:
                continue

            raw = line.rstrip("\r\n")
            clean = raw.replace("\f", "").strip()
            if not clean:
                continue
            if clean.startswith("@@@"):
                continue
            if "ELEM." in clean and "INDEX" in clean:
                continue
            if "(PA)" in clean.upper() and "(DEG.C)" in clean.upper():
                continue
            if "TOTAL TIME" in clean:
                continue
            if "DX1M" in clean or "DX2M" in clean:
                continue

            if len(raw) < 10:
                continue

            candidate_elem = raw[1:6].strip() if len(raw) > 5 else ""

            if candidate_elem and candidate_elem in known_elements:
                remainder = raw[6:].split()
                try:
                    if len(remainder) < 2 or not remainder[0].lstrip("-").isdigit():
                        continue

                    if len(remainder) >= 11:

                        def _fix_fortran_float(s):
                            s = s.upper()
                            if "E" not in s:
                                for sign in ("+", "-"):
                                    idx = s.rfind(sign)
                                    if idx > 0 and s[idx - 1].isdigit():
                                        return s[:idx] + "E" + s[idx:]
                            return s

                        p_str = _fix_fortran_float(remainder[1][1:])
                        p_value = float(p_str)
                        other_values = [
                            float(_fix_fortran_float(remainder[2 + j])) for j in range(9)
                        ]
                        values = [p_value] + other_values
                        current_data[candidate_elem] = values
                except (ValueError, IndexError):
                    pass

    if current_data is not None and len(current_data) > 0:
        time_steps.append((current_ts, current_td, current_data))

    elapsed = time_module.time() - start_time
    print(f"  {tr('status.out.parsing_complete', count=len(time_steps), elapsed=elapsed)}")

    if progress_callback:
        progress_callback(
            90,
            tr("status.out.parsing_complete", count=len(time_steps), elapsed=elapsed),
        )

    return time_steps


# ============================================================

# ============================================================
EXCLUDED_ELEMS = {"INC 1", "INC 2"}


def write_tecplot(time_steps, coords, elem_order, output_dir, progress_callback=None):
    "Write parsed TOUGH results in Tecplot ASCII format."
    os.makedirs(output_dir, exist_ok=True)

    variables = [
        "X",
        "Y",
        "Z",
        "P",
        "T",
        "SAQ",
        "SLIQ",
        "SGAS",
        "XCO2AQ",
        "DLIQ",
        "VISLIQ",
        "DGAS",
        "VISGAS",
    ]
    var_line = " ".join([f'"{v}"' for v in variables])

    output_files = []
    n_steps = len(time_steps)

    for ts_idx, (time_s, time_d, data) in enumerate(time_steps):
        time_label = f"{time_s:.0f}" if time_s >= 1.0 else f"{time_s:.6f}"
        filename = f"flow_time_{time_label}s.dat"
        filepath = os.path.join(output_dir, filename)

        writable_elems = [e for e in elem_order if e in data and e not in EXCLUDED_ELEMS]
        writable_elems.sort(key=lambda e: (coords[e][0], coords[e][2]))

        if len(writable_elems) == 0:
            continue

        with open(filepath, "w") as f:
            f.write(f'TITLE = "ECO2M Simulation - Time={time_s:.1f}s ({time_d:.5f} days)"\n')
            f.write(f"VARIABLES = {var_line}\n")
            f.write(f'ZONE T="Time={time_s:.1f}s", I={len(writable_elems)}, F=POINT\n')

            for elem in writable_elems:
                x, y, z = coords[elem]
                vals = data[elem]
                line_data = [x, y, z] + vals
                f.write(" ".join([f"{v:15.7E}" for v in line_data]) + "\n")

        output_files.append(filepath)
        print(
            f"  [{ts_idx + 1}/{n_steps}] {filename} ({len(writable_elems)} {tr('common.cells.unit')})"
        )

        if progress_callback:
            pct = 90 + int(10 * (ts_idx + 1) / n_steps)
            progress_callback(min(pct, 99), f"{tr('status.out.writing')} {filename}")

    merged_filepath = os.path.join(output_dir, "flow_all_times.dat")
    with open(merged_filepath, "w") as f:
        f.write('TITLE = "ECO2M Simulation - All Time Steps"\n')
        f.write(f"VARIABLES = {var_line}\n")

        for ts_idx, (time_s, time_d, data) in enumerate(time_steps):
            writable_elems = [e for e in elem_order if e in data and e not in EXCLUDED_ELEMS]
            writable_elems.sort(key=lambda e: (coords[e][0], coords[e][2]))
            if len(writable_elems) == 0:
                continue

            f.write(
                f'ZONE T="Time={time_s:.1f}s ({time_d:.5f}d)", I={len(writable_elems)}, F=POINT\n'
            )
            for elem in writable_elems:
                x, y, z = coords[elem]
                vals = data[elem]
                line_data = [x, y, z] + vals
                f.write(" ".join([f"{v:15.7E}" for v in line_data]) + "\n")

    output_files.append(merged_filepath)
    print(f"  {tr('status.out.merged_file')} flow_all_times.dat")

    if progress_callback:
        progress_callback(100, tr("common.extraction_complete"))

    return output_files
