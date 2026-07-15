import unittest

import meshio
import numpy as np

from geofvbridge.api import to_pyvista
from geofvbridge.converter import convert_meshio
from geofvbridge.model import Source


class VisualizationFilterTests(unittest.TestCase):
    @staticmethod
    def _two_material_model():
        points = np.array(
            [
                [0.0, 0.0, 0.0],
                [1.0, 0.0, 0.0],
                [0.0, 1.0, 0.0],
                [0.0, 0.0, 1.0],
                [0.0, 0.0, -1.0],
            ]
        )
        cells = np.array([[0, 1, 2, 3], [0, 2, 1, 4]])
        model = convert_meshio(meshio.Mesh(points, [("tetra", cells)]))
        model.cells[0].material = "ROCK_A"
        model.cells[1].material = "ROCK_B"
        model.sources = [
            Source(0, "SOURCE_A", model.cells[0].centroid.copy(), 0, 0.0),
            Source(1, "SOURCE_B", model.cells[1].centroid.copy(), 1, 0.0),
        ]
        return model

    def test_material_filter_does_not_mutate_model(self):
        model = self._two_material_model()
        original_materials = [cell.material for cell in model.cells]

        bundle = to_pyvista(model, "material", visible_materials={"ROCK_A"})

        self.assertEqual(bundle.grid.n_cells, 1)
        np.testing.assert_array_equal(bundle.grid.cell_data["cell_id"], [0])
        self.assertEqual(len(model.cells), 2)
        self.assertEqual([cell.material for cell in model.cells], original_materials)

    def test_empty_selection_returns_an_empty_display_grid(self):
        model = self._two_material_model()

        bundle = to_pyvista(model, "wireframe", visible_materials=set())

        self.assertEqual(bundle.grid.n_cells, 0)
        self.assertEqual(bundle.grid.n_points, 0)

    def test_boundary_and_source_overlays_follow_owner_cell(self):
        model = self._two_material_model()

        boundaries = to_pyvista(
            model,
            "boundaries",
            visible_materials={"ROCK_A"},
        )
        sources = to_pyvista(model, "sources", visible_materials={"ROCK_A"})

        self.assertEqual(boundaries.overlay.n_cells, 3)
        np.testing.assert_array_equal(
            np.unique(boundaries.overlay.cell_data["owner_cell_id"]),
            [0],
        )
        self.assertEqual(sources.overlay.n_points, 1)
        np.testing.assert_array_equal(sources.overlay.point_data["cell_id"], [0])

    def test_connection_requires_both_endpoint_materials(self):
        model = self._two_material_model()

        one_material = to_pyvista(
            model,
            "connections",
            visible_materials={"ROCK_A"},
        )
        both_materials = to_pyvista(
            model,
            "connections",
            visible_materials={"ROCK_A", "ROCK_B"},
        )

        self.assertEqual(one_material.overlay.n_cells, 0)
        self.assertEqual(both_materials.overlay.n_cells, 2)

    def test_quality_wireframe_and_inactive_modes_use_same_filter(self):
        model = self._two_material_model()

        for mode in ("quality", "wireframe", "tough_inactive"):
            with self.subTest(mode=mode):
                bundle = to_pyvista(
                    model,
                    mode,
                    inactive_cells={1},
                    visible_materials={"ROCK_B"},
                )
                self.assertEqual(bundle.grid.n_cells, 1)
                np.testing.assert_array_equal(bundle.grid.cell_data["cell_id"], [1])
        inactive = to_pyvista(
            model,
            "tough_inactive",
            inactive_cells={1},
            visible_materials={"ROCK_B"},
        )
        np.testing.assert_array_equal(inactive.grid.cell_data["tough_inactive"], [1])


if __name__ == "__main__":
    unittest.main()
