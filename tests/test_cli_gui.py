import json
import os
import runpy
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import meshio
import numpy as np

from geofvbridge.api import default_fv_dataset_path
from geofvbridge.cli import main


class CliTests(unittest.TestCase):
    def test_convert_and_validate(self):
        points = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1.0]])
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            source = directory / "Ff006.vtu"
            meshio.write(source, meshio.Mesh(points, [("tetra", np.array([[0, 1, 2, 3]]))]))
            self.assertEqual(main(["convert", str(source)]), 0)
            self.assertEqual(default_fv_dataset_path(source), directory / "Ff006.geofv.h5")
            self.assertTrue((directory / "Ff006.summary.json").is_file())
            self.assertTrue((directory / "Ff006.vtu").is_file())
            self.assertEqual(main(["validate", str(directory / "Ff006.geofv.h5")]), 0)

    def test_gui_app_supports_direct_script_loading(self):
        app_path = Path(__file__).parents[1] / "src" / "geofvbridge" / "gui" / "app.py"
        namespace = runpy.run_path(str(app_path), run_name="_geofvbridge_gui_direct_test")
        self.assertIn("MainWindow", namespace)
        self.assertIn("run", namespace)

    def test_source_tree_has_no_toughio_import(self):
        source = Path(__file__).parents[1] / "src" / "geofvbridge"
        occurrences = []
        for path in source.rglob("*.py"):
            text = path.read_text(encoding="utf-8").lower()
            if "import toughio" in text or "from toughio" in text:
                occurrences.append(str(path))
        self.assertEqual(occurrences, [])

    def test_failed_worker_keeps_previous_authoritative_dataset(self):
        from geofvbridge.worker import run_request

        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            output = directory / "case.geofv.h5"
            output.write_bytes(b"previous-valid-dataset")
            with self.assertRaises(FileNotFoundError):
                run_request(
                    {
                        "input": str(directory / "missing.msh"),
                        "output": str(output),
                    }
                )
            self.assertEqual(output.read_bytes(), b"previous-valid-dataset")
            self.assertFalse(list(directory.glob(".geofvbridge-*")))

    def test_worker_protocol_preserves_non_ascii_paths(self):
        from geofvbridge.worker import _emit

        path = r"C:\example-data\示例\模型.geofv.h5"
        with patch("builtins.print") as printer:
            _emit({"event": "complete", "result": {"model": path}})
        payload = printer.call_args.args[0]
        self.assertTrue(payload.isascii())
        self.assertEqual(json.loads(payload)["result"]["model"], path)

    def test_fe_visualization_ignores_incompatible_gmsh_cell_sets(self):
        import pyvista as pv

        from geofvbridge.gui.visualizer import _meshio_visualization_copy

        points = np.array(
            [
                [0.0, 0.0, 0.0],
                [1.0, 0.0, 0.0],
                [0.0, 1.0, 0.0],
                [0.0, 0.0, 1.0],
            ]
        )
        mesh = meshio.Mesh(
            points,
            [
                ("line", np.array([[0, 1]])),
                ("tetra", np.array([[0, 1, 2, 3]])),
            ],
            cell_data={
                "gmsh:physical": [np.array([10]), np.array([20])],
                "gmsh:geometrical": [np.array([1]), np.array([2])],
            },
            field_data={"ROCK": np.array([20, 3])},
            # Entity-based Gmsh sets may contain entity tags rather than
            # zero-based indices for every Meshio cell block.  PyVista asks
            # Meshio to convert them in place and would index past the block.
            cell_sets={"gmsh:bounding_entities": [np.array([30]), np.array([30])]},
        )

        view_mesh = _meshio_visualization_copy(mesh, dimension=3)
        self.assertEqual(view_mesh.cell_sets, {})
        self.assertEqual(len(view_mesh.cells), 1)
        self.assertEqual(view_mesh.cells[0].type, "tetra")
        np.testing.assert_array_equal(view_mesh.cell_data["gmsh:physical"][0], [20])
        grid = pv.from_meshio(view_mesh)
        self.assertEqual(grid.n_cells, 1)


