import unittest

import meshio
import numpy as np

from geofvbridge.converter import convert_meshio
from geofvbridge.extrusion import extrude_meshio
from geofvbridge.model import ValidationIssue, ValidationReport


class TopologyTests(unittest.TestCase):
    def test_validation_report_uses_stable_hash_deduplication(self):
        report = ValidationReport(
            [ValidationIssue("warning", "existing", "Existing warning.")]
        )
        report.add("warning", "existing", "Existing warning.")
        for entity_id in range(1000):
            report.add("warning", "many", "Warning.", "face", entity_id)
        self.assertEqual(len(report.issues), 1001)
        self.assertEqual(len(report._issue_keys), 1001)

    def test_nonplanar_faces_are_aggregated_in_one_warning(self):
        points = np.array(
            [
                [0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0],
                [0, 0, 1], [1, 0, 1], [1, 1, 1.2], [0, 1, 1],
                [2, 0, 0], [3, 0, 0], [3, 1, 0], [2, 1, 0],
                [2, 0, 1], [3, 0, 1], [3, 1, 1.2], [2, 1, 1],
            ],
            dtype=float,
        )
        model = convert_meshio(
            meshio.Mesh(points, [("hexahedron", np.arange(16).reshape(2, 8))])
        )
        issues = [issue for issue in model.report.warnings if issue.code == "nonplanar_face"]
        diagnostic = model.metadata["diagnostics"]["nonplanar_faces"]
        self.assertEqual(len(issues), 1)
        self.assertGreater(diagnostic["count"], 1)
        self.assertEqual(model.summary()["face_nonplanarity_count"], diagnostic["count"])

    def test_two_tetrahedra_share_one_face(self):
        points = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1], [0, 0, -1.0]])
        cells = np.array([[0, 1, 2, 3], [0, 2, 1, 4]])
        model = convert_meshio(meshio.Mesh(points, [("tetra", cells)]))
        self.assertEqual(len(model.faces), 7)
        self.assertEqual(len(model.connections), 1)
        self.assertEqual(len(model.boundaries), 6)
        self.assertGreater(model.connections[0].orthogonality, 0.0)

    def test_nonmanifold_face_is_an_error(self):
        points = np.array(
            [[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1], [0, 0, -1], [0.2, 0.2, 2.0]]
        )
        cells = np.array([[0, 1, 2, 3], [0, 2, 1, 4], [0, 1, 2, 5]])
        model = convert_meshio(meshio.Mesh(points, [("tetra", cells)]))
        self.assertFalse(model.report.valid)
        self.assertIn("nonmanifold_face", {issue.code for issue in model.report.errors})

    def test_layered_quad_extrusion(self):
        points = np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0.0]])
        source = meshio.Mesh(points, [("quad", np.array([[0, 1, 2, 3]]))])
        model = convert_meshio(extrude_meshio(source, layer_thicknesses=[0.25, 0.75]))
        self.assertEqual([cell.cell_type for cell in model.cells], ["hexahedron", "hexahedron"])
        self.assertAlmostEqual(sum(cell.measure for cell in model.cells), 1.0)
        self.assertEqual(len(model.connections), 1)
        self.assertAlmostEqual(model.connections[0].orthogonality, 1.0)

    def test_layered_triangle_extrusion(self):
        points = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0.0]])
        source = meshio.Mesh(points, [("triangle", np.array([[0, 1, 2]]))])
        model = convert_meshio(extrude_meshio(source, layer_thicknesses=[0.25, 0.75]))
        self.assertEqual([cell.cell_type for cell in model.cells], ["wedge", "wedge"])
        self.assertAlmostEqual(sum(cell.measure for cell in model.cells), 0.5)
        self.assertEqual(len(model.connections), 1)

    def test_nonorthogonal_connection_uses_centroid_line_intersection(self):
        points = np.array(
            [[0, 0, 0], [2, 0, 0], [0, 2, 0], [0, 0, 2], [2, 0, -1.0]]
        )
        cells = np.array([[0, 1, 2, 3], [0, 2, 1, 4]])
        model = convert_meshio(meshio.Mesh(points, [("tetra", cells)]))
        connection = model.connections[0]
        self.assertAlmostEqual(connection.d1 + connection.d2, connection.center_distance)
        self.assertFalse(np.isclose(connection.d1, connection.normal_d1))
        self.assertFalse(np.isclose(connection.d2, connection.normal_d2))
        plane_z = model.faces[connection.face].centroid[2]
        self.assertAlmostEqual(connection.intersection[2], plane_z, places=12)

    def test_named_boundary_line_is_extruded_to_named_surface(self):
        points = np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0.0]])
        cells = [
            ("line", np.array([[0, 1]])),
            ("quad", np.array([[0, 1, 2, 3]])),
        ]
        data = {"gmsh:physical": [np.array([2]), np.array([1])]}
        fields = {"BottomEdge": np.array([2, 1]), "Rock": np.array([1, 2])}
        source = meshio.Mesh(points, cells, cell_data=data, field_data=fields)
        extruded = extrude_meshio(source, layer_thicknesses=[1.0])
        model = convert_meshio(extruded)
        self.assertIn("BottomEdge", {boundary.name for boundary in model.boundaries})


if __name__ == "__main__":
    unittest.main()
