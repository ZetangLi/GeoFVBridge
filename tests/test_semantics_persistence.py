import tempfile
import unittest
from pathlib import Path

import h5py
import meshio
import numpy as np

from geofvbridge.converter import convert_meshio
from geofvbridge.model import CellField, ConversionOptions, SourceConnection
from geofvbridge.persistence import read_model, write_model


class SemanticsPersistenceTests(unittest.TestCase):
    def model(self):
        points = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1.0]])
        cells = [
            ("line", np.array([[0, 1]])),
            ("triangle", np.array([[0, 2, 1], [0, 1, 3], [1, 2, 3], [2, 0, 3]])),
            ("tetra", np.array([[0, 1, 2, 3]])),
        ]
        data = {"gmsh:physical": [np.array([30]), np.full(4, 20), np.array([10])]}
        fields = {
            "Injector": np.array([30, 1]),
            "Wall": np.array([20, 2]),
            "Rock": np.array([10, 3]),
        }
        return convert_meshio(meshio.Mesh(points, cells, cell_data=data, field_data=fields))

    def test_dimension_aware_mapping(self):
        model = self.model()
        self.assertEqual(model.cells[0].material, "Rock")
        self.assertEqual({item.name for item in model.boundaries}, {"Wall"})
        self.assertEqual(model.sources[0].name, "Injector")
        self.assertEqual(model.sources[0].cell, 0)

    def test_role_overrides_can_ignore_groups(self):
        points = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1.0]])
        cells = [
            ("vertex", np.array([[0]])),
            ("triangle", np.array([[0, 2, 1], [0, 1, 3], [1, 2, 3], [2, 0, 3]])),
            ("tetra", np.array([[0, 1, 2, 3]])),
        ]
        data = {"gmsh:physical": [np.array([30]), np.full(4, 20), np.array([10])]}
        fields = {
            "PointSource": np.array([30, 0]),
            "Wall": np.array([20, 2]),
            "Rock": np.array([10, 3]),
        }
        options = ConversionOptions(physical_roles={"PointSource": "ignore", "Wall": "ignore"})
        model = convert_meshio(
            meshio.Mesh(points, cells, cell_data=data, field_data=fields), options=options
        )
        self.assertEqual(model.cells[0].material, "Rock")
        self.assertFalse(model.sources)
        self.assertEqual({item.name for item in model.boundaries}, {"UNASSIGNED"})

    def test_hdf5_round_trip(self):
        model = self.model()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "model.geofv.h5"
            write_model(model, path)
            loaded = read_model(path)
            self.assertEqual(loaded.cells[0].nodes, model.cells[0].nodes)
            self.assertEqual(loaded.faces[0].nodes, model.faces[0].nodes)
            self.assertEqual(loaded.sources[0].name, "Injector")
            self.assertAlmostEqual(loaded.cells[0].measure, 1.0 / 6.0)

    def test_connection_diagnostics_round_trip(self):
        points = np.array(
            [[0, 0, 0], [2, 0, 0], [0, 2, 0], [0, 0, 2], [2, 0, -1.0]]
        )
        model = convert_meshio(
            meshio.Mesh(points, [("tetra", np.array([[0, 1, 2, 3], [0, 2, 1, 4]]))])
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "model.geofv.h5"
            write_model(model, path)
            loaded = read_model(path)
        expected = model.connections[0]
        actual = loaded.connections[0]
        np.testing.assert_allclose(actual.intersection, expected.intersection)
        self.assertAlmostEqual(actual.d1, expected.d1)
        self.assertAlmostEqual(actual.normal_d1, expected.normal_d1)
        self.assertAlmostEqual(loaded.faces[expected.face].planarity, model.faces[expected.face].planarity)

    def test_schema_1_2_petrel_extensions_round_trip(self):
        points = np.array(
            [[0, 0, 0], [2, 0, 0], [0, 2, 0], [0, 0, 2], [2, 0, -1.0]]
        )
        model = convert_meshio(
            meshio.Mesh(points, [("tetra", np.array([[0, 1, 2, 3], [0, 2, 1, 4]]))])
        )
        model.cells[0].source_kind = "petrel"
        model.cells[0].source_global_index = 17
        model.cells[0].active_index = 3
        model.cells[0].ijk = (2, 3, 4)
        model.cells[0].source_members = (17, 18)
        model.cell_fields["PORO"] = CellField(
            np.array([0.1, 0.2]), unit="fraction", source="case.INIT", keyword="PORO"
        )
        model.source_connections.append(
            SourceConnection(
                id=0,
                cell1=0,
                cell2=1,
                kind="REGULAR_Z",
                transmissibility=2.5,
                flow_connected=True,
                direction="Z",
                matched_connection=0,
                geometry_status="matched",
                metadata={"i": 2},
            )
        )
        model.connections[0].source_connection_id = 0
        model.connections[0].enabled = False
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "petrel.geofv.h5"
            write_model(model, path)
            loaded = read_model(path)
        self.assertEqual(loaded.cells[0].ijk, (2, 3, 4))
        self.assertEqual(loaded.cells[0].source_members, (17, 18))
        np.testing.assert_allclose(loaded.cell_fields["PORO"].values, [0.1, 0.2])
        self.assertEqual(loaded.cell_fields["PORO"].unit, "fraction")
        self.assertFalse(loaded.connections[0].enabled)
        self.assertEqual(loaded.source_connections[0].metadata, {"i": 2})

    def test_schema_1_0_reconstructs_intersection_diagnostics(self):
        points = np.array(
            [[0, 0, 0], [2, 0, 0], [0, 2, 0], [0, 0, 2], [2, 0, -1.0]]
        )
        model = convert_meshio(
            meshio.Mesh(points, [("tetra", np.array([[0, 1, 2, 3], [0, 2, 1, 4]]))])
        )
        expected = model.connections[0]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "schema_1_0.geofv.h5"
            write_model(model, path)
            with h5py.File(path, "r+") as handle:
                handle.attrs["schema_version"] = "1.0"
                del handle["cell_fields"]
                del handle["source_connections"]
                for name in (
                    "source_kind",
                    "source_global_index",
                    "active_index",
                    "ijk",
                    "source_members",
                    "source_member_offsets",
                ):
                    del handle[f"cells/{name}"]
                del handle["faces/planarity"]
                del handle["connections/intersection"]
                del handle["connections/normal_d1"]
                del handle["connections/normal_d2"]
                del handle["connections/enabled"]
                del handle["connections/source_connection_id"]
            loaded = read_model(path)
        actual = loaded.connections[0]
        np.testing.assert_allclose(actual.intersection, expected.intersection)
        self.assertAlmostEqual(actual.d1, expected.d1)
        self.assertAlmostEqual(actual.d2, expected.d2)
        self.assertAlmostEqual(actual.normal_d1, expected.normal_d1)
        self.assertEqual(loaded.faces[actual.face].planarity, 0.0)
        self.assertTrue(actual.enabled)
        self.assertFalse(loaded.cell_fields)
        self.assertFalse(loaded.source_connections)


if __name__ == "__main__":
    unittest.main()
