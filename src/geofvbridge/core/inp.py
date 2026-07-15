# -*- coding: utf-8 -*-
"Fixed-width TOUGH2/ECO2M input-file generation."

import os

from ..i18n import tr


def _to_float(val):
    "To float."
    if isinstance(val, (int, float)):
        return float(val)
    val = str(val).strip()
    if not val:
        return 0.0
    return float(val)


def _clean_sci(s):
    "Clean sci."
    if "E" not in s:
        return s
    mantissa, exp_str = s.split("E")

    if "." in mantissa:
        mantissa = mantissa.rstrip("0")
        if mantissa.endswith("."):
            mantissa += "0"

    exp_val = int(exp_str)
    if exp_val >= 0:
        new_exp = f"+{exp_val}"
    else:
        new_exp = str(exp_val)
    return f"{mantissa}E{new_exp}"


def _clean_float(s):
    "Clean float."
    if "." not in s:
        return s + ".0"
    s = s.rstrip("0")
    if s.endswith("."):
        s += "0"
    return s


def _tough_fmt(val, width=10):
    "Format a value for a fixed-width TOUGH field."
    val = _to_float(val)

    if val == 0.0:
        return f"{'0.0':>{width}}"

    abs_val = abs(val)

    if abs_val < 0.001 or abs_val >= 1e6:
        for decimals in range(6, 0, -1):
            s = _clean_sci(f"{val:.{decimals}E}")
            if len(s) <= width:
                return f"{s:>{width}}"
        s = _clean_sci(f"{val:.1E}")
        return f"{s:>{width}}"

    for decimals in range(6, 0, -1):
        s = _clean_float(f"{val:.{decimals}f}")
        if len(s) <= width:
            return f"{s:>{width}}"

    s = _clean_sci(f"{val:.2E}")
    return f"{s:>{width}}"


def _tough_fmt_rp(val, width=10):
    "Format a relative-permeability or capillary-pressure parameter."
    val = _to_float(val)

    if val == 0.0:
        return f"{'0.000':>{width}}"

    for decimals in range(3, -1, -1):
        s = f"{val:.{decimals}f}"
        if len(s) <= width:
            return f"{s:>{width}}"

    s = _clean_sci(f"{val:.2E}")
    return f"{s:>{width}}"


