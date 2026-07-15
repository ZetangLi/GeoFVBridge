import tempfile
import unittest
from pathlib import Path

import meshio
import numpy as np

from geofvbridge.api import (
    convert_mesh,
    export_model,
    export_solver_mesh,
    load_fv_dataset,
    prepare_solver_model,
    save_fv_dataset,
)
from geofvbridge.model import ExtrusionOptions


class NativeSolverWorkflowTests(unittest.TestCase):
    @staticmethod
    def _write_quad(path: Path):
        points = np.array([[0.0, 0, 0], [1, 0, 0], [1, 0, 1], [0, 0, 1]])
        mesh = meshio.Mesh(points, [("quad", np.array([[0, 1, 2, 3]]))])
        meshio.write(path, mesh, file_format="gmsh22", binary=False)
        return points

    def test_native_2d_roundtrip_and_solver_source_parity(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            source = directory / "quad.msh"
            points = self._write_quad(source)
            native = convert_mesh(source)
            self.assertEqual(native.dimension, 2)
            self.assertEqual(native.cells[0].cell_type, "quad")
            np.testing.assert_allclose(native.points, points)
            self.assertEqual(native.cells[0].nodes, (0, 1, 2, 3))

            artifacts = save_fv_dataset(native, directory / "quad.geofv.h5")
            loaded = load_fv_dataset(artifacts.hdf5)
            self.assertEqual(loaded.dimension, 2)
            self.assertEqual(loaded.cells[0].nodes, native.cells[0].nodes)
            self.assertEqual(len(loaded.faces), len(native.faces))
            self.assertEqual(len(loaded.boundaries), len(native.boundaries))

            extrusion = ExtrusionOptions((0.0, 1.0, 0.0), (0.01, 0.01))
            from_msh = prepare_solver_model(source, extrusion)
            from_h5 = prepare_solver_model(artifacts.hdf5, extrusion)
            self.assertEqual(from_msh.dimension, 3)
            self.assertEqual([cell.cell_type for cell in from_msh.cells], ["hexahedron"] * 2)
            np.testing.assert_allclose(from_msh.points, from_h5.points)
            np.testing.assert_allclose(
                [cell.measure for cell in from_msh.cells],
                [cell.measure for cell in from_h5.cells],
            )
            np.testing.assert_allclose(
                [cell.centroid for cell in from_msh.cells],
                [cell.centroid for cell in from_h5.cells],
            )
            np.testing.assert_allclose(
                [[item.d1, item.d2, item.interface_measure, item.gravity_projection] for item in from_msh.connections],
                [[item.d1, item.d2, item.interface_measure, item.gravity_projection] for item in from_h5.connections],
            )

    def test_mesh_only_export_writes_no_flow_or_incon(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            source = directory / "quad.msh"
            self._write_quad(source)
            native = convert_mesh(source)
            solver = prepare_solver_model(
                native, ExtrusionOptions((0.0, 1.0, 0.0), (0.019,))
            )
            output = directory / "solver"
            manifest = export_solver_mesh(solver, "tough2-eco2m", {}, output)
            self.assertEqual(manifest["cells"], 1)
            self.assertTrue((output / "MESH").is_file())
            self.assertTrue((output / "cell_map.csv").is_file())
            self.assertTrue((output / "mesh_manifest.json").is_file())
            self.assertFalse((output / "flow.inp").exists())
            self.assertFalse((output / "INCON").exists())

    def test_full_api_export_prepares_native_2d_from_config(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            source = directory / "quad.msh"
            self._write_quad(source)
            artifacts = save_fv_dataset(convert_mesh(source), directory / "quad.geofv.h5")
            output = directory / "full"
            manifest = export_model(
                artifacts.hdf5,
                "tough2-eco2m",
                {
                    "extrusion": {
                        "axis": "y",
                        "total_thickness": 0.02,
                        "layers": 2,
                    }
                },
                output,
            )
            self.assertEqual(manifest["cells"], 2)
            self.assertTrue((output / "MESH").is_file())
            self.assertTrue((output / "flow.inp").is_file())
            self.assertTrue((output / "INCON").is_file())


if __name__ == "__main__":
    unittest.main()
