"""GeoFVBridge desktop application using the retained visual workspace shell."""

from __future__ import annotations

import os
import sys
import traceback
from copy import deepcopy
from pathlib import Path

os.environ.setdefault("QT_API", "pyside6")

if __package__ in {None, ""}:
    source_root = str(Path(__file__).resolve().parents[2])
    if source_root not in sys.path:
        sys.path.insert(0, source_root)

import meshio
import numpy as np
import qdarktheme
from PySide6.QtCore import QEventLoop, QProcess, QSize, Qt, QThread, QUrl, Signal
from PySide6.QtGui import QAction, QDesktopServices, QFont
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QSplitter,
    QStackedWidget,
    QStatusBar,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from geofvbridge.api import (
    DatasetArtifacts,
    convert_mesh,
    default_fv_dataset_path,
    export_solver_mesh,
    inspect_source,
    load_fv_dataset,
    prepare_solver_model,
    save_fv_dataset,
)
from geofvbridge.boundary_selection import (
    BoundarySelectionIndex,
    build_boundary_selection_index,
    selection_preview,
)
from geofvbridge.gui.console import LogConsole
from geofvbridge.gui.context import SolverMeshContext
from geofvbridge.gui.conversion_process import ConversionProcess
from geofvbridge.gui.pages import (
    DatasetPage,
    ImportPage,
    InconPage,
    InpPage,
    OutPage,
    SolverSelectionPage,
    ToughMeshPage,
)
from geofvbridge.gui.sidebar import Sidebar
from geofvbridge.gui.visualizer import Visualizer
from geofvbridge.i18n import get_language, set_language, tr
from geofvbridge.model import FVModel
from geofvbridge.styles import (
    APP_FULL_NAME,
    APP_NAME,
    APP_VERSION,
    CUSTOM_QSS,
    Colors,
    Fonts,
    Sizes,
)


def _t(chinese: str, english: str) -> str:
    return chinese if get_language() == "zh_CN" else english


class DatasetLoadWorker(QThread):
    """Read a GeoFV HDF5 model without blocking the Qt event loop."""

    loaded = Signal(object, str)
    failed = Signal(str, str)

    def __init__(self, path: Path, parent=None):
        super().__init__(parent)
        self.path = path

    def run(self):
        try:
            self.loaded.emit(load_fv_dataset(self.path), str(self.path))
        except Exception as error:
            self.failed.emit(str(error), traceback.format_exc())


class SolverPreparationWorker(QThread):
    """Prepare one solver model and its reusable boundary index."""

    prepared = Signal(int, object, object, str)
    failed = Signal(int, str, str)

    def __init__(self, generation: int, native, source: Path, extrusion, parent=None):
        super().__init__(parent)
        self.generation = generation
        self.native = native
        self.source = source
        self.extrusion = extrusion

    def run(self):
        try:
            model = prepare_solver_model(self.native, self.extrusion)
            index = build_boundary_selection_index(model)
            self.prepared.emit(self.generation, model, index, str(self.source))
        except Exception as error:
            self.failed.emit(self.generation, str(error), traceback.format_exc())


class MeshPreviewWorker(QThread):
    """Resolve one cached selection without constructing TOUGH export records."""

    previewed = Signal(int, object, object)
    failed = Signal(int, str, str)

    def __init__(
        self,
        generation: int,
        model: FVModel,
        selection: dict,
        index: BoundarySelectionIndex,
        parent=None,
    ):
        super().__init__(parent)
        self.generation = generation
        self.model = model
        self.selection = deepcopy(selection)
        self.index = index

    def run(self):
        try:
            result, report = selection_preview(
                self.model,
                self.selection,
                self.index,
                sample_limit=20,
            )
            self.previewed.emit(self.generation, result, report)
        except Exception as error:
            self.failed.emit(self.generation, str(error), traceback.format_exc())


class MeshExportWorker(QThread):
    """Write MESH and its manifests without blocking the GUI thread."""

    exported = Signal(int, object, object, str, str, object)
    failed = Signal(int, str, str)

    def __init__(
        self,
        generation: int,
        model: FVModel,
        backend: str,
        config: dict,
        output: Path,
        source: Path,
        parent=None,
    ):
        super().__init__(parent)
        self.generation = generation
        self.model = model
        self.backend = backend
        self.config = deepcopy(config)
        self.output = output
        self.source = source

    def run(self):
        try:
            manifest = export_solver_mesh(
                self.model,
                self.backend,
                self.config,
                self.output,
            )
            self.exported.emit(
                self.generation,
                manifest,
                self.model,
                str(self.source),
                str(self.output),
                self.config,
            )
        except Exception as error:
            self.failed.emit(self.generation, str(error), traceback.format_exc())