def write_flow_inp(
    filepath,
    rocks_data,
    param_data,
    times_data,
    gener_data,
    multi_data,
    selec_data,
    outpu_data=None,
):
    "Write a fixed-width TOUGH2/ECO2M flow input file."

    ref_path = os.path.join(os.path.dirname(filepath), "flow_reference.inp")

    with open(filepath, "w", encoding="utf-8") as f:
        # TOUGH2 reads the first record as the problem title. GeoFVBridge
        # leaves that title blank, so the ROCKS block must begin on line 2.
        f.write("\n")

        # ===== ROCKS =====

        f.write(
            "ROCKS----1----*----2----*----3----*----4----*----5----*----6----*----7----*----8\n"
        )
        for r in rocks_data:
            nad_val = int(r["nadm"])
            name = f"{r['name']:<5s}"[:5]
            nadm = f"{nad_val:>5d}"
            density = _tough_fmt(r["density"])
            porosity = _tough_fmt(r["porosity"])
            px = _tough_fmt(r["perm_x"])
            py = _tough_fmt(r["perm_y"])
            pz = _tough_fmt(r["perm_z"])
            cond = _tough_fmt(r["conductivity"])
            cp = _tough_fmt(r["specific_heat"])
            line1 = f"{name}{nadm}{density}{porosity}{px}{py}{pz}{cond}{cp}\n"
            if len(line1) > 81:
                raise ValueError(
                    tr(
                        "error.inp.rocks_line_too_long",
                        length=len(line1) - 1,
                        line=line1,
                    )
                )
            f.write(line1)

            if nad_val >= 1:
                comp = _tough_fmt(r["compressibility"])
                f.write(f"{comp}\n")

            if nad_val >= 2:
                irp = f"{r['irp']:>5d}"
                rp = "".join(_tough_fmt_rp(p) for p in r["rp_params"])
                f.write(f"{irp}     {rp}\n")

                icp = f"{r['icp']:>5d}"
                cpp = "".join(_tough_fmt_rp(p) for p in r["cp_params"])
                f.write(f"{icp}     {cpp}\n")

        f.write("\n")

        # ===== MULTI =====
        f.write(
            "MULTI----1----*----2----*----3----*----4----*----5----*----6----*----7----*----8\n"
        )
        multi_str = "".join(f"{v:>5d}" for v in multi_data)
        f.write(f"{multi_str}\n")

        # ===== SELEC =====
        f.write(
            "SELEC....2....3....4....5....6....7....8....9...10...11...12...13...14...15...16\n"
        )
        # Record 1: IE(1)~IE(16), Format(16I5)
        ie = [0] * 16
        ie[0] = int(selec_data.get("ie1", 1))
        ie[6] = int(selec_data.get("ie7", 0))
        ie[7] = int(selec_data.get("ie8", 0))
        ie[8] = int(selec_data.get("ie9", 3))
        ie[9] = int(selec_data.get("ie10", 0))
        ie[10] = int(selec_data.get("ie11", 0))
        ie[11] = int(selec_data.get("ie12", 0))
        ie[12] = int(selec_data.get("ie13", 0))
        ie[13] = int(selec_data.get("ie14", 0))
        ie[14] = int(selec_data.get("ie15", 0))
        ie_str = "".join(f"{v:>5d}" for v in ie)
        f.write(f"{ie_str}\n")
        # Record 2: FE(1)~FE(8), Format(8E10.4)
        if ie[0] >= 1:
            fe_vals = [
                float(selec_data.get("fe1", 0.8)),
                float(selec_data.get("fe2", 0.8)),
                float(selec_data.get("fe3", 1.0e-3)),
                float(selec_data.get("fe4", 0.0)),
            ]

            while fe_vals and fe_vals[-1] == 0.0:
                fe_vals.pop()
            fe_str = "".join(f"{v:>10.4g}" for v in fe_vals)
            f.write(f"{fe_str}\n")

        # ===== START =====
        f.write(
            "START----1----*----2----*----3----*----4----*----5----*----6----*----7----*----8\n"
        )
        f.write(
            "----*----1-MOP: 123456789*123456789*1234----*----5----*----6----*----7----*----8\n"
        )

        # ===== PARAM =====
        f.write(
            "PARAM----1----*----2----*----3----*----4----*----5----*----6----*----7----*----8\n"
        )
        p = param_data

        if "mop_vals" in p:
            mop_values = [int(value) for value in p["mop_vals"][:24]]
            if any(value < 0 or value > 9 for value in mop_values):
                raise ValueError("Each MOP entry must be a single digit from 0 to 9.")
            mop_str = "".join(str(value) for value in mop_values).ljust(24, "0")
        else:
            mop_str = str(p["mop_str"]).ljust(24, "0")[:24]
        f.write(f"{p['mcyc']:>8d}{p['mcypr']:>8d}{mop_str}{p['texp']:>3s}{p['be']:>5s} \n")
        # Record 2: TSTART, TIMAX, DELTEN, DELTMX, (A5), GF, REDLT, SCALE
        tstart = p.get("tstart", "0.").strip()
        timax = p.get("timax", p.get("dt_init", "")).strip()
        delten = p.get("delten", "-1.").strip()
        deltmx = p.get("deltmx", "").strip()
        gravity = float(p["gravity"])
        f.write(f"{tstart:>10s}{timax:>10s}{delten:>10s}{deltmx:>10s}{'':10s}{gravity:10.2f}\n")
        f.write(f"{p['re1'].strip():>10s}\n")
        f.write(f"{p['re2'].strip():>10s}{p['dlt'].strip():>10s}\n")
        ic = p["default_ic"]
        ic_str = "".join(f"{v:>20s}" for v in ic)
        f.write(f"{ic_str}\n")

        # ===== TIMES =====
        if times_data:
            f.write(
                "TIMES----1----*----2----*----3----*----4----*----5----*----6----*----7----*----8\n"
            )
            f.write(f"{len(times_data):>5d}\n")
            for i in range(0, len(times_data), 8):
                chunk = times_data[i : i + 8]

                line = "".join(f"{t:>10.4e}" for t in chunk)
                f.write(f"{line}\n")

        # ===== GENER =====
        if gener_data.strip():
            f.write(
                "GENER----1----*----2----*----3----*----4----*----5----*----6----*----7----*----8\n"
            )
            f.write(gener_data)
            if not gener_data.endswith("\n"):
                f.write("\n")
            f.write("\n")

        # ===== OUTPU =====
        if outpu_data and outpu_data.strip():
            f.write(
                "OUTPU----1----*----2----*----3----*----4----*----5----*----6----*----7----*----8\n"
            )
            f.write(outpu_data)
            if not outpu_data.endswith("\n"):
                f.write("\n")
            f.write("\n")
        else:
            f.write(
                "OUTPU----1----*----2----*----3----*----4----*----5----*----6----*----7----*----8\n"
            )
            f.write("2\n")
            f.write("SATURATION              1\n")
            f.write("COORDINATE\n")
            f.write("\n")

        # ===== ENDCY =====
        f.write(
            "ENDCY----1----*----2----*----3----*----4----*----5----*----6----*----7----*----8\n"
        )

    print(f"{tr('status.inp.exported_flow_inp')} {filepath}")

    if os.path.exists(ref_path):
        _check_format(filepath, ref_path)

    return filepath