@unittest.skipUnless(os.environ.get("QT_QPA_PLATFORM") == "offscreen", "requires offscreen Qt")
class GuiTests(unittest.TestCase):
    @staticmethod
    def _write_tetra(path: Path):
        mesh = meshio.Mesh(
            np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1.0]]),
            [("tetra", np.array([[0, 1, 2, 3]]))],
        )
        meshio.write(path, mesh, file_format="gmsh22", binary=False)

    @staticmethod
    def _wait_worker(application, worker):
        while worker is not None and worker.isRunning():
            application.processEvents()
            worker.wait(20)
        application.processEvents()
        application.processEvents()

    def test_seven_stage_window_and_mesh_only_export(self):
        import qdarktheme
        from PySide6.QtGui import QPalette
        from PySide6.QtWidgets import QApplication

        from geofvbridge.gui.app import MainWindow
        from geofvbridge.gui.sidebar import Sidebar
        from geofvbridge.styles import CUSTOM_QSS, Colors

        application = QApplication.instance() or QApplication([])
        application.setStyleSheet(qdarktheme.load_stylesheet("dark") + CUSTOM_QSS)
        self.assertIn("QComboBox::down-arrow", application.styleSheet())
        window = MainWindow()
        window.show()
        application.processEvents()
        page_color = window.page_stack.currentWidget().palette().color(QPalette.Window).name()
        self.assertEqual(page_color, Colors.BG_PANEL)
        self.assertEqual(window.visualizer.btn_popout.height(), 26)
        self.assertTrue(window.visualizer.btn_popout.property("compact"))
        self.assertGreaterEqual(
            window.visualizer.btn_popout.height(),
            window.visualizer.btn_popout.sizeHint().height(),
        )
        self.assertEqual(len(window.sidebar.buttons), 7)
        self.assertEqual(window.page_stack.count(), 7)
        self.assertFalse(window.sidebar.buttons[Sidebar.PAGE_DATASET].isEnabled())
        self.assertFalse(window.sidebar.buttons[Sidebar.PAGE_SOLVER].isEnabled())
        self.assertFalse(window.sidebar.buttons[Sidebar.PAGE_MESH].isEnabled())
        self.assertTrue(window.sidebar.buttons[Sidebar.PAGE_OUT].isEnabled())
        self.assertFalse(hasattr(window.page_import, "project_edit"))
        self.assertFalse(hasattr(window.page_import, "open_input_button"))
        self.assertFalse(window.page_import.open_input_folder_button.isEnabled())
        self.assertFalse(hasattr(window.page_import, "groups"))
        self.assertFalse(hasattr(window.page_import, "axis_combo"))

        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            source = directory / "case.msh"
            self._write_tetra(source)
            window.page_import.input_edit.setText(str(source))
            self.assertIsNotNone(window._inspect())
            self.assertIn("case.msh", window.page_import.info.toPlainText())
            self.assertNotIn('"cell_types"', window.page_import.info.toPlainText())
            self.assertTrue(window.page_import.open_input_folder_button.isEnabled())
            self.assertTrue(window.sidebar.buttons[Sidebar.PAGE_DATASET].isEnabled())
            mode_model = window.visualizer.combo_mode.model()
            self.assertTrue(
                mode_model.item(window.visualizer.combo_mode.findData("wireframe")).isEnabled()
            )
            self.assertFalse(
                mode_model.item(window.visualizer.combo_mode.findData("connections")).isEnabled()
            )
            self.assertIsNotNone(window._generate_dataset())
            self.assertEqual(window.model.dimension, 3)
            self.assertTrue((directory / "case.geofv.h5").is_file())
            self.assertIn("FV", window.page_dataset.output.toPlainText())
            self.assertNotIn('"connections"', window.page_dataset.output.toPlainText())
            self.assertNotIn("unassigned_boundaries", window.page_dataset.output.toPlainText())
            self.assertFalse(hasattr(window.page_dataset, "open_hdf5_button"))
            self.assertFalse(hasattr(window.page_dataset, "open_summary_button"))
            self.assertFalse(hasattr(window.page_dataset, "open_vtu_button"))
            self.assertTrue(window.page_dataset.open_folder_button.isEnabled())
            self.assertTrue(window.sidebar.buttons[Sidebar.PAGE_SOLVER].isEnabled())

            self.assertIsNotNone(window._confirm_solver("tough2-eco2m"))
            self._wait_worker(application, window._preparation_worker)
            self.assertTrue(window.sidebar.buttons[Sidebar.PAGE_MESH].isEnabled())
            self.assertEqual(window.page_mesh.source_combo.currentData(), "h5")
            prepared_model = window._prepared_solver_model
            prepared_index = window._boundary_selection_index
            preparation_generation = window._solver_task_generation
            window.page_mesh.source_combo.setCurrentIndex(
                window.page_mesh.source_combo.findData("msh")
            )
            application.processEvents()
            self.assertIs(window._prepared_solver_model, prepared_model)
            self.assertIs(window._boundary_selection_index, prepared_index)
            self.assertEqual(window._solver_task_generation, preparation_generation)
            self.assertIsNone(window._preparation_worker)
            window.page_mesh.source_combo.setCurrentIndex(
                window.page_mesh.source_combo.findData("h5")
            )
            application.processEvents()
            self.assertTrue(window.page_mesh.extrude_group.isEnabled())
            self.assertFalse(window.page_mesh.entry_height.isEnabled())
            self.assertFalse(hasattr(window.page_mesh, "open_mesh_button"))
            self.assertFalse(window.page_mesh.open_folder_button.isEnabled())
            self.assertFalse(window.page_mesh.chk_allow_unrepresented_connections.isChecked())
            material_mode = window.page_mesh.combo_selection_mode.findData(
                window.page_mesh.SELECTION_MATERIAL
            )
            window.page_mesh.combo_selection_mode.setCurrentIndex(material_mode)
            window.page_mesh.combo_inactive_material.setCurrentText("DEFAULT")
            window._update_selection_statistics()
            self.assertFalse(
                window.page_mesh.config()["allow_unrepresented_source_connections"]
            )
            window.page_mesh.chk_allow_unrepresented_connections.setChecked(True)
            self.assertTrue(
                window.page_mesh.config()["allow_unrepresented_source_connections"]
            )
            export_worker = window._generate_mesh()
            self.assertIsNotNone(export_worker)
            self._wait_worker(application, export_worker)
            manifest = window.solver_context.manifest
            self.assertTrue(
                manifest["source_connection_audit"]["ignore_was_explicitly_allowed"]
            )
            self.assertTrue((directory / "MESH").is_file())
            self.assertTrue((directory / "cell_map.csv").is_file())
            self.assertTrue((directory / "mesh_manifest.json").is_file())
            mesh_page_text = window.page_mesh.output.toPlainText()
            self.assertNotIn('"cell_labels"', mesh_page_text)
            self.assertIn("TOUGH2/ECO2M", mesh_page_text)
            self.assertIn("cell_map.csv", mesh_page_text)
            self.assertFalse((directory / "flow.inp").exists())
            self.assertFalse((directory / "INCON").exists())
            self.assertTrue(window.page_mesh.open_folder_button.isEnabled())
            self.assertTrue(window.sidebar.buttons[Sidebar.PAGE_INP].isEnabled())
            self.assertTrue(window.sidebar.buttons[Sidebar.PAGE_INCON].isEnabled())

            window.page_mesh.infinite_volume_edit.setText("9.9E49")
            self.assertIsNone(window.solver_context)
            self.assertFalse(window.sidebar.buttons[Sidebar.PAGE_INP].isEnabled())
            self.assertFalse(window.sidebar.buttons[Sidebar.PAGE_INCON].isEnabled())
            self.assertFalse(window.page_mesh.open_folder_button.isEnabled())

            window.visualizer.display_model(window.model, "boundaries")
            bundle = window.visualizer._bundle
            original_mesh = window.visualizer._mesh
            window.visualizer._mesh_mode = "2d"
            for bounds, expected in (
                ((0, 2, 0, 3, 0, 0), "xy"),
                ((0, 2, 0, 0, 0, 3), "xz"),
                ((0, 0, 0, 2, 0, 3), "yz"),
            ):
                window.visualizer._mesh = SimpleNamespace(bounds=bounds)
                self.assertEqual(window.visualizer._resolved_view_key(), expected)
            window.visualizer._mesh = original_mesh
            window.visualizer._mesh_mode = "3d"

            class FakePlotter:
                def __init__(self):
                    self.meshes = []
                    self.app_window = SimpleNamespace(setWindowTitle=lambda _title: None)

                def clear(self):
                    self.meshes.clear()

                def set_background(self, _color):
                    pass

                def add_mesh(self, mesh, **_kwargs):
                    self.meshes.append(mesh)

                def add_axes(self, **_kwargs):
                    pass

                def view_isometric(self):
                    pass

                def view_xy(self):
                    pass

                def view_xz(self):
                    pass

                def view_yz(self):
                    pass

                def reset_camera(self):
                    pass

                def update(self):
                    pass

                def close(self):
                    pass

            popout = FakePlotter()
            previous_plotter = window.visualizer.plotter
            camera_position = ((1.0, 2.0, 3.0), (0.0, 0.0, 0.0), (0.0, 0.0, 1.0))
            window.visualizer.plotter = SimpleNamespace(camera_position=camera_position)
            with patch("pyvistaqt.BackgroundPlotter", return_value=popout):
                window.visualizer._popout_view()
            window.visualizer.plotter = previous_plotter
            self.assertIs(popout.meshes[0], bundle.grid)
            self.assertIs(popout.meshes[1], bundle.overlay)
            self.assertEqual(popout.camera_position, camera_position)

            h5_path = directory / "case.geofv.h5"
            worker = window._load_dataset(str(h5_path))
            self.assertIsNotNone(worker)
            self.assertFalse(window.page_import.isEnabled())
            self.assertIsNone(window.model)
            self.assertFalse(window.sidebar.buttons[Sidebar.PAGE_DATASET].isEnabled())
            while worker.isRunning():
                application.processEvents()
            worker.wait()
            application.processEvents()
            self.assertTrue(window.page_import.isEnabled())
            self.assertTrue(window.model_path.samefile(h5_path))
            self.assertFalse(window.page_dataset.generate_button.isEnabled())
            self.assertTrue(window.sidebar.buttons[Sidebar.PAGE_SOLVER].isEnabled())

            second_source = directory / "case_b.msh"
            self._write_tetra(second_source)
            window.page_import.input_edit.setText(str(second_source))
            self.assertIsNone(window.inspection)
            self.assertIsNone(window.model)
            self.assertIsNone(window.model_path)
            self.assertFalse(window.sidebar.buttons[Sidebar.PAGE_DATASET].isEnabled())
            self.assertFalse(window.sidebar.buttons[Sidebar.PAGE_SOLVER].isEnabled())
        window.close()
        application.processEvents()

    def test_conversion_qprocess_can_be_cancelled(self):
        import sys
        import time

        from PySide6.QtCore import QEventLoop, QTimer
        from PySide6.QtWidgets import QApplication

        from geofvbridge.gui.conversion_process import ConversionProcess

        application = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            controller = ConversionProcess(
                directory / "dummy.msh",
                directory / "dummy.geofv.h5",
            )
            controller.process.setProgram(sys.executable)
            controller.process.setArguments(["-c", "import time; time.sleep(30)"])
            loop = QEventLoop()
            outcome = []
            controller.cancelled.connect(lambda: (outcome.append("cancelled"), loop.quit()))
            controller.failed.connect(lambda *_: (outcome.append("failed"), loop.quit()))
            QTimer.singleShot(6000, loop.quit)
            started = time.monotonic()
            controller.start()
            QTimer.singleShot(100, controller.cancel)
            loop.exec()
            application.processEvents()
            self.assertEqual(outcome, ["cancelled"])
            self.assertLess(time.monotonic() - started, 6.0)
            self.assertFalse(controller.staging_dir.exists())

    def test_conversion_qprocess_exposes_source_package_to_worker(self):
        from geofvbridge.gui.conversion_process import ConversionProcess

        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            controller = ConversionProcess(
                directory / "dummy.msh",
                directory / "dummy.geofv.h5",
            )
            package_root = Path(__file__).parents[1] / "src"
            python_path = controller.process.processEnvironment().value("PYTHONPATH")
            entries = {
                os.path.normcase(os.path.abspath(entry))
                for entry in python_path.split(os.pathsep)
                if entry
            }
            self.assertIn(os.path.normcase(os.path.abspath(package_root)), entries)
            controller._cleanup_staging()

    def test_lithology_filter_preserves_selection_across_fe_fv_views(self):
        from PySide6.QtWidgets import QApplication

        from geofvbridge.converter import convert_meshio
        from geofvbridge.gui.visualizer import Visualizer

        application = QApplication.instance() or QApplication([])
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
        source = meshio.Mesh(
            points,
            [("tetra", cells)],
            cell_data={"gmsh:physical": [np.array([1, 2])]},
            field_data={
                "ROCK_A": np.array([1, 3]),
                "ROCK_B": np.array([2, 3]),
            },
        )
        visualizer = Visualizer()
        visualizer.display_meshio(source, 3)
        self.assertEqual(visualizer.visible_materials, {"ROCK_A", "ROCK_B"})

        visualizer.set_visible_materials({"ROCK_A"})
        self.assertEqual(visualizer._mesh.n_cells, 1)
        self.assertIn("1/2", visualizer.status_label.text())

        model = convert_meshio(source)
        visualizer.display_model(model, "boundaries")
        self.assertEqual(visualizer.visible_materials, {"ROCK_A"})
        self.assertEqual(visualizer._bundle.grid.n_cells, 1)
        self.assertEqual(visualizer._bundle.overlay.n_cells, 3)
        np.testing.assert_array_equal(
            np.unique(visualizer._bundle.overlay.cell_data["owner_cell_id"]),
            [0],
        )

        visualizer.clear_display()
        visualizer.display_model(model, "material")
        self.assertEqual(visualizer.visible_materials, {"ROCK_A", "ROCK_B"})
        visualizer.close_plotter()
        visualizer.deleteLater()
        application.processEvents()

    def test_mesh_page_uses_one_selector_and_smart_defaults(self):
        from PySide6.QtWidgets import QApplication

        from geofvbridge.boundary_selection import build_boundary_selection_index
        from geofvbridge.converter import convert_meshio
        from geofvbridge.extrusion import extrude_meshio
        from geofvbridge.gui.pages.page_mesh import ToughMeshPage

        application = QApplication.instance() or QApplication([])
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

        page = ToughMeshPage()
        page.materials = ["ROCK", "BOUND"]
        page._populate_material_entries()
        index = build_boundary_selection_index(model)
        page.set_selection_index(index)
        self.assertEqual(page.combo_selection_mode.currentData(), page.SELECTION_MATERIAL)
        self.assertEqual(page.inactive_selection(), {"method": "material", "material": "BOUND"})

        page.combo_selection_mode.setCurrentIndex(
            page.combo_selection_mode.findData(page.SELECTION_BOUNDARY)
        )
        page.combo_boundary_group.setCurrentText("Top")
        config = page.config()
        self.assertEqual(
            config["inactive_selection"],
            {"method": "boundary_group", "boundary_group": "Top"},
        )
        self.assertFalse(
            any(
                key in config
                for key in ("inactive_cells", "inactive_materials", "inactive_z_min", "inactive_top")
            )
        )

        for cell in model.cells:
            cell.material = "ROCK"
        page.set_selection_index(build_boundary_selection_index(model))
        self.assertEqual(page.combo_selection_mode.currentData(), page.SELECTION_BOUNDARY)
        self.assertEqual(page.combo_boundary_group.currentText(), "Top")

        for boundary in model.boundaries:
            boundary.name = "UNASSIGNED"
        page.set_selection_index(build_boundary_selection_index(model))
        self.assertIsNone(page.combo_selection_mode.currentData())
        self.assertFalse(page.btn_preview.isEnabled())
        self.assertFalse(page.btn_generate.isEnabled())
        page.deleteLater()
        application.processEvents()

    def test_failed_h5_load_stays_on_import_page(self):
        from PySide6.QtWidgets import QApplication

        from geofvbridge.gui.app import MainWindow
        from geofvbridge.gui.sidebar import Sidebar

        application = QApplication.instance() or QApplication([])
        window = MainWindow()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "broken.geofv.h5"
            path.write_bytes(b"not an hdf5 file")
            window.page_import.input_edit.setText(str(path))
            with patch("geofvbridge.gui.app.QMessageBox.critical"):
                worker = window._load_dataset(str(path))
                self.assertIsNotNone(worker)
                worker.wait()
                application.processEvents()
                application.processEvents()
            self.assertIsNone(window.model)
            self.assertIsNone(window.model_path)
            self.assertEqual(window.page_stack.currentIndex(), Sidebar.PAGE_IMPORT)
            self.assertFalse(window.sidebar.buttons[Sidebar.PAGE_DATASET].isEnabled())
            self.assertFalse(window.sidebar.buttons[Sidebar.PAGE_SOLVER].isEnabled())
        window.close()
        application.processEvents()

    def test_run_all_stops_when_flow_input_fails(self):
        from PySide6.QtWidgets import QApplication

        from geofvbridge.gui.app import MainWindow

        application = QApplication.instance() or QApplication([])
        window = MainWindow()
        with (
            patch.object(window, "_generate_flow_input", return_value=None),
            patch.object(window, "_generate_incon") as generate_incon,
        ):
            window._run_all_pending = True
            window._finish_run_all_outputs()
        generate_incon.assert_not_called()
        self.assertFalse(window._run_all_pending)
        window.close()
        application.processEvents()

    def test_output_worker_success_error_and_shutdown_lifecycle(self):
        from PySide6.QtWidgets import QApplication

        from geofvbridge.gui.pages.page_out import OutPage

        application = QApplication.instance() or QApplication([])
        page = OutPage()
        page._out_path = "flow.out"
        page._mesh_path = "MESH"

        with (
            patch("geofvbridge.core.out.parse_mesh_coords", return_value=({"A": (0, 0, 0)}, ["A"])),
            patch("geofvbridge.core.out.parse_flow_out", return_value=[{"time": 0.0}]),
            patch("geofvbridge.core.out.write_tecplot", return_value=["result.dat"]),
        ):
            page._start_extraction()
            worker = page._worker
            worker.wait()
            application.processEvents()
            application.processEvents()
        self.assertIsNone(page._worker)
        self.assertTrue(page._btn_extract.isEnabled())
        self.assertIn("result.dat", page._result_text.toPlainText())

        page._btn_extract.setEnabled(True)
        with patch("geofvbridge.core.out.parse_mesh_coords", side_effect=RuntimeError("boom")):
            page._start_extraction()
            worker = page._worker
            worker.wait()
            application.processEvents()
            application.processEvents()
        self.assertIsNone(page._worker)
        self.assertTrue(page._btn_extract.isEnabled())
        self.assertIn("boom", page._result_text.toPlainText())

        fake_worker = Mock()
        fake_worker.isRunning.return_value = True
        page._worker = fake_worker
        page.shutdown()
        fake_worker.requestInterruption.assert_called_once_with()
        fake_worker.wait.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
