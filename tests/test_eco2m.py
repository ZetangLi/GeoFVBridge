import math
import tempfile
import unittest
from pathlib import Path

import meshio
import numpy as np

from geofvbridge.backends.eco2m import (
    TOUGH_LABEL_CAPACITY,
    _is_a3_i2,
    _label,
    export_eco2m,
    export_eco2m_mesh,
    read_flow_output,
    validate_eco2m,
)
from geofvbridge.converter import convert_meshio
from geofvbridge.extrusion import extrude_meshio
from geofvbridge.model import ConversionOptions, SourceConnection


class Eco2mTests(unittest.TestCase):
    def cube(self):
        points = np.array(
            [[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0], [0, 0, 1], [1, 0, 1], [1, 1, 1], [0, 1, 1.0]]
        )
        model = convert_meshio(meshio.Mesh(points, [("hexahedron", np.array([[0, 1, 2, 3, 4, 5, 6, 7]]))]))
        for boundary in model.boundaries:
            if model.faces[boundary.face].centroid[2] > 0.999:
                boundary.name = "TOP"
        return model

    def test_labels_match_original_gui_a3_i2_progression(self):
        expected = {
            0: "A11 0",
            1: "A11 1",
            9: "A11 9",
            10: "A1110",
            99: "A1199",
            100: "A12 0",
            999: "A1A99",
            1000: "A1B 0",
            122_499: "AZZ99",
            122_500: "B11 0",
            TOUGH_LABEL_CAPACITY - 1: "ZZZ99",
        }
        for index, label in expected.items():
            with self.subTest(index=index):
                self.assertEqual(_label(index), label)
                self.assertTrue(_is_a3_i2(label))
        with self.assertRaises(ValueError):
            _label(TOUGH_LABEL_CAPACITY)

    def test_conne_isot_uses_gravity_angle_and_preserves_geometry(self):
        source = meshio.Mesh(
            np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0.0]]),
            [("quad", np.array([[0, 1, 2, 3]]))],
        )
        extruded = extrude_meshio(source, layer_thicknesses=[0.25, 0.75])
        cases = [
            (0.0, 3), (30.0, 3), (44.999999, 3), (45.0, 1),
            (45.000001, 1), (90.0, 1), (134.999999, 1), (135.0, 1),
            (135.000001, 3), (150.0, 3), (180.0, 3),
        ]
        with tempfile.TemporaryDirectory() as directory:
            for angle, expected_isot in cases:
                radians = math.radians(angle)
                gravity = (2.0 * math.sin(radians), 0.0, 2.0 * math.cos(radians))
                for reverse in (False, True):
                    nodes = extruded.cells[0].data
                    mesh = meshio.Mesh(
                        extruded.points,
                        [("hexahedron", nodes[::-1] if reverse else nodes)],
                    )
                    model = convert_meshio(mesh, options=ConversionOptions(gravity=gravity))
                    connection = model.connections[0]
                    original = (
                        connection.d1, connection.d2, connection.interface_measure,
                        connection.gravity_projection,
                    )
                    for exporter in (export_eco2m_mesh, export_eco2m):
                        with self.subTest(angle=angle, reverse=reverse, exporter=exporter.__name__):
                            exporter(model, {}, directory)
                            lines = (Path(directory) / "MESH").read_text("ascii").splitlines()
                            header = next(i for i, line in enumerate(lines) if line.startswith("CONNE"))
                            record = lines[header + 1]
                            self.assertEqual(len(record), 80)
                            self.assertEqual(record[:10], "A11 0A11 1")
                            self.assertEqual(int(record[25:30]), expected_isot)
                            np.testing.assert_allclose(
                                [float(record[i:i + 10]) for i in (30, 40, 50, 60)],
                                # Ten columns include the sign and exponent;
                                # negative BETAX can round at the fifth decimal.
                                original, rtol=1e-5, atol=1e-12,
                            )
                            expected_beta = math.cos(radians) * (-1 if reverse else 1)
                            self.assertAlmostEqual(connection.gravity_projection, expected_beta)
                            self.assertAlmostEqual(
                                float(record[60:70]), expected_beta, delta=5e-6,
                            )
                            self.assertEqual(
                                (connection.d1, connection.d2, connection.interface_measure,
                                 connection.gravity_projection), original,
                            )

    def test_conne_isot_with_zero_gravity_is_horizontal(self):
        source = meshio.Mesh(
            np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0.0]]),
            [("quad", np.array([[0, 1, 2, 3]]))],
        )
        model = convert_meshio(
            extrude_meshio(source, layer_thicknesses=[0.5, 0.5]),
            options=ConversionOptions(gravity=(0.0, 0.0, 0.0)),
        )
        with tempfile.TemporaryDirectory() as directory:
            export_eco2m_mesh(model, {}, directory)
            lines = (Path(directory) / "MESH").read_text("ascii").splitlines()
            header = next(i for i, line in enumerate(lines) if line.startswith("CONNE"))
            self.assertEqual(int(lines[header + 1][25:30]), 1)
            self.assertEqual(float(lines[header + 1][60:70]), 0.0)

    def test_export_with_automatic_state_boundary(self):
        model = self.cube()
        config = {
            "boundary_mode": "auto",
            "boundaries": {"TOP": {"kind": "state", "primary": [101325, 0, 0, 20]}},
            "flow": {"times": [1, 10]},
        }
        with tempfile.TemporaryDirectory() as directory:
            manifest = export_eco2m(model, config, directory)
            self.assertEqual(manifest["cells"], 2)
            self.assertEqual(manifest["cell_label_format"], "TOUGH A3,I2")
            self.assertEqual(len(manifest["generated_boundary_cells"]), 1)
            self.assertEqual(manifest["generated_boundary_cells"][0]["label"], "A11 1")
            mesh_lines = (Path(directory) / "MESH").read_text("ascii").splitlines()
            self.assertEqual(mesh_lines[1][:5], "A11 0")
            self.assertEqual(mesh_lines[2][:5], "A11 1")
            conne_header = next(
                index for index, line in enumerate(mesh_lines) if line.startswith("CONNE")
            )
            self.assertEqual(mesh_lines[conne_header + 1][:10], "A11 0A11 1")
            self.assertEqual(int(mesh_lines[conne_header + 1][25:30]), 3)
            self.assertEqual(float(mesh_lines[conne_header + 1][60:70]), -1.0)
            incon_lines = (Path(directory) / "INCON").read_text("ascii").splitlines()
            self.assertEqual(incon_lines[1], "A11 0")
            self.assertEqual(incon_lines[3], "A11 1")
            self.assertTrue((Path(directory) / "INCON").is_file())
            flow_text = (Path(directory) / "flow.inp").read_text("ascii")
            self.assertTrue(flow_text.startswith("\nROCKS"))

    def test_automatic_generator_names_use_a3_i2(self):
        model = self.cube()
        config = {
            "boundary_mode": "auto",
            "boundaries": {
                "TOP": {
                    "kind": "flux",
                    "name": "injector",
                    "value": 1.0,
                }
            },
        }
        with tempfile.TemporaryDirectory() as directory:
            export_eco2m(model, config, directory)
            lines = (Path(directory) / "flow.inp").read_text("ascii").splitlines()
            header = next(index for index, line in enumerate(lines) if line.startswith("GENER"))
            record = lines[header + 1]
            self.assertEqual(record[:5], "A11 0")
            self.assertEqual(record[5:10], "inj 1")
            self.assertTrue(_is_a3_i2(record[:5]))
            self.assertTrue(_is_a3_i2(record[5:10]))

    def test_flow_output_element_and_connection_parse(self):
        model = self.cube()
        text = """OUTPUT DATA AFTER ITERATION 1 THE TIME IS 1.0000E+00 DAYS
 ELEM. INDEX P T
 A11 0 1 1.01325E+05 2.00000E+01
 ELEM1 ELEM2 FLO
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "flow.out"
            path.write_text(text, encoding="latin-1")
            results = read_flow_output(path, model)
            self.assertEqual(len(results.steps), 1)
            self.assertIn("A11 0", results.steps[0].elements)
            self.assertAlmostEqual(results.steps[0].time_seconds, 86400.0)

    def test_inactive_top_preserves_geometric_distance_and_ahtx(self):
        source = meshio.Mesh(
            np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0.0]]),
            [("quad", np.array([[0, 1, 2, 3]]))],
        )
        model = convert_meshio(extrude_meshio(source, layer_thicknesses=[0.5, 0.5]))
        config = {
            "inactive_top": True,
            "infinite_volume": 1.0e50,
            "ahtx": {"mode": "all"},
        }
        with tempfile.TemporaryDirectory() as directory:
            manifest = export_eco2m(model, config, directory)
            self.assertEqual([item["cell_id"] for item in manifest["inactive_cells"]], [1])
            self.assertEqual(manifest["cells"], len(model.cells))
            self.assertEqual(manifest["generated_boundary_cells"], [])
            lines = (Path(directory) / "MESH").read_text("ascii").splitlines()
            element_lines = lines[1:3]
            self.assertAlmostEqual(float(element_lines[1][20:30]), 1.0e50)
            self.assertGreater(float(element_lines[0][30:40]), 0.0)
            connection_header = next(i for i, line in enumerate(lines) if line.startswith("CONNE"))
            connection = lines[connection_header + 1]
            self.assertAlmostEqual(
                float(connection[40:50]),
                model.connections[0].d2,
            )

    def test_boundary_group_infinite_volume_overrides_material_volume_only(self):
        source = meshio.Mesh(
            np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0.0]]),
            [("quad", np.array([[0, 1, 2, 3]]))],
        )
        model = convert_meshio(extrude_meshio(source, layer_thicknesses=[0.5, 0.5]))
        for cell in model.cells:
            cell.material = "ROCK"
        for boundary in model.boundaries:
            if model.faces[boundary.face].centroid[2] > 0.999:
                boundary.name = "Top"
        original_connection = (
            model.connections[0].d1,
            model.connections[0].d2,
            model.connections[0].interface_measure,
            model.connections[0].gravity_projection,
        )
        config = {
            "inactive_selection": {
                "method": "boundary_group",
                "boundary_group": "Top",
            },
            "infinite_volume": 1.0e50,
            "volume_overrides": {"ROCK": 7.5},
        }
        with tempfile.TemporaryDirectory() as directory:
            manifest = export_eco2m_mesh(model, config, directory)
            self.assertEqual(manifest["inactive_selection"], config["inactive_selection"])
            inactive = manifest["inactive_cells"]
            self.assertEqual([item["cell_id"] for item in inactive], [1])
            self.assertEqual(inactive[0]["volume"], 1.0e50)
            lines = (Path(directory) / "MESH").read_text("ascii").splitlines()
            self.assertAlmostEqual(float(lines[1][20:30]), 7.5)
            self.assertAlmostEqual(float(lines[2][20:30]), 1.0e50)
        self.assertEqual(
            (
                model.connections[0].d1,
                model.connections[0].d2,
                model.connections[0].interface_measure,
                model.connections[0].gravity_projection,
            ),
            original_connection,
        )

    def test_unrepresented_petrel_connection_requires_explicit_override(self):
        points = np.array(
            [
                [0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1],
                [2, 0, 0], [3, 0, 0], [2, 1, 0], [2, 0, 1],
            ],
            dtype=float,
        )
        model = convert_meshio(
            meshio.Mesh(
                points,
                [("tetra", np.array([[0, 1, 2, 3], [4, 5, 6, 7]]))],
            )
        )
        model.source_connections.append(
            SourceConnection(
                id=0,
                cell1=0,
                cell2=1,
                kind="nnc",
                transmissibility=2.5,
                flow_connected=True,
                geometry_status="nnc",
            )
        )
        errors = validate_eco2m(model, {})
        self.assertTrue(any("no TOUGH geometry" in message for message in errors))
        with tempfile.TemporaryDirectory() as directory:
            manifest = export_eco2m(
                model,
                {"allow_unrepresented_source_connections": True},
                directory,
            )
            audit = manifest["source_connection_audit"]
            self.assertEqual(audit["ignored_positive_without_geometry"], 1)
            self.assertTrue(audit["ignore_was_explicitly_allowed"])
            self.assertEqual(audit["sample_ignored_source_connection_ids"], [0])


if __name__ == "__main__":
    unittest.main()