def _check_format(generated, reference):
    "Check format."
    print(f"\n--- {tr('status.inp.format_check_vs_flow_reference_inp')} ---")
    with open(generated, "r", encoding="utf-8") as fg, open(reference, "r", encoding="utf-8") as fr:
        gen_lines = fg.readlines()
        _reference_lines = fr.readlines()

    for i, line in enumerate(gen_lines):
        if line.startswith("ROCKS") or line.startswith("PARAM") or line.startswith("MULTI"):
            continue

        stripped = line.rstrip("\n\r")
        if len(stripped) > 80:
            print(
                f"  ⚠ {tr('status.inp.line')}{i + 1}{tr('status.inp.exceeds_80_characters')} ({len(stripped)}): {stripped[:50]}..."
            )

    print(f"  ✓ {tr('status.inp.format_check_complete')}")
    print("---")


def get_default_rock(name):
    "Return default rock."
    return {
        "name": name[:5],
        "nadm": 2,
        "density": 2600.0,
        "porosity": 0.44,
        "perm_x": 4.2e-9,
        "perm_y": 4.2e-9,
        "perm_z": 0.42e-9,
        "conductivity": 2.0,
        "specific_heat": 1000.0,
        "compressibility": 0.0e-10,
        "irp": 12,
        "rp_params": [0.300, 0.01, 0.01, 3.0],
        "icp": 8,
        "cp_params": [0.000, 1.84, 3.16, 3.48],
    }


def get_default_param():
    "Return default param."
    return {
        "mcyc": 29999,
        "mcypr": 9999,
        "mop_str": "1000300000000",
        "texp": "  4",
        "be": "   3",
        "tstart": "0.",
        "timax": "4.3200e5",
        "delten": "      -1.",
        "deltmx": "",
        "gravity": 9.81,
        "re1": "1.",
        "re2": "   1.E-3",
        "dlt": "    1.e00",
        "default_ic": ["1.01325e5", "0.00", "0.00", "20."],
    }


def get_default_times():
    return [
        1.0,
        7.2e3,
        1.44e4,
        1.8e4,
        2.16e4,
        2.88e4,
        3.6e4,
        4.32e4,
        7.2e4,
        8.64e4,
        1.296e5,
        1.44e5,
        1.728e5,
        2.16e5,
        2.592e5,
        2.88e5,
        3.456e5,
        3.6e5,
        4.32e5,
    ]


def get_default_gener():
    "Return default gener."
    return (
        "INC 1inj 1                   4     COM31\n"
        "   0.00000E+00   0.18000E+05   0.18001E+05   0.43200E+06\n"
        "   0.30700E-06   0.30700E-06   0.00000E+00   0.00000E+00\n"
        "   3.50000E+05   3.50000E+05   3.50000E+05   3.50000E+05\n"
        "INC 2inj 2                   6     COM31\n"
        "   0.00000E+00   0.80990E+04   0.81000E+04   0.18000E+05\n"
        "   0.18001E+05   0.43200E+06\n"
        "   0.00000E+00   0.00000E+00   0.30700E-06   0.30700E-06\n"
        "   0.00000E+00   0.00000E+00\n"
        "   3.50000E+05   3.50000E+05   3.50000E+05   3.50000E+05\n"
        "   3.50000E+05   3.50000E+05\n"
    )


def get_default_multi():
    return [3, 4, 4, 6]


def get_default_selec():
    return {
        "ie1": 1,
        "ie7": 0,
        "ie8": 0,
        "ie9": 3,
        "ie10": 0,
        "ie11": 0,
        "ie12": 0,
        "ie13": 0,
        "ie14": 0,
        "ie15": 0,
        "fe1": 0.8,
        "fe2": 0.8,
        "fe3": 1.0e-3,
        "fe4": 0.0,
    }
