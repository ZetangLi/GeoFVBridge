import unittest
from pathlib import Path

from geofvbridge.api import inspect_mesh


class PublicExampleSmokeTests(unittest.TestCase):
    def test_bundled_meshes_can_be_inspected(self):
        root = Path(__file__).parents[1]
        cases = (
            ("examples/eg_3d004/1_msh/eg3d004.msh", 3),
            ("examples/eg_Ff006/1_msh/Ff006.msh", 2),
        )

        for relative_path, expected_dimension in cases:
            with self.subTest(mesh=relative_path):
                path = root / relative_path
                self.assertTrue(path.is_file())
                inspection = inspect_mesh(path)
                self.assertEqual(inspection["dimension"], expected_dimension)
                self.assertGreater(inspection["points"], 0)
                self.assertTrue(inspection["cell_types"])
                self.assertTrue(inspection["physical_groups"])
