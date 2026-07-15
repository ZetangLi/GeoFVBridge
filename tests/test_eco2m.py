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
    read_flow_output,
)
from geofvbridge.converter import convert_meshio
from geofvbridge.extrusion import extrude_meshio


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


if __name__ == "__main__":
    unittest.main()
