import unittest
from types import SimpleNamespace

import meshio
import numpy as np

from geofvbridge.converter import ConversionError, convert_meshio


class GeometryTests(unittest.TestCase):
    CASES = {
        "triangle": (np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0.0]]), [[0, 1, 2]], 0.5, 3),
        "quad": (
            np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0.0]]),
            [[0, 1, 2, 3]],
            1.0,
            4,
        ),
        "tetra": (
            np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1.0]]),
            [[0, 1, 2, 3]],
            1.0 / 6.0,
            4,
        ),
        "wedge": (
            np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1], [1, 0, 1], [0, 1, 1.0]]),
            [[0, 1, 2, 3, 4, 5]],
            0.5,
            5,
        ),
        "hexahedron": (
            np.array(
                [[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0], [0, 0, 1], [1, 0, 1], [1, 1, 1], [0, 1, 1.0]]
            ),
            [[0, 1, 2, 3, 4, 5, 6, 7]],
            1.0,
            6,
        ),
        "voxel": (
            np.array(
                [[0, 0, 0], [1, 0, 0], [0, 1, 0], [1, 1, 0], [0, 0, 1], [1, 0, 1], [0, 1, 1], [1, 1, 1.0]]
            ),
            [[0, 1, 2, 3, 4, 5, 6, 7]],
            1.0,
            6,
        ),
        "pyramid": (
            np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0], [0.5, 0.5, 1.0]]),
            [[0, 1, 2, 3, 4]],
            1.0 / 3.0,
            5,
        ),
    }

    def test_analytic_measures(self):
        for cell_type, (points, cells, expected, face_count) in self.CASES.items():
            with self.subTest(cell_type=cell_type):
                if cell_type == "voxel":
                    mesh = SimpleNamespace(
                        points=points,
                        cells=[SimpleNamespace(type="voxel", data=np.asarray(cells))],
                        field_data={},
                        cell_data={},
                    )
                else:
                    mesh = meshio.Mesh(points, [(cell_type, np.asarray(cells))])
                model = convert_meshio(mesh)
                self.assertAlmostEqual(model.cells[0].measure, expected, places=12)
                self.assertEqual(len(model.faces), face_count)
                self.assertTrue(model.report.valid)
                if cell_type == "voxel":
                    self.assertEqual(model.cells[0].cell_type, "hexahedron")

    def test_high_order_is_rejected(self):
        points = np.zeros((10, 3))
        with self.assertRaises(ConversionError):
            convert_meshio(meshio.Mesh(points, [("tetra10", np.arange(10).reshape(1, 10))]))

    def test_pyramid_uses_volume_centroid_not_vertex_average(self):
        points, cells, _volume, _faces = self.CASES["pyramid"]
        model = convert_meshio(meshio.Mesh(points, [("pyramid", np.asarray(cells))]))
        self.assertAlmostEqual(model.cells[0].centroid[2], 0.25, places=12)
        self.assertNotAlmostEqual(model.cells[0].centroid[2], points[:, 2].mean(), places=6)

    def test_tapered_hexahedron_true_centroid(self):
        points = np.array(
            [
                [-0.5, -0.5, 0], [0.5, -0.5, 0], [0.5, 0.5, 0], [-0.5, 0.5, 0],
                [-1, -1, 1], [1, -1, 1], [1, 1, 1], [-1, 1, 1],
            ],
            dtype=float,
        )
        model = convert_meshio(meshio.Mesh(points, [("hexahedron", np.arange(8).reshape(1, 8))]))
        self.assertAlmostEqual(model.cells[0].measure, 7.0 / 3.0, places=12)
        self.assertAlmostEqual(model.cells[0].centroid[2], 17.0 / 28.0, places=12)
        self.assertNotAlmostEqual(model.cells[0].centroid[2], 0.5, places=6)


if __name__ == "__main__":
    unittest.main()
