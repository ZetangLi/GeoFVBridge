"""GeoFVBridge desktop application using the retained visual workspace shell."""

from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path

os.environ.setdefault("QT_API", "pyside6")

if __package__ in {None, ""}:
    source_root = str(Path(__file__).resolve().parents[2])
    if source_root not in sys.path:
        sys.path.insert(0, source_root)

import meshio
import numpy as np
import qdarktheme
from PySide6.QtCore import QSize, Qt, QThread, QUrl, Signal
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
    inspect_mesh,
    load_fv_dataset,
    prepare_solver_model,
    save_fv_dataset,
)
from geofvbridge.backends.eco2m import preview_eco2m
from geofvbridge.gui.console import LogConsole
from geofvbridge.gui.context import SolverMeshContext
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


class GeoFVBridgeMainWindow(QMainWindow):
    """Seven-stage FE → FV → solver desktop workflow."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} — {APP_FULL_NAME}")
        self.resize(1400, 900)
        self.setMinimumSize(1100, 700)

        self.inspection: dict | None = None
        self.msh_path: Path | None = None
        self.model: FVModel | None = None
        self.model_path: Path | None = None
        self.artifacts: DatasetArtifacts | None = None
        self.dataset_source_kind: str | None = None
        self.selected_backend: str | None = None
        self.solver_context: SolverMeshContext | None = None
        self.inactive_cells: set[int] = set()
        self._load_worker: DatasetLoadWorker | None = None
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
        self.page_dataset.open_requested.connect(self._open_workflow_path)
        self.page_solver.selection_confirmed.connect(self._confirm_solver)
        self.page_mesh.preview_requested.connect(self._preview_mesh)
        self.page_mesh.generate_requested.connect(self._generate_mesh)
        self.page_mesh.config_changed.connect(self._solver_mesh_config_changed)
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
        self.sidebar.set_page_enabled(Sidebar.PAGE_INP, False)
        self.sidebar.set_page_enabled(Sidebar.PAGE_INCON, False)
        self.page_inp.reset_mesh_context()
        self.page_incon.reset_mesh_context()
        if mark_stale and had_output:
            self.page_mesh.mark_output_stale()

    def _invalidate_workflow_for_input(self) -> None:
        self.inspection = None
        self.msh_path = None
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
            if not path.is_file() or path.suffix.lower() != ".msh":
                raise FileNotFoundError(_t("请选择有效的 Gmsh MSH 文件。", "Select a valid Gmsh MSH file."))
            self._invalidate_workflow_for_input()
            self.inspection = inspect_mesh(path)
            self.msh_path = path.resolve()
            self.dataset_source_kind = "msh"
            self.page_import.set_inspection(self.inspection)
            self.sidebar.set_page_enabled(Sidebar.PAGE_DATASET, True)
            self.page_dataset.set_generation_enabled(True)
            for page in (Sidebar.PAGE_SOLVER, Sidebar.PAGE_MESH, Sidebar.PAGE_INP, Sidebar.PAGE_INCON):
                self.sidebar.set_page_enabled(page, False)
            self.visualizer.display_meshio(meshio.read(path), int(self.inspection["dimension"]))
            self.info_label.setText(
                f"  {path.name} | {self.inspection['points']:,} points | "
                f"{self.inspection['dimension']}D FE mesh"
            )
            self.console.log(f"Inspected {path.name}: {self.inspection['cell_types']}", "SUCCESS")
            return self.inspection

        return self._guard(action, _t("正在检查有限元网格", "Inspecting FE mesh"))

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
            self.msh_path = source.resolve() if source and source.is_file() else None
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

    def _generate_dataset(self):
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

    def _on_native_model_ready(self):
        assert self.model is not None
        self.page_dataset.show_model(self.model, self.artifacts)
        self.page_dataset.set_generation_enabled(self.dataset_source_kind == "msh")
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
            return backend

        return self._guard(action, _t("正在确认求解器", "Confirming solver"))

    def _native_source_for_solver(self) -> tuple[FVModel, Path]:
        source = self.page_mesh.source_path()
        if source is None or not source.is_file():
            raise FileNotFoundError(_t("所选求解器网格来源不存在。", "The selected solver source does not exist."))
        if source.name.lower().endswith((".geofv.h5", ".h5")):
            model = self.model if self.model_path and source.resolve() == self.model_path.resolve() else load_fv_dataset(source)
        else:
            model = convert_mesh(source)
        return model, source

    def _prepare_solver_mesh(self) -> tuple[FVModel, Path, dict]:
        native, source = self._native_source_for_solver()
        prepared = prepare_solver_model(native, self.page_mesh.extrusion())
        return prepared, source, self.page_mesh.config()

    def _preview_mesh(self):
        def action():
            prepared, _, config = self._prepare_solver_mesh()
            preview = preview_eco2m(prepared, config)
            selected = preview.get("boundary_cells", preview.get("inactive_cells", []))
            self.inactive_cells = {int(item["cell_id"]) for item in selected}
            self.page_mesh.show_json(preview)
            self.visualizer.display_model(prepared, "tough_inactive", self.inactive_cells)
            return preview

        return self._guard(action, _t("正在预览 TOUGH 边界清单", "Previewing TOUGH boundary list"))

    def _generate_mesh(self):
        def action():
            if not self.selected_backend:
                raise ValueError(_t("请先确认求解器。", "Confirm a solver first."))
            prepared, source, config = self._prepare_solver_mesh()
            output_text = self.page_mesh.output_edit.text().strip()
            output = Path(output_text) if output_text else source.parent
            manifest = export_solver_mesh(prepared, self.selected_backend, config, output)
            self._clear_solver_mesh_state()
            self.solver_context = SolverMeshContext.from_export(
                prepared,
                self.selected_backend,
                source,
                output,
                config,
                manifest,
            )
            mesh_view = self.solver_context.mesh_view
            materials = list(dict.fromkeys(mesh_view.materials.tolist()))
            self.page_inp.populate_rocks(materials)
            self.page_inp.set_mesh_data(mesh_view)
            self.page_incon.populate_materials(materials)
            z_values = mesh_view.centers[:, 2]
            self.page_incon.set_reservoir_depth(float(np.max(z_values)), float(np.min(z_values)))
            self.page_incon.enable_generation()
            self.page_mesh.set_output_path(output)
            self.page_mesh.show_json(manifest)
            self.page_mesh.set_output_ready(True)
            selected = manifest.get("boundary_cells", manifest.get("inactive_cells", []))
            self.inactive_cells = {int(item["cell_id"]) for item in selected}
            self.visualizer.display_model(prepared, "tough_inactive", self.inactive_cells)
            self.sidebar.set_page_enabled(Sidebar.PAGE_INP, True)
            self.sidebar.set_page_enabled(Sidebar.PAGE_INCON, True)
            self.console.log(f"Generated MESH and cell_map.csv in {output}", "SUCCESS")
            return manifest

        return self._guard(action, _t("正在生成 TOUGH MESH", "Generating TOUGH MESH"))

    def _open_workflow_path(self, key: str):
        def action():
            input_text = self.page_import.input_edit.text().strip()
            input_path = Path(input_text) if input_text else None
            if key == "input_folder":
                target = input_path.parent if input_path else None
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
                self.solver_context.mesh_view, self.solver_context.output_dir
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
        if self._generate_mesh() is None:
            return
        if self._generate_flow_input() is None:
            return
        self._generate_incon()

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
        if self._load_worker is not None and self._load_worker.isRunning():
            self._load_worker.wait()
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
