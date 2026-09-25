import unittest

import meshio
import numpy as np

from geofvbridge.backends.eco2m import _inactive_cells, validate_eco2m
from geofvbridge.boundary_selection import (
    build_boundary_selection_index,
    resolve_boundary_selection,
    selection_preview,
)
from geofvbridge.converter import convert_meshio
from geofvbridge.extrusion import extrude_meshio


class BoundarySelectionTests(unittest.TestCase):
    @staticmethod
    def layered_model():
        source = meshio.Mesh(
            np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0.0]]),
            [("quad", np.array([[0, 1, 2, 3]]))],
        )
        model = convert_meshio(extrude_meshio(source, layer_thicknesses=[0.5, 0.5]))
        model.cells[0].material = "ROCK"
        model.cells[1].material = "BOUND"
        for boundary in model.boundaries:
            face = model.faces[boundary.face]
            if face.centroid[2] > 0.999:
                boundary.name = "Top"
            elif face.centroid[2] < 0.001:
                boundary.name = "Bottom"
            else:
                boundary.name = "OuterSide"
        return model

    def test_all_canonical_methods_are_mutually_resolved(self):
        model = self.layered_model()
        index = build_boundary_selection_index(model)
        cases = (
            ({"method": "material", "material": "BOUND"}, [1]),
            ({"method": "boundary_group", "boundary_group": "Top"}, [1]),
            ({"method": "coordinate", "axis": 2, "operator": "ge", "value": 0.5}, [1]),
            (
                {
                    "method": "exposed_face",
                    "axis": 2,
                    "direction": 1,
                    "minimum_normal": 0.9,
                },
                [1],
            ),
            ({"method": "global_plane", "axis": 2, "side": "max"}, [1]),
        )
        for selection, expected in cases:
            with self.subTest(selection=selection):
                result = resolve_boundary_selection(model, selection, index)
                self.assertEqual(result.cell_ids.tolist(), expected)

    def test_boundary_group_reports_faces_unique_cells_and_node_range(self):
        model = self.layered_model()
        index = build_boundary_selection_index(model)
        result, report = selection_preview(
            model,
            {"method": "boundary_group", "boundary_group": "top"},
            index,
        )
        self.assertEqual(result.face_count, 1)
        self.assertEqual(result.cell_count, 1)
        self.assertEqual(report["node_coordinate_min"][2], 1.0)
        self.assertEqual(report["node_coordinate_max"][2], 1.0)

    def test_reverse_directions_and_invalid_selections(self):
        model = self.layered_model()
        index = build_boundary_selection_index(model)
        cases = (
            ({"method": "coordinate", "axis": 2, "operator": "le", "value": 0.5}, [0]),
            (
                {
                    "method": "exposed_face",
                    "axis": 2,
                    "direction": -1,
                    "minimum_normal": 0.9,
                },
                [0],
            ),
            ({"method": "global_plane", "axis": 2, "side": "min"}, [0]),
        )
        for selection, expected in cases:
            with self.subTest(selection=selection):
                result = resolve_boundary_selection(model, selection, index)
                self.assertEqual(result.cell_ids.tolist(), expected)
        with self.assertRaisesRegex(ValueError, "Unknown boundary face group"):
            resolve_boundary_selection(
                model,
                {"method": "boundary_group", "boundary_group": "Missing"},
                index,
            )
        with self.assertRaisesRegex(ValueError, "matched no cells"):
            resolve_boundary_selection(
                model,
                {"method": "coordinate", "axis": 2, "operator": "ge", "value": 99.0},
                index,
            )

    def test_canonical_selector_cannot_be_combined_with_legacy_selector(self):
        model = self.layered_model()
        config = {
            "inactive_selection": {"method": "material", "material": "BOUND"},
            "inactive_top": True,
        }
        errors = validate_eco2m(model, config)
        self.assertTrue(any("cannot be combined" in error for error in errors))

    def test_legacy_selector_remains_supported(self):
        model = self.layered_model()
        selected, _ = _inactive_cells(model, {"inactive_top": True})
        self.assertEqual(selected, {1})


if __name__ == "__main__":
    unittest.main()
