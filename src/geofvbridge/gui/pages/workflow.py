"""Pages for FE import, reusable FV data, and solver selection."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ...api import available_backends
from ...i18n import get_language
from ...model import FVModel
from ..reports import format_fe_inspection, format_fv_model


def _t(chinese: str, english: str) -> str:
    return chinese if get_language() == "zh_CN" else english


def _title(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("SectionTitle")
    return label


def _path_row(edit: QLineEdit, callback, caption: str) -> QWidget:
    row = QWidget()
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 0, 0, 0)
    edit.setPlaceholderText(caption)
    button = QPushButton(_t("浏览…", "Browse…"))
    button.clicked.connect(callback)
    layout.addWidget(edit, 1)
    layout.addWidget(button)
    return row


class ImportPage(QWidget):
    """Stage 1: inspect the original finite-element mesh without modifying it."""

    inspect_requested = Signal(str)
    load_dataset_requested = Signal(str)
    open_requested = Signal(str)
    input_changed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.inspection: dict | None = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.addWidget(_title(_t("1. 有限元网格导入", "1. Finite-element mesh import")))
        note = QLabel(
            _t(
                "导入并检查原始 Gmsh 网格。本阶段只展示节点、单元、物理组和坐标范围，不修改网格。",
                "Inspect the original Gmsh mesh. This stage does not modify its nodes, cells, or dimension.",
            )
        )
        note.setWordWrap(True)
        layout.addWidget(note)

        source = QGroupBox(_t("输入文件", "Input file"))
        form = QFormLayout(source)
        self.input_edit = QLineEdit()
        self.input_edit.textChanged.connect(self._input_changed)
        form.addRow(
            _t("Gmsh / FV 数据：", "Gmsh / FV data:"),
            _path_row(self.input_edit, self._browse_input, ".msh / .geofv.h5"),
        )
        buttons = QHBoxLayout()
        inspect = QPushButton(_t("检查 MSH 并显示有限元网格", "Inspect MSH and display FE mesh"))
        inspect.setObjectName("AccentButton")
        inspect.clicked.connect(lambda: self.inspect_requested.emit(self.input_edit.text().strip()))
        load = QPushButton(_t("载入已有 FV 数据集", "Load existing FV dataset"))
        load.clicked.connect(lambda: self.load_dataset_requested.emit(self.input_edit.text().strip()))
        self.inspect_button = inspect
        self.load_button = load
        buttons.addWidget(inspect)
        buttons.addWidget(load)
        form.addRow(buttons)
        open_buttons = QHBoxLayout()
        self.open_input_folder_button = QPushButton(_t("打开所在目录", "Open containing folder"))
        self.open_input_folder_button.setEnabled(False)
        self.open_input_folder_button.clicked.connect(
            lambda: self.open_requested.emit("input_folder")
        )
        open_buttons.addWidget(self.open_input_folder_button)
        form.addRow(open_buttons)
        layout.addWidget(source)

        self.info = QPlainTextEdit()
        self.info.setReadOnly(True)
        self.info.setPlaceholderText(
            _t("检查后显示维数、节点、单元类型、物理组和坐标范围。", "Mesh information appears here after inspection.")
        )
        layout.addWidget(self.info, 1)
        self._update_input_actions('')

    def _browse_input(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            _t("选择 MSH 或 FV 数据集", "Select MSH or FV dataset"),
            "",
            "Gmsh/FV (*.msh *.geofv.h5 *.h5);;All files (*)",
        )
        if path:
            self.input_edit.setText(path)

    def _input_changed(self, text: str) -> None:
        self.inspection = None
        self._update_input_actions(text)
        self.input_changed.emit(text.strip())

    def _update_input_actions(self, text: str) -> None:
        path = Path(text.strip()) if text.strip() else None
        exists = bool(path and path.is_file())
        lower = path.name.lower() if path else ''
        self.inspect_button.setEnabled(exists and lower.endswith('.msh'))
        self.load_button.setEnabled(exists and lower.endswith(('.geofv.h5', '.h5')))
        self.open_input_folder_button.setEnabled(exists)

    def set_inspection(self, inspection: dict) -> None:
        self.inspection = inspection
        self.info.setPlainText(format_fe_inspection(inspection))
        self.set_input_ready(True)

    def set_input_ready(self, ready: bool) -> None:
        if ready:
            self._update_input_actions(self.input_edit.text())
        else:
            self.open_input_folder_button.setEnabled(False)

    def clear_inspection(self) -> None:
        self.inspection = None
        self.info.clear()


class DatasetPage(QWidget):
    """Stage 2: compute and persist the native-dimensional FV dataset."""

    generate_requested = Signal()
    open_requested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.addWidget(_title(_t("2. FV 数据集确认与保存", "2. Confirm and save FV dataset")))
        note = QLabel(
            _t(
                "计算 CELL、FACE、CONNECTION、BOUNDARY 和 SOURCE。二维输入仍保存为二维 triangle/quad，不在此处拉伸。",
                "Compute reusable FV topology and geometry. A 2-D input remains a 2-D triangle/quad dataset; extrusion is deferred to the solver stage.",
            )
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        row = QHBoxLayout()
        self.generate_button = QPushButton(_t("计算、确认并自动保存", "Compute, validate, and auto-save"))
        self.generate_button.setObjectName("AccentButton")
        self.generate_button.clicked.connect(self.generate_requested)
        row.addWidget(self.generate_button)
        row.addStretch()
        layout.addLayout(row)
        open_row = QHBoxLayout()
        self.open_folder_button = QPushButton(_t("打开输出目录", "Open output folder"))
        self.open_folder_button.setEnabled(False)
        self.open_folder_button.clicked.connect(
            lambda: self.open_requested.emit("dataset_folder")
        )
        open_row.addWidget(self.open_folder_button)
        open_row.addStretch()
        layout.addLayout(open_row)
        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        layout.addWidget(self.output, 1)

    def show_model(self, model: FVModel, artifacts=None) -> None:
        self.output.setPlainText(format_fv_model(model, artifacts))
        self.open_folder_button.setEnabled(bool(artifacts and Path(artifacts.hdf5).parent.is_dir()))

    def set_generation_enabled(self, enabled: bool) -> None:
        self.generate_button.setEnabled(enabled)

    def clear_model(self) -> None:
        self.output.clear()
        self.open_folder_button.setEnabled(False)
        self.generate_button.setEnabled(False)


class SolverSelectionPage(QWidget):
    """Stage 3: choose and confirm a registered solver backend."""

    selection_confirmed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.addWidget(_title(_t("3. 选择求解器", "3. Select solver")))
        note = QLabel(
            _t(
                "FV 数据集与求解器无关。确认求解器后才进入相应的网格和输入文件配置页面。",
                "The FV dataset is solver-independent. Confirm a backend to enable its mesh and input pages.",
            )
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        group = QGroupBox(_t("已注册后端", "Registered backends"))
        form = QFormLayout(group)
        self.backend = QComboBox()
        for item in available_backends():
            self.backend.addItem(item["display_name"], item["identifier"])
        form.addRow(_t("求解器：", "Solver:"), self.backend)
        self.confirm_button = QPushButton(_t("确认求解器", "Confirm solver"))
        self.confirm_button.setObjectName("AccentButton")
        self.confirm_button.clicked.connect(
            lambda: self.selection_confirmed.emit(str(self.backend.currentData()))
        )
        form.addRow(self.confirm_button)
        layout.addWidget(group)
        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        layout.addWidget(self.output, 1)

    def selected_backend(self) -> str:
        return str(self.backend.currentData())

    def show_selection(self, backend: str) -> None:
        self.output.setPlainText(
            _t(
                f"已确认：{self.backend.currentText()}\n下一步配置 TOUGH MESH。",
                f"Confirmed: {self.backend.currentText()}\nContinue to the TOUGH MESH stage.",
            )
        )

    def clear_selection(self) -> None:
        self.output.clear()
