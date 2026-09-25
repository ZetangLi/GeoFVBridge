from pathlib import Path

import meshio
import numpy as np

from geofvbridge.extrusion import extrude_meshio


def main():
    output = Path(__file__).parent / "generated"
    output.mkdir(parents=True, exist_ok=True)
    points = np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]], dtype=float)
    triangles = np.array([[0, 1, 2], [0, 2, 3]], dtype=int)
    mesh = meshio.Mesh(
        points,
        [("triangle", triangles)],
        cell_data={"gmsh:physical": [np.array([1, 1])]},
        field_data={"ROCK": np.array([1, 2])},
    )
    mesh = extrude_meshio(mesh, direction=(0, 0, 1), layer_thicknesses=(1.0,))
    mesh.cell_data["gmsh:geometrical"] = [values.copy() for values in mesh.cell_data["gmsh:physical"]]
    # Gmsh 2.2 can represent the mixed volume/surface blocks without the
    # explicit entity ownership required by the Gmsh 4.1 writer.
    meshio.write(output / "two_prisms.msh", mesh, file_format="gmsh22", binary=False)
    print(output / "two_prisms.msh")


if __name__ == "__main__":
    main()
