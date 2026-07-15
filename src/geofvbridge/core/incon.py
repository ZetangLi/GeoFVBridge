# -*- coding: utf-8 -*-
"Initial-condition generation for TOUGH simulations."

import numpy as np

from ..i18n import tr


def compute_initial_conditions(
    centers, z_top, z_bot, p_top, p_bot, t_top, t_bot, sg_default=0.0, xco2_default=0.0
):
    "Compute depth-dependent pressure and temperature initial conditions."
    n = len(centers)
    z = centers[:, 2]

    dz = z_top - z_bot
    if abs(dz) < 1e-10:
        dz = 1.0

    p_gradient = (p_bot - p_top) / dz
    t_gradient = (t_bot - t_top) / dz  # °C/m

    pressure = p_top + p_gradient * (z_top - z)
    temperature = t_top + t_gradient * (z_top - z)

    incon = np.zeros((n, 4))
    incon[:, 0] = pressure
    incon[:, 1] = sg_default
    incon[:, 2] = xco2_default
    incon[:, 3] = temperature

    return incon


def write_incon(filepath, labels, materials, incon_data, material_states, material_porosities):
    "Write a fixed-width TOUGH INCON file."
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(
            "INCON----1----*----2----*----3----*----4----*----5----*----6----*----7----*----8\n"
        )

        for i, label in enumerate(labels):
            mat = str(materials[i])

            state = material_states.get(mat, 0)
            poro = material_porosities.get(mat, 0.0)

            elem_name = f"{label:5s}"

            if state > 0 and poro > 0:
                line1 = f"{elem_name}{'':10s}{state:1d}{'':4s}{poro:15.9E}\n"
            elif state > 0:
                line1 = f"{elem_name}{'':10s}{state:1d}\n"
            elif poro > 0:
                line1 = f"{elem_name}{'':15s}{poro:15.9E}\n"
            else:
                line1 = f"{elem_name}\n"

            p, sg, xco2, t = incon_data[i]
            line2 = f"{p:20.13E}{sg:20.13E}{xco2:20.13E}{t:20.13E}\n"

            f.write(line1)
            f.write(line2)

        f.write("\n")

    print(f"{tr('status.incon.exported_incon')} {filepath}")
    return filepath