class GeoFVBridgeMainWindow(QMainWindow):
    """Seven-stage FE → FV → solver workflow in the original GUI shell."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} — {APP_FULL_NAME}")
        self.resize(1400, 900)
        self.setMinimumSize(1100, 700)

        self.inspection: dict | None = None
        self.msh_path: Path | None = None
        self.source_path: Path | None = None
        self.model: FVModel | None = None
        self.model_path: Path | None = None
        self.artifacts: DatasetArtifacts | None = None
        self.dataset_source_kind: str | None = None
        self.selected_backend: str | None = None
        self.solver_context: SolverMeshContext | None = None
        self.inactive_cells: set[int] = set()
        self.inactive_faces: set[int] = set()
        self._prepared_solver_model: FVModel | None = None
        self._boundary_selection_index: BoundarySelectionIndex | None = None
        self._prepared_source: Path | None = None
        self._latest_preparation_source: Path | None = None
        self._preparation_key: tuple | None = None
        self._solver_task_generation = 0
        self._preview_generation = 0
        self._export_generation = 0
        self._preparation_worker: SolverPreparationWorker | None = None
        self._preview_worker: MeshPreviewWorker | None = None
        self._export_worker: MeshExportWorker | None = None
        self._pending_preparation = False
        self._run_all_pending = False
        self._load_worker: DatasetLoadWorker | None = None
        self._conversion_process: ConversionProcess | None = None
        self._loading_cursor_active = False
        self._setting_input_path = False

        self._setup_menubar()
        self._setup_toolbar()
        self._setup_ui()
        self._connect_signals()
        self._reset_navigation()
        self.console.log("=" * 58, "DEBUG")
        self.console.log(f"{APP_NAME} v{APP_VERSION}", "INFO")
        self.console.log("Gmsh → native FV dataset → solver mesh → TOUGH files", "INFO")
        self.console.log("=" * 58, "DEBUG")

    def _setup_menubar(self):
        file_menu = self.menuBar().addMenu(tr("menu.file.title"))
        open_action = QAction(tr("menu.file.open_msh"), self)
        open_action.setShortcut("Ctrl+O")
        open_action.triggered.connect(self._action_open)
        file_menu.addAction(open_action)
        load_action = QAction(_t("打开 FV 数据集", "Open FV dataset"), self)
        load_action.triggered.connect(self._action_load_dataset)
        file_menu.addAction(load_action)
        file_menu.addSeparator()
        quit_action = QAction(tr("menu.file.quit"), self)
        quit_action.setShortcut("Ctrl+Q")
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

        settings = self.menuBar().addMenu(tr("menu.settings.title"))
        language = settings.addMenu(tr("menu.settings.language"))
        chinese = QAction(tr("language.chinese"), self)
        chinese.triggered.connect(lambda: self._change_language("zh_CN"))
        english = QAction(tr("language.english"), self)
        english.triggered.connect(lambda: self._change_language("en_US"))
        language.addActions([chinese, english])
        help_menu = self.menuBar().addMenu(tr("menu.help.title"))
        about = QAction(tr("menu.help.about"), self)
        about.triggered.connect(self._show_about)
        help_menu.addAction(about)

    def _setup_toolbar(self):
        toolbar = QToolBar(tr("toolbar.title"))
        toolbar.setMovable(False)
        toolbar.setIconSize(QSize(Sizes.ICON_SIZE, Sizes.ICON_SIZE))
        toolbar.setFixedHeight(Sizes.TOOLBAR_H)
        toolbar.setStyleSheet(
            f"background-color:{Colors.BG_PANEL};border-bottom:1px solid {Colors.BORDER};"
        )
        open_action = QAction(tr("toolbar.open"), self)
        open_action.triggered.connect(self._action_open)
        toolbar.addAction(open_action)
        run_action = QAction(tr("toolbar.generate_all"), self)
        run_action.triggered.connect(self._action_run_all)
        toolbar.addAction(run_action)
        toolbar.addSeparator()
        self.info_label = QLabel("  " + tr("app.no_file_loaded"))
        self.info_label.setStyleSheet(f"color:{Colors.TEXT_DIM};font-size:{Fonts.SIZE_S}pt;")
        toolbar.addWidget(self.info_label)
        self.addToolBar(toolbar)

    def _setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        vertical = QSplitter(Qt.Vertical)
        work = QWidget()
        work_layout = QHBoxLayout(work)
        work_layout.setContentsMargins(0, 0, 0, 0)
        work_layout.setSpacing(0)
        self.sidebar = Sidebar()
        work_layout.addWidget(self.sidebar)
        horizontal = QSplitter(Qt.Horizontal)
        self.page_stack = QStackedWidget()
        self.page_import = ImportPage()
        self.page_dataset = DatasetPage()
        self.page_solver = SolverSelectionPage()
        self.page_mesh = ToughMeshPage()
        self.page_inp = InpPage()
        self.page_incon = InconPage()
        self.page_out = OutPage()
        for page in (
            self.page_import,
            self.page_dataset,
            self.page_solver,
            self.page_mesh,
            self.page_inp,
            self.page_incon,
            self.page_out,
        ):
            self.page_stack.addWidget(page)
        horizontal.addWidget(self.page_stack)
        self.visualizer = Visualizer()
        horizontal.addWidget(self.visualizer)
        horizontal.setSizes([650, 500])
        horizontal.setStretchFactor(0, 6)
        horizontal.setStretchFactor(1, 4)
        work_layout.addWidget(horizontal)
        vertical.addWidget(work)
        self.console = LogConsole()
        vertical.addWidget(self.console)
        vertical.setSizes([700, Sizes.CONSOLE_H])
        vertical.setStretchFactor(0, 7)
        vertical.setStretchFactor(1, 2)
        root.addWidget(vertical)
        status = QStatusBar()
        status.setStyleSheet(f"font-size:{Fonts.SIZE_S}pt;color:{Colors.TEXT_DIM};")
        status.showMessage(f"{APP_NAME} v{APP_VERSION} · {tr('common.ready')}")
        self.setStatusBar(status)

    def _connect_signals(self):
        self.sidebar.page_changed.connect(self.page_stack.setCurrentIndex)
        self.page_import.input_changed.connect(self._input_path_changed)
        self.page_import.inspect_requested.connect(self._inspect)
        self.page_import.load_dataset_requested.connect(self._load_dataset)
        self.page_import.open_requested.connect(self._open_workflow_path)
        self.page_dataset.generate_requested.connect(self._generate_dataset)
        self.page_dataset.cancel_requested.connect(self._cancel_conversion)
        self.page_dataset.open_requested.connect(self._open_workflow_path)
        self.page_solver.selection_confirmed.connect(self._confirm_solver)
        self.page_mesh.preview_requested.connect(self._preview_mesh)
        self.page_mesh.generate_requested.connect(self._generate_mesh)
        self.page_mesh.config_changed.connect(self._solver_mesh_config_changed)
        self.page_mesh.preparation_changed.connect(self._request_solver_preparation)
        self.page_mesh.selection_changed.connect(self._update_selection_statistics)
        self.page_mesh.open_requested.connect(self._open_workflow_path)
        self.page_inp.inp_generated.connect(self._generate_flow_input)
        self.page_incon.incon_generated.connect(self._generate_incon)

    def _reset_navigation(self):
        self.sidebar.set_page_enabled(Sidebar.PAGE_DATASET, False)
        self.sidebar.set_page_enabled(Sidebar.PAGE_SOLVER, False)
        self.sidebar.set_page_enabled(Sidebar.PAGE_MESH, False)
        self.sidebar.set_page_enabled(Sidebar.PAGE_INP, False)
        self.sidebar.set_page_enabled(Sidebar.PAGE_INCON, False)
        self.sidebar.set_page_enabled(Sidebar.PAGE_OUT, True)
        self.sidebar.set_active(Sidebar.PAGE_IMPORT)
        self.page_stack.setCurrentIndex(Sidebar.PAGE_IMPORT)

    def _set_input_path(self, path: Path) -> None:
        self._setting_input_path = True
        try:
            self.page_import.input_edit.setText(str(path))
        finally:
            self._setting_input_path = False

    def _clear_solver_mesh_state(self, *, mark_stale: bool = False) -> None:
        had_output = self.solver_context is not None or bool(
            self.page_mesh.output.toPlainText().strip()
        )
        self.solver_context = None
        self.inactive_cells.clear()
        self.inactive_faces.clear()
        self.sidebar.set_page_enabled(Sidebar.PAGE_INP, False)
        self.sidebar.set_page_enabled(Sidebar.PAGE_INCON, False)
        self.page_inp.reset_mesh_context()
        self.page_incon.reset_mesh_context()
        if mark_stale and had_output:
            self.page_mesh.mark_output_stale()

    def _clear_prepared_solver_state(self) -> None:
        self._solver_task_generation += 1
        self._prepared_solver_model = None
        self._boundary_selection_index = None
        self._prepared_source = None
        self._latest_preparation_source = None
        self._preparation_key = None
        self._pending_preparation = False
        self.inactive_cells.clear()
        self.inactive_faces.clear()
        self.page_mesh.selection_index = None
        self.page_mesh.set_selection_ready(False)

    def _invalidate_workflow_for_input(self) -> None:
        self.inspection = None
        self.msh_path = None
        self.source_path = None
        self.model = None
        self.model_path = None
        self.artifacts = None
        self.dataset_source_kind = None
        self.selected_backend = None
        self.page_import.clear_inspection()
        self.page_dataset.clear_model()
        self.page_solver.clear_selection()
        self.page_mesh.clear_output()
        self._clear_solver_mesh_state()
        self._clear_prepared_solver_state()
        for page in (
            Sidebar.PAGE_DATASET,
            Sidebar.PAGE_SOLVER,
            Sidebar.PAGE_MESH,
        ):
            self.sidebar.set_page_enabled(page, False)
        self.info_label.setText("  " + tr("app.no_file_loaded"))
        self.visualizer.clear_display()

    def _input_path_changed(self, _raw_path: str) -> None:
        if not self._setting_input_path:
            self._invalidate_workflow_for_input()

    def _solver_mesh_config_changed(self) -> None:
        self._preview_generation += 1
        self._export_generation += 1
        self._clear_solver_mesh_state(mark_stale=True)

    def _guard(self, action, message: str):
        try:
            self.statusBar().showMessage(message)
            result = action()
            self.statusBar().showMessage(tr("common.ready"), 5000)
            return result
        except Exception as error:
            self.console.log(f"{message}: {error}", "ERROR")
            traceback.print_exc()
            self.statusBar().showMessage(_t("失败", "Failed"), 5000)
            QMessageBox.critical(self, APP_NAME, str(error))
            return None

    def _go_to(self, page: int):
        self.sidebar.set_active(page)
        self.page_stack.setCurrentIndex(page)

    def _inspect(self, raw_path: str | None = None):
        def action():
            path = Path(raw_path or self.page_import.input_edit.text().strip())
            if not path.exists():
                raise FileNotFoundError(_t("请选择有效的网格输入。", "Select a valid grid input."))
            self._invalidate_workflow_for_input()
            self.inspection = inspect_source(path)
            self.source_path = path.resolve()
            self.dataset_source_kind = str(self.inspection.get("input_kind", "mesh"))
            self.msh_path = self.source_path if self.dataset_source_kind == "mesh" else None
            self.page_import.set_inspection(self.inspection)
            self.sidebar.set_page_enabled(Sidebar.PAGE_DATASET, True)
            self.page_dataset.set_generation_enabled(True)
            for page in (Sidebar.PAGE_SOLVER, Sidebar.PAGE_MESH, Sidebar.PAGE_INP, Sidebar.PAGE_INCON):
                self.sidebar.set_page_enabled(page, False)
            if self.dataset_source_kind == "mesh":
                self.visualizer.display_meshio(
                    meshio.read(path), int(self.inspection["dimension"])
                )
                self.info_label.setText(
                    f"  {path.name} | {self.inspection['points']:,} points | "
                    f"{self.inspection['dimension']}D FE mesh"
                )
                detail = self.inspection["cell_types"]
            else:
                self.visualizer.clear_display()
                dimensions = "×".join(str(value) for value in self.inspection["dimensions"])
                self.info_label.setText(
                    f"  {path.name} | {self.inspection['active_cells']:,} active cells | "
                    f"{dimensions} Petrel grid"
                )
                detail = {
                    "dimensions": self.inspection["dimensions"],
                    "active_cells": self.inspection["active_cells"],
                }
            self.console.log(f"Inspected {path.name}: {detail}", "SUCCESS")
            return self.inspection

        return self._guard(action, _t("正在检查网格输入", "Inspecting grid input"))

    def _load_dataset(self, raw_path: str | None = None):
        path = Path(raw_path or self.page_import.input_edit.text().strip())
        if not path.is_file() or not path.name.lower().endswith((".geofv.h5", ".h5")):
            self._dataset_load_failed(
                _t("请选择现有 .geofv.h5 文件。", "Select an existing .geofv.h5 file."), ""
            )
            return None
        if self._load_worker is not None and self._load_worker.isRunning():
            self.console.log(_t("已有数据集正在载入。", "A dataset is already loading."), "WARNING")
            return self._load_worker
        message = _t("正在后台载入 FV 数据集", "Loading FV dataset in background")
        self._invalidate_workflow_for_input()
        self._go_to(Sidebar.PAGE_IMPORT)
        self.statusBar().showMessage(message)
        self.console.log(f"{message}: {path}", "INFO")
        self.page_import.setEnabled(False)
        QApplication.setOverrideCursor(Qt.WaitCursor)
        self._loading_cursor_active = True
        worker = DatasetLoadWorker(path, self)
        self._load_worker = worker
        worker.loaded.connect(self._dataset_load_succeeded)
        worker.failed.connect(self._dataset_load_failed)
        worker.finished.connect(self._dataset_load_finished)
        worker.start()
        return worker

    def _dataset_load_succeeded(self, model: FVModel, raw_path: str):
        try:
            path = Path(raw_path).resolve()
            self.model = model
            self.model_path = path
            self.dataset_source_kind = "h5"
            base = path.name[: -len(".geofv.h5")] if path.name.lower().endswith(".geofv.h5") else path.stem
            self.artifacts = DatasetArtifacts(
                path,
                path.with_name(base + ".summary.json"),
                path.with_name(base + ".vtu"),
            )
            source = model.source_path
            self.source_path = source.resolve() if source and source.exists() else None
            self.msh_path = (
                source.resolve()
                if source and source.is_file() and source.suffix.lower() == ".msh"
                else None
            )
            self.inspection = None
            self._set_input_path(path)
            self.page_import.set_input_ready(True)
            self._on_native_model_ready()
            self.statusBar().showMessage(tr("common.ready"), 5000)
        except Exception as error:
            self._dataset_load_failed(str(error), traceback.format_exc())

    def _dataset_load_failed(self, message: str, details: str):
        self._invalidate_workflow_for_input()
        self._go_to(Sidebar.PAGE_IMPORT)
        self.console.log(f"{_t('FV 数据集载入失败', 'FV dataset loading failed')}: {message}", "ERROR")
        if details:
            self.console.log(details, "DEBUG")
        self.statusBar().showMessage(_t("载入失败", "Loading failed"), 5000)
        QMessageBox.critical(self, APP_NAME, message)

    def _dataset_load_finished(self):
        self.page_import.setEnabled(True)
        if self._loading_cursor_active:
            QApplication.restoreOverrideCursor()
            self._loading_cursor_active = False
        worker = self._load_worker
        self._load_worker = None
        if worker is not None:
            worker.deleteLater()

    def _generate_dataset_legacy(self):
        def action():
            path = Path(self.page_import.input_edit.text().strip())
            if not path.is_file() or path.suffix.lower() != ".msh":
                raise FileNotFoundError(_t("请选择现有 Gmsh MSH 文件。", "Select an existing Gmsh MSH file."))
            path = path.resolve()
            if self.msh_path is None or self.msh_path.resolve() != path or self.inspection is None:
                raise ValueError(
                    _t(
                        "\u8bf7\u5148\u68c0\u67e5\u5f53\u524d MSH \u6587\u4ef6\u3002",
                        "Inspect the currently selected MSH file first.",
                    )
                )
            self.msh_path = path
            self.page_import.set_inspection(self.inspection)
            self.model = convert_mesh(path)
            self.dataset_source_kind = "msh"
            self.artifacts = save_fv_dataset(self.model, default_fv_dataset_path(path))
            self.model_path = self.artifacts.hdf5.resolve()
            self._on_native_model_ready()
            return self.model

        return self._guard(action, _t("正在生成原维度 FV 数据集", "Generating native FV dataset"))

    def _generate_dataset(self):
        def action():
            path = Path(self.page_import.input_edit.text().strip())
            if not path.exists():
                raise FileNotFoundError(
                    _t("请选择现有网格输入。", "Select an existing grid input.")
                )
            path = path.resolve()
            if (
                self.source_path is None
                or self.source_path.resolve() != path
                or self.inspection is None
            ):
                raise ValueError(
                    _t(
                        "请先检查当前网格输入。",
                        "Inspect the currently selected grid input first.",
                    )
                )
            self.page_import.set_inspection(self.inspection)
            output = default_fv_dataset_path(path)
            petrel_options = (
                self.page_import.petrel_options()
                if self.dataset_source_kind == "petrel"
                else {}
            )
            process = ConversionProcess(
                path,
                output,
                petrel_options=petrel_options,
                parent=self,
            )
            self._conversion_process = process
            loop = QEventLoop(self)
            outcome: dict[str, object] = {}

            def completed(result):
                outcome["result"] = result
                loop.quit()

            def failed(message, details):
                outcome["error"] = message
                outcome["details"] = details
                loop.quit()

            def cancelled():
                outcome["cancelled"] = True
                loop.quit()

            process.progress.connect(self.page_dataset.set_progress)
            process.completed.connect(completed)
            process.failed.connect(failed)
            process.cancelled.connect(cancelled)
            self.page_dataset.set_conversion_running(True)
            self.console.log(f"Conversion worker started: {path}", "INFO")
            try:
                process.start()
                loop.exec()
            finally:
                self.page_dataset.set_conversion_running(False)
                self._conversion_process = None
                process.deleteLater()

            if outcome.get("cancelled"):
                self.page_dataset.set_generation_enabled(True)
                self.console.log(
                    "Conversion cancelled; previous dataset was kept.", "WARNING"
                )
                return None
            if "error" in outcome:
                details = str(outcome.get("details", ""))
                if details:
                    self.console.log(details, "DEBUG")
                raise RuntimeError(str(outcome["error"]))
            result = dict(outcome["result"])
            self.model_path = Path(str(result["model"])).resolve()
            self.artifacts = DatasetArtifacts(
                self.model_path,
                Path(str(result["summary"])).resolve(),
                Path(str(result["vtu"])).resolve(),
            )
            self.model = load_fv_dataset(self.model_path)
            self.msh_path = path if self.dataset_source_kind == "mesh" else None
            self._on_native_model_ready()
            return self.model

        return self._guard(
            action,
            _t("正在后台生成 FV 数据集", "Generating FV dataset in a worker process"),
        )

    def _cancel_conversion(self):
        if self._conversion_process is not None:
            self._conversion_process.cancel()

    def _on_native_model_ready(self):
        assert self.model is not None
        self.page_dataset.show_model(self.model, self.artifacts)
        self.page_dataset.set_generation_enabled(
            self.dataset_source_kind in {"mesh", "msh", "petrel"}
        )
        self.visualizer.display_model(self.model, "material")
        materials = list(dict.fromkeys(cell.material for cell in self.model.cells))
        self.info_label.setText(
            f"  {len(self.model.cells):,} FV cells | {len(self.model.connections):,} connections | "
            f"{self.model.dimension}D | {', '.join(materials)}"
        )
        ready = bool(self.model.report.valid and self.model_path and self.model_path.is_file())
        self.sidebar.set_page_enabled(Sidebar.PAGE_DATASET, True)
        self.sidebar.set_page_enabled(Sidebar.PAGE_SOLVER, ready)
        for page in (Sidebar.PAGE_MESH, Sidebar.PAGE_INP, Sidebar.PAGE_INCON):
            self.sidebar.set_page_enabled(page, False)
        self.selected_backend = None
        self.page_solver.clear_selection()
        self.page_mesh.clear_output()
        self._clear_solver_mesh_state()
        level = "SUCCESS" if ready else "ERROR"
        self.console.log(
            f"Native FV dataset ready: dimension={self.model.dimension}, valid={self.model.report.valid}",
            level,
        )
        self._go_to(Sidebar.PAGE_DATASET)

    def _confirm_solver(self, backend: str):
        def action():
            if self.model is None or self.model_path is None or not self.model.report.valid:
                raise ValueError(_t("请先保存有效的 FV 数据集。", "Save a valid FV dataset first."))
            self._clear_solver_mesh_state()
            self._clear_prepared_solver_state()
            self.page_mesh.clear_output()
            self.selected_backend = backend
            materials = list(dict.fromkeys(cell.material for cell in self.model.cells))
            self.page_mesh.set_sources(
                self.model_path,
                self.msh_path,
                self.model.dimension,
                materials,
            )
            self.page_solver.show_selection(backend)
            self.sidebar.set_page_enabled(Sidebar.PAGE_MESH, True)
            self.sidebar.set_page_enabled(Sidebar.PAGE_INP, False)
            self.sidebar.set_page_enabled(Sidebar.PAGE_INCON, False)
            self._go_to(Sidebar.PAGE_MESH)
            self._request_solver_preparation()
            return backend

        return self._guard(action, _t("正在确认求解器", "Confirming solver"))

    def _native_source_for_solver(self) -> tuple[FVModel | Path, Path]:
        source = self.page_mesh.source_path()
        if source is None or not source.is_file():
            raise FileNotFoundError(_t("所选求解器网格来源不存在。", "The selected solver source does not exist."))
        resolved = source.resolve()
        current_paths = {
            path.resolve()
            for path in (self.model_path, self.msh_path, self.source_path)
            if path is not None and path.exists()
        }
        if self.model is not None and resolved in current_paths:
            return self.model, resolved
        return resolved, resolved

    def _solver_preparation_signature(self, native, extrusion) -> tuple:
        extrusion_key = None
        if extrusion is not None:
            extrusion_key = (tuple(extrusion.direction), tuple(extrusion.layer_thicknesses))
        native_key = id(native) if isinstance(native, FVModel) else str(Path(native).resolve())
        return native_key, extrusion_key

    def _request_solver_preparation(self, *_args):
        try:
            native, source = self._native_source_for_solver()
            extrusion = self.page_mesh.extrusion()
            key = self._solver_preparation_signature(native, extrusion)
        except Exception as error:
            self.page_mesh.set_selection_summary(error=str(error))
            return None
        self._latest_preparation_source = source
        if self._prepared_solver_model is not None and key == self._preparation_key:
            self._prepared_source = source
            self.page_mesh.set_solver_mesh_info(self._prepared_solver_model)
            self._update_selection_statistics()
            return self._prepared_solver_model
        if self._preparation_worker is not None:
            if key == self._preparation_key:
                return self._preparation_worker
            self._pending_preparation = True
            self._solver_task_generation += 1
            self.page_mesh.set_task_busy(
                True,
                _t("等待当前任务结束后准备最新求解器网格……", "Waiting to prepare the latest solver mesh…"),
            )
            return self._preparation_worker
        self._solver_task_generation += 1
        generation = self._solver_task_generation
        self._pending_preparation = False
        self._prepared_solver_model = None
        self._boundary_selection_index = None
        self._prepared_source = None
        self._preparation_key = key
        message = _t("正在后台准备求解器网格和边界索引……", "Preparing solver mesh and boundary index in background…")
        self.page_mesh.set_task_busy(True, message)
        self.statusBar().showMessage(message)
        worker = SolverPreparationWorker(generation, native, source, extrusion, self)
        self._preparation_worker = worker
        worker.prepared.connect(self._solver_preparation_succeeded)
        worker.failed.connect(self._solver_preparation_failed)
        worker.finished.connect(self._solver_preparation_finished)
        worker.start()
        return worker

    def _solver_preparation_succeeded(
        self,
        generation: int,
        model: FVModel,
        index: BoundarySelectionIndex,
        raw_source: str,
    ) -> None:
        if generation != self._solver_task_generation:
            return
        self._prepared_solver_model = model
        self._boundary_selection_index = index
        self._prepared_source = self._latest_preparation_source or Path(raw_source)
        self.page_mesh.set_solver_mesh_info(model)
        self.page_mesh.set_selection_index(index)
        self._update_selection_statistics()
        self.page_mesh.set_task_busy(False)
        self.statusBar().showMessage(tr("common.ready"), 5000)
        self.console.log(
            f"Solver mesh ready: {len(model.cells):,} cells; "
            f"{len(index.boundary_groups):,} boundary groups",
            "SUCCESS",
        )
        if self._run_all_pending:
            self._generate_mesh()

    def _solver_preparation_failed(self, generation: int, message: str, details: str) -> None:
        if generation != self._solver_task_generation:
            return
        self._prepared_solver_model = None
        self._boundary_selection_index = None
        self.page_mesh.set_task_busy(False)
        self.page_mesh.set_selection_summary(error=message)
        self.console.log(f"Solver mesh preparation failed: {message}", "ERROR")
        self.console.log(details, "DEBUG")
        self.statusBar().showMessage(_t("准备失败", "Preparation failed"), 5000)
        self._run_all_pending = False

    def _solver_preparation_finished(self) -> None:
        worker = self._preparation_worker
        self._preparation_worker = None
        if worker is not None:
            worker.deleteLater()
        if self._pending_preparation:
            self._pending_preparation = False
            self._request_solver_preparation()
        else:
            self._set_mesh_task_idle_if_possible()

    def _set_mesh_task_idle_if_possible(self) -> None:
        """Restore Stage 4 actions after the last background task exits."""
        workers = (
            self._preparation_worker,
            self._preview_worker,
            self._export_worker,
        )
        if not any(worker is not None and worker.isRunning() for worker in workers):
            self.page_mesh.set_task_busy(False)

    def _update_selection_statistics(self, *_args) -> None:
        if self._prepared_solver_model is None or self._boundary_selection_index is None:
            return
        try:
            _, report = selection_preview(
                self._prepared_solver_model,
                self.page_mesh.inactive_selection(),
                self._boundary_selection_index,
                sample_limit=0,
            )
            self.page_mesh.set_selection_summary(report)
        except Exception as error:
            self.page_mesh.set_selection_summary(error=str(error))

    def _solver_visual_model(self, prepared: FVModel) -> FVModel:
        preparation = prepared.metadata.get("solver_preparation", {})
        if (
            preparation.get("mode") == "direct_3d"
            and self.model is not None
            and len(self.model.cells) == len(prepared.cells)
        ):
            return self.model
        return prepared

    def _preview_mesh(self):
        if self._prepared_solver_model is None or self._boundary_selection_index is None:
            return self._request_solver_preparation()
        try:
            selection = self.page_mesh.inactive_selection()
        except Exception as error:
            self.page_mesh.set_selection_summary(error=str(error))
            return None
        if self._preview_worker is not None:
            self.console.log(_t("边界预览正在进行。", "A boundary preview is already running."), "WARNING")
            return self._preview_worker
        self._preview_generation += 1
        generation = self._preview_generation
        message = _t("正在后台计算无限体积单元……", "Resolving infinite-volume cells in background…")
        self.page_mesh.set_task_busy(True, message)
        worker = MeshPreviewWorker(
            generation,
            self._prepared_solver_model,
            selection,
            self._boundary_selection_index,
            self,
        )
        self._preview_worker = worker
        worker.previewed.connect(self._mesh_preview_succeeded)
        worker.failed.connect(self._mesh_preview_failed)
        worker.finished.connect(self._mesh_preview_finished)
        worker.start()
        return worker

    def _mesh_preview_succeeded(self, generation: int, result, report: dict) -> None:
        if generation != self._preview_generation:
            return
        self.inactive_cells = {int(value) for value in result.cell_ids}
        self.inactive_faces = {int(value) for value in result.face_ids}
        report = {
            **report,
            "boundary_count": report.get("inactive_count", 0),
            "boundary_cells": [
                {
                    "cell_id": item["cell_id"],
                    "material": item["material"],
                    "centroid": item["centroid"],
                    "reasons": [f"{result.method}:{result.label}"],
                }
                for item in report.get("sample_cells", [])
            ],
        }
        report["inactive_cells"] = list(report["boundary_cells"])
        self.page_mesh.set_selection_summary(report)
        self.page_mesh.show_json(report)
        self.visualizer.display_model(
            self._solver_visual_model(self._prepared_solver_model),
            "tough_inactive",
            self.inactive_cells,
            self.inactive_faces,
        )
        self.page_mesh.set_task_busy(False)
        self.statusBar().showMessage(tr("common.ready"), 5000)

    def _mesh_preview_failed(self, generation: int, message: str, details: str) -> None:
        if generation != self._preview_generation:
            return
        self.page_mesh.set_task_busy(False)
        self.page_mesh.set_selection_summary(error=message)
        self.console.log(f"Boundary preview failed: {message}", "ERROR")
        self.console.log(details, "DEBUG")

    def _mesh_preview_finished(self) -> None:
        worker = self._preview_worker
        self._preview_worker = None
        if worker is not None:
            worker.deleteLater()
        self._set_mesh_task_idle_if_possible()

    def _generate_mesh(self):
        if not self.selected_backend:
            QMessageBox.warning(self, APP_NAME, _t("请先确认求解器。", "Confirm a solver first."))
            return None
        if self._prepared_solver_model is None or self._prepared_source is None:
            return self._request_solver_preparation()
        if self._export_worker is not None:
            self.console.log(_t("MESH 正在后台生成。", "MESH generation is already running."), "WARNING")
            return self._export_worker
        try:
            config = self.page_mesh.config()
            output_text = self.page_mesh.output_edit.text().strip()
            output = Path(output_text) if output_text else self._prepared_source.parent
        except Exception as error:
            self.page_mesh.set_selection_summary(error=str(error))
            self._run_all_pending = False
            return None
        self._export_generation += 1
        generation = self._export_generation
        self._clear_solver_mesh_state()
        message = _t("正在后台生成 TOUGH MESH……", "Generating TOUGH MESH in background…")
        self.page_mesh.set_task_busy(True, message)
        worker = MeshExportWorker(
            generation,
            self._prepared_solver_model,
            self.selected_backend,
            config,
            output,
            self._prepared_source,
            self,
        )
        self._export_worker = worker
        worker.exported.connect(self._mesh_export_succeeded)
        worker.failed.connect(self._mesh_export_failed)
        worker.finished.connect(self._mesh_export_finished)
        worker.start()
        return worker

    def _mesh_export_succeeded(
        self,
        generation: int,
        manifest: dict,
        model: FVModel,
        raw_source: str,
        raw_output: str,
        config: dict,
    ) -> None:
        if generation != self._export_generation:
            return
        source = Path(raw_source)
        output = Path(raw_output)
        self.solver_context = SolverMeshContext.from_export(
            model,
            self.selected_backend or "tough2-eco2m",
            source,
            output,
            config,
            manifest,
        )
        legacy = self.solver_context.legacy
        materials = list(dict.fromkeys(legacy.materials.tolist()))
        self.page_inp.populate_rocks(materials)
        self.page_inp.set_mesh_data(legacy)
        self.page_incon.populate_materials(materials)
        z_values = legacy.centers[:, 2]
        self.page_incon.set_reservoir_depth(float(np.max(z_values)), float(np.min(z_values)))
        self.page_incon.enable_generation()
        self.page_mesh.set_output_path(output)
        self.page_mesh.show_json(manifest)
        self.page_mesh.set_output_ready(True)
        selected = manifest.get("inactive_cells", [])
        self.inactive_cells = {int(item["cell_id"]) for item in selected}
        if self._boundary_selection_index is not None:
            try:
                result, _ = selection_preview(
                    model,
                    config["inactive_selection"],
                    self._boundary_selection_index,
                    sample_limit=0,
                )
                self.inactive_faces = {int(value) for value in result.face_ids}
            except Exception:
                self.inactive_faces.clear()
        self.visualizer.display_model(
            self._solver_visual_model(model),
            "tough_inactive",
            self.inactive_cells,
            self.inactive_faces,
        )
        self.sidebar.set_page_enabled(Sidebar.PAGE_INP, True)
        self.sidebar.set_page_enabled(Sidebar.PAGE_INCON, True)
        self.page_mesh.set_task_busy(False)
        self.console.log(f"Generated MESH and cell_map.csv in {output}", "SUCCESS")
        self.statusBar().showMessage(tr("common.ready"), 5000)
        if self._run_all_pending:
            self._finish_run_all_outputs()

    def _finish_run_all_outputs(self) -> None:
        """Finish the one-click workflow, stopping at the first failed file."""
        self._run_all_pending = False
        if self._generate_flow_input() is not None:
            self._generate_incon()

    def _mesh_export_failed(self, generation: int, message: str, details: str) -> None:
        if generation != self._export_generation:
            return
        self.page_mesh.set_task_busy(False)
        self.console.log(f"MESH generation failed: {message}", "ERROR")
        self.console.log(details, "DEBUG")
        self.statusBar().showMessage(_t("生成失败", "Generation failed"), 5000)
        QMessageBox.critical(self, APP_NAME, message)
        self._run_all_pending = False

    def _mesh_export_finished(self) -> None:
        worker = self._export_worker
        self._export_worker = None
        if worker is not None:
            worker.deleteLater()
        self._set_mesh_task_idle_if_possible()

    def _open_workflow_path(self, key: str):
        def action():
            input_text = self.page_import.input_edit.text().strip()
            input_path = Path(input_text) if input_text else None
            if key == "input_folder":
                target = (
                    input_path
                    if input_path and input_path.is_dir()
                    else input_path.parent
                    if input_path
                    else None
                )
            elif key == "dataset_folder":
                hdf5 = self.artifacts.hdf5 if self.artifacts else self.model_path
                target = Path(hdf5).parent if hdf5 else None
            elif key == "mesh_folder":
                target = self.solver_context.output_dir if self.solver_context else None
            else:
                target = None
            if target is None or not Path(target).exists():
                raise FileNotFoundError(_t("目标文件尚未生成。", "The target file has not been generated."))
            if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(target).resolve()))):
                raise OSError(_t("系统无法打开该文件或目录。", "The system could not open the file or folder."))
            return target

        return self._guard(action, _t("正在打开文件", "Opening file"))

    def _solver_output_dir(self) -> Path:
        if self.solver_context is None:
            raise ValueError(_t("请先生成 MESH。", "Generate MESH first."))
        return self.solver_context.output_dir

    def _generate_flow_input(self):
        return self._guard(
            lambda: self.page_inp.collect_data(self._solver_output_dir()),
            _t("正在生成 flow.inp", "Generating flow.inp"),
        )

    def _generate_incon(self):
        if self.solver_context is None:
            QMessageBox.warning(self, APP_NAME, _t("请先生成 MESH。", "Generate MESH first."))
            return None
        return self._guard(
            lambda: self.page_incon.generate(
                self.solver_context.legacy, self.solver_context.output_dir
            ),
            _t("正在生成 INCON", "Generating INCON"),
        )

    def _action_open(self):
        self._go_to(Sidebar.PAGE_IMPORT)
        self.page_import._browse_input()

    def _action_load_dataset(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            _t("打开 FV 数据集", "Open FV dataset"),
            "",
            "GeoFV HDF5 (*.geofv.h5 *.h5)",
        )
        if path:
            self.page_import.input_edit.setText(path)
            self._load_dataset(path)

    def _action_run_all(self):
        if self.model is None:
            raw_path = Path(self.page_import.input_edit.text().strip())
            if raw_path.name.lower().endswith((".geofv.h5", ".h5")):
                QMessageBox.warning(
                    self,
                    APP_NAME,
                    _t(
                        "\u8bf7\u5148\u70b9\u51fb\u201c\u8f7d\u5165\u73b0\u6709 FV \u6570\u636e\u96c6\u201d\uff0c\u5f85\u8f7d\u5165\u5b8c\u6210\u540e\u518d\u4e00\u952e\u751f\u6210\u3002",
                        "Load the existing FV dataset first, then run the full workflow.",
                    ),
                )
                return
            if self._inspect(str(raw_path)) is None:
                return
            if self._generate_dataset() is None:
                return
        if not self.selected_backend and self._confirm_solver(self.page_solver.selected_backend()) is None:
            return
        self._run_all_pending = True
        if self._prepared_solver_model is None:
            self._request_solver_preparation()
        else:
            self._generate_mesh()

    def _change_language(self, code: str):
        if code != get_language():
            set_language(code)
            QMessageBox.information(
                self,
                tr("app.restart_required"),
                tr("app.message.restart_after_language_change"),
            )

    def _show_about(self):
        QMessageBox.about(
            self,
            APP_NAME,
            f"<h2>{APP_NAME}</h2><p>{APP_FULL_NAME} v{APP_VERSION}</p>"
            "<p>Solver-independent finite-volume topology and geometry bridge.</p>",
        )

    def closeEvent(self, event):
        if (
            self._conversion_process is not None
            and self._conversion_process.process.state() != QProcess.NotRunning
        ):
            process = self._conversion_process.process
            process.terminate()
            if not process.waitForFinished(3000):
                process.kill()
                process.waitForFinished(3000)
        if self._load_worker is not None and self._load_worker.isRunning():
            self._load_worker.wait()
        for worker in (
            self._preparation_worker,
            self._preview_worker,
            self._export_worker,
        ):
            if worker is not None and worker.isRunning():
                worker.wait()
        self.page_out.shutdown()
        self.console.restore_stdout()
        self.visualizer.close_plotter()
        event.accept()


MainWindow = GeoFVBridgeMainWindow


def run() -> int:
    os.environ.setdefault("PYVISTA_OFF_SCREEN", "false")
    application = QApplication.instance() or QApplication(sys.argv)
    application.setApplicationName(APP_NAME)
    application.setFont(QFont(Fonts.FAMILY, Fonts.SIZE_M))
    application.setStyleSheet(qdarktheme.load_stylesheet("dark") + CUSTOM_QSS)
    window = GeoFVBridgeMainWindow()
    window.show()
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(run())
