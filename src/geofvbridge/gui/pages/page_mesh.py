"""TOUGH MESH preparation page built on the independent FV core."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ...boundary_selection import BoundarySelectionIndex
from ...i18n import get_language
from ...model import ExtrusionOptions
from ..reports import format_tough_report


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


class ToughMeshPage(QWidget):
    """Stage 4: prepare the solver model and export MESH only."""

    preview_requested = Signal()
    generate_requested = Signal()
    config_changed = Signal()
    preparation_changed = Signal()
    selection_changed = Signal()
    open_requested = Signal(str)

    SELECTION_MATERIAL = "material"
    SELECTION_BOUNDARY = "boundary_group"
    SELECTION_COORDINATE = "coordinate"
    SELECTION_EXPOSED = "exposed_face"
    SELECTION_GLOBAL = "global_plane"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.native_dimension: int | None = None
        self.materials: list[str] = []
        self.h5_path: Path | None = None
        self.msh_path: Path | None = None
        self.vol_entries: dict[str, QLineEdit] = {}
        self.ahtx_entries: dict[str, QLineEdit] = {}
        self.selection_index: BoundarySelectionIndex | None = None
        self._selection_valid = False
        self._automatic_output_dir: Path | None = None
        self._suppress_config_changed = False
        self._suppress_smart_default = False
        self._selection_timer = QTimer(self)
        self._selection_timer.setSingleShot(True)
        self._selection_timer.setInterval(250)
        self._selection_timer.timeout.connect(self.selection_changed)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        outer.addWidget(scroll)
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        scroll.setWidget(body)

        layout.addWidget(_title(_t("4. TOUGH 几何与网格（MESH）", "4. TOUGH geometry and mesh (MESH)")))
        desc = QLabel(
            _t(
                "选择当前 H5 或原始 MSH。两者都先形成相同的原维度 FVModel；二维拉伸只在本页执行。",
                "Select the current H5 or original MSH. Both pass through the same native FVModel; 2-D extrusion occurs only here.",
            )
        )
        desc.setWordWrap(True)
        layout.addWidget(desc)

        source_group = QGroupBox(_t("Step 1：来源与输出", "Step 1: source and output"))
        source_form = QFormLayout(source_group)
        self.source_combo = QComboBox()
        self.source_combo.addItem(_t("当前 .geofv.h5", "Current .geofv.h5"), "h5")
        self.source_combo.addItem(_t("原始 .msh", "Original .msh"), "msh")
        self.source_combo.currentIndexChanged.connect(self._source_selected)
        self.source_label = QLabel("—")
        self.source_label.setWordWrap(True)
        self.output_edit = QLineEdit()
        source_form.addRow(_t("数据来源：", "Data source:"), self.source_combo)
        source_form.addRow(_t("来源文件：", "Source file:"), self.source_label)
        source_form.addRow(
            _t("MESH 输出目录：", "MESH output directory:"),
            _path_row(
                self.output_edit,
                self._browse_output,
                _t("默认使用来源文件目录", "Defaults to the source file directory"),
            ),
        )
        layout.addWidget(source_group)

        info_group = QGroupBox(_t("Step 2：求解器网格信息", "Step 2: solver mesh information"))
        info_form = QFormLayout(info_group)
        self.info_label = QLabel("—")
        self.info_label.setWordWrap(True)
        info_form.addRow(self.info_label)
        layout.addWidget(info_group)

        self.extrude_group = QGroupBox(_t("Step 3：二维拉伸", "Step 3: 2-D extrusion"))
        ext = QGridLayout(self.extrude_group)
        self.entry_height = QLineEdit("0.019")
        self.combo_axis = QComboBox()
        self.combo_axis.addItems(["X (0)", "Y (1)", "Z (2)"])
        self.combo_axis.setCurrentIndex(1)
        self.layers_spin = QSpinBox()
        self.layers_spin.setRange(1, 10000)
        self.layers_spin.setValue(1)
        ext.addWidget(QLabel(_t("总厚度：", "Total thickness:")), 0, 0)
        ext.addWidget(self.entry_height, 0, 1)
        ext.addWidget(QLabel(_t("拉伸方向：", "Direction:")), 1, 0)
        ext.addWidget(self.combo_axis, 1, 1)
        ext.addWidget(QLabel(_t("等厚层数：", "Equal layers:")), 2, 0)
        ext.addWidget(self.layers_spin, 2, 1)
        layout.addWidget(self.extrude_group)

        volume = QGroupBox(_t("Step 4：无限体积单元设置", "Step 4: infinite-volume cells"))
        self.vol_layout = QGridLayout(volume)
        self.combo_selection_mode = QComboBox()
        self.combo_selection_mode.addItem(_t("请选择定义方式", "Select a definition method"), None)
        self.combo_selection_mode.addItem(_t("按三维材料组", "By 3-D material group"), self.SELECTION_MATERIAL)
        self.combo_selection_mode.addItem(_t("按二维边界面组", "By 2-D boundary face group"), self.SELECTION_BOUNDARY)
        self.combo_selection_mode.addItem(_t("按坐标阈值", "By coordinate threshold"), self.SELECTION_COORDINATE)
        self.combo_selection_mode.addItem(_t("自动识别顶部外露面", "Automatic exposed top faces"), self.SELECTION_EXPOSED)
        self.combo_selection_mode.addItem(_t("全局最高水平面", "Global highest plane"), self.SELECTION_GLOBAL)
        self.combo_volume_mode = self.combo_selection_mode
        self.combo_selection_mode.currentIndexChanged.connect(self._update_volume_mode_ui)
        self.infinite_volume_edit = QLineEdit("1.0E50")
        self.vol_layout.addWidget(QLabel(_t("定义方式：", "Definition method:")), 0, 0)
        self.vol_layout.addWidget(self.combo_selection_mode, 0, 1)
        self.vol_layout.addWidget(QLabel(_t("无限体积：", "Infinite volume:")), 1, 0)
        self.vol_layout.addWidget(self.infinite_volume_edit, 1, 1)
        self.selection_stack = QStackedWidget()
        self.selection_stack.addWidget(
            QLabel(_t("请选择一种无限体积单元定义方式。", "Select one infinite-volume definition method."))
        )

        material_widget = QWidget()
        material_form = QFormLayout(material_widget)
        material_form.setContentsMargins(0, 0, 0, 0)
        self.combo_inactive_material = QComboBox()
        material_form.addRow(_t("材料组：", "Material group:"), self.combo_inactive_material)
        self.selection_stack.addWidget(material_widget)

        boundary_widget = QWidget()
        boundary_form = QFormLayout(boundary_widget)
        boundary_form.setContentsMargins(0, 0, 0, 0)
        self.combo_boundary_group = QComboBox()
        boundary_form.addRow(_t("边界面组：", "Boundary face group:"), self.combo_boundary_group)
        boundary_note = QLabel(
            _t(
                "二维面本身不写入 ELEME；选择它们相邻的唯一三维单元。",
                "The 2-D faces are not ELEME records; their unique adjacent 3-D cells are selected.",
            )
        )
        boundary_note.setWordWrap(True)
        boundary_form.addRow(boundary_note)
        self.selection_stack.addWidget(boundary_widget)

        coordinate_widget = QWidget()
        coordinate_form = QFormLayout(coordinate_widget)
        coordinate_form.setContentsMargins(0, 0, 0, 0)
        self.combo_coordinate_axis = QComboBox()
        self.combo_coordinate_axis.addItems(["X", "Y", "Z"])
        self.combo_coordinate_axis.setCurrentIndex(2)
        self.combo_coordinate_operator = QComboBox()
        self.combo_coordinate_operator.addItem("≥", "ge")
        self.combo_coordinate_operator.addItem("≤", "le")
        self.entry_coordinate_value = QLineEdit()
        coordinate_form.addRow(_t("坐标轴：", "Coordinate axis:"), self.combo_coordinate_axis)
        coordinate_form.addRow(_t("关系：", "Relation:"), self.combo_coordinate_operator)
        coordinate_form.addRow(_t("阈值：", "Threshold:"), self.entry_coordinate_value)
        self.selection_stack.addWidget(coordinate_widget)

        exposed_widget = QWidget()
        exposed_form = QFormLayout(exposed_widget)
        exposed_form.setContentsMargins(0, 0, 0, 0)
        self.combo_exposed_axis = QComboBox()
        self.combo_exposed_axis.addItems(["X", "Y", "Z"])
        self.combo_exposed_axis.setCurrentIndex(2)
        self.combo_exposed_direction = QComboBox()
        self.combo_exposed_direction.addItem(_t("正方向（顶部）", "Positive direction (top)"), 1)
        self.combo_exposed_direction.addItem(_t("负方向（底部）", "Negative direction (bottom)"), -1)
        self.entry_minimum_normal = QLineEdit("0.10")
        exposed_form.addRow(_t("垂直轴：", "Vertical axis:"), self.combo_exposed_axis)
        exposed_form.addRow(_t("方向：", "Direction:"), self.combo_exposed_direction)
        exposed_form.addRow(_t("最小法向分量：", "Minimum normal component:"), self.entry_minimum_normal)
        self.selection_stack.addWidget(exposed_widget)

        global_widget = QWidget()
        global_form = QFormLayout(global_widget)
        global_form.setContentsMargins(0, 0, 0, 0)
        self.combo_global_axis = QComboBox()
        self.combo_global_axis.addItems(["X", "Y", "Z"])
        self.combo_global_axis.setCurrentIndex(2)
        self.entry_global_tolerance = QLineEdit()
        self.entry_global_tolerance.setPlaceholderText(_t("留空＝自动", "Blank = automatic"))
        global_form.addRow(_t("垂直轴：", "Vertical axis:"), self.combo_global_axis)
        global_form.addRow(_t("坐标容差：", "Coordinate tolerance:"), self.entry_global_tolerance)
        self.selection_stack.addWidget(global_widget)

        self.vol_layout.addWidget(self.selection_stack, 2, 0, 1, 2)
        self.selection_summary = QLabel(_t("求解器网格尚未就绪。", "The solver mesh is not ready."))
        self.selection_summary.setWordWrap(True)
        self.vol_layout.addWidget(self.selection_summary, 3, 0, 1, 2)
        layout.addWidget(volume)

        self.volume_override_group = QGroupBox(
            _t("Step 5：普通材料体积覆盖（高级）", "Step 5: material volume overrides (advanced)")
        )
        self.volume_override_group.setCheckable(True)
        self.volume_override_group.setChecked(False)
        self.vol_material_layout = QGridLayout(self.volume_override_group)
        layout.addWidget(self.volume_override_group)

        ahtx = QGroupBox(_t("Step 6：热传导面积 AHTX", "Step 6: heat-transfer area AHTX"))
        self.ahtx_layout = QGridLayout(ahtx)
        self.chk_auto_ahtx = QCheckBox(
            _t("自动计算外露面 AHTX", "Automatically compute exposed-face AHTX")
        )
        self.chk_auto_ahtx.setChecked(True)
        self.combo_ahtx_mode = QComboBox()
        self.combo_ahtx_mode.addItem(_t("拉伸端面", "Extrusion end faces"), "extrusion")
        self.combo_ahtx_mode.addItem(_t("侧向外露面", "Lateral exposed faces"), "lateral")
        self.combo_ahtx_mode.addItem(_t("全部外露面", "All exposed faces"), "all")
        self.combo_vertical_axis = QComboBox()
        self.combo_vertical_axis.addItems(["X", "Y", "Z"])
        self.combo_vertical_axis.setCurrentIndex(2)
        self.ahtx_layout.addWidget(self.chk_auto_ahtx, 0, 0, 1, 2)
        self.ahtx_layout.addWidget(QLabel(_t("计算模式：", "Calculation mode:")), 1, 0)
        self.ahtx_layout.addWidget(self.combo_ahtx_mode, 1, 1)
        self.ahtx_layout.addWidget(QLabel(_t("垂直轴：", "Vertical axis:")), 2, 0)
        self.ahtx_layout.addWidget(self.combo_vertical_axis, 2, 1)
        layout.addWidget(ahtx)

        connections = QGroupBox(
            _t(
                "Step 7：Petrel 高级连接处理",
                "Step 7: advanced Petrel connection handling",
            )
        )
        connection_layout = QVBoxLayout(connections)
        self.chk_allow_unrepresented_connections = QCheckBox(
            _t(
                "忽略没有 TOUGH 几何的正 TRAN/NNC 连接（近似模型）",
                "Ignore positive TRAN/NNC without TOUGH geometry (approximate model)",
            )
        )
        self.chk_allow_unrepresented_connections.setChecked(False)
        connection_layout.addWidget(self.chk_allow_unrepresented_connections)
        connection_warning = QLabel(
            _t(
                "警告：勾选后只导出具有安全几何的连接；未表示的正 TRAN/NNC "
                "不会写入 CONNE，忽略数量将记录在 mesh_manifest.json 中。",
                "Warning: only connections with safe geometry are exported. "
                "Unrepresented positive TRAN/NNC are omitted from CONNE and audited "
                "in mesh_manifest.json.",
            )
        )
        connection_warning.setWordWrap(True)
        connection_layout.addWidget(connection_warning)
        layout.addWidget(connections)

        actions = QGroupBox(_t("Step 8：预览并生成 MESH", "Step 8: preview and generate MESH"))
        action_layout = QVBoxLayout(actions)
        buttons = QHBoxLayout()
        self.btn_preview = QPushButton(_t("预览无限体积单元", "Preview infinite-volume cells"))
        self.btn_preview.clicked.connect(self.preview_requested)
        self.btn_generate = QPushButton(_t("生成 MESH", "Generate MESH"))
        self.btn_generate.setObjectName("AccentButton")
        self.btn_generate.clicked.connect(self.generate_requested)
        self.open_folder_button = QPushButton(_t("打开输出目录", "Open output folder"))
        self.open_folder_button.setEnabled(False)
        self.open_folder_button.clicked.connect(lambda: self.open_requested.emit("mesh_folder"))
        buttons.addWidget(self.btn_preview)
        buttons.addWidget(self.btn_generate)
        buttons.addWidget(self.open_folder_button)
        buttons.addStretch()
        action_layout.addLayout(buttons)
        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        self.output.setMinimumHeight(160)
        action_layout.addWidget(self.output)
        layout.addWidget(actions)
        layout.addStretch()
        self._update_volume_mode_ui()
        self._connect_config_signals()
        self.set_selection_ready(False)

    def _connect_config_signals(self) -> None:
        for edit in (self.output_edit, self.entry_height, self.infinite_volume_edit):
            edit.textChanged.connect(self._emit_config_changed)
        for combo in (self.combo_ahtx_mode, self.combo_vertical_axis):
            combo.currentIndexChanged.connect(self._emit_config_changed)
        for combo in (
            self.combo_inactive_material,
            self.combo_boundary_group,
            self.combo_coordinate_axis,
            self.combo_coordinate_operator,
            self.combo_exposed_axis,
            self.combo_exposed_direction,
            self.combo_global_axis,
        ):
            combo.currentIndexChanged.connect(self._selection_control_changed)
        for edit in (
            self.entry_coordinate_value,
            self.entry_minimum_normal,
            self.entry_global_tolerance,
        ):
            edit.textChanged.connect(self._selection_text_changed)
        self.entry_height.editingFinished.connect(self._emit_preparation_changed)
        self.combo_axis.currentIndexChanged.connect(self._emit_preparation_changed)
        self.layers_spin.valueChanged.connect(self._emit_preparation_changed)
        self.volume_override_group.toggled.connect(self._emit_config_changed)
        self.chk_auto_ahtx.stateChanged.connect(self._emit_config_changed)
        self.chk_allow_unrepresented_connections.stateChanged.connect(
            self._emit_config_changed
        )

    def _emit_config_changed(self, *_args) -> None:
        if not self._suppress_config_changed:
            self.config_changed.emit()

    def _emit_preparation_changed(self, *_args) -> None:
        if not self._suppress_config_changed:
            self.config_changed.emit()
            self.preparation_changed.emit()

    def _selection_control_changed(self, *_args) -> None:
        if not self._suppress_config_changed:
            self.set_selection_ready(False)
            self.config_changed.emit()
            self.selection_changed.emit()

    def _selection_text_changed(self, *_args) -> None:
        if not self._suppress_config_changed:
            self.set_selection_ready(False)
            self.config_changed.emit()
            self._selection_timer.start()

    def _browse_output(self):
        path = QFileDialog.getExistingDirectory(
            self, _t("选择 MESH 输出目录", "Select MESH output directory")
        )
        if path:
            self._automatic_output_dir = None
            self.output_edit.setText(path)

    def _source_selected(self):
        path = self.source_path()
        self.source_label.setText(str(path) if path else "—")
        if path:
            current = self.output_edit.text().strip()
            current_path = Path(current) if current else None
            if current_path is None or current_path == self._automatic_output_dir:
                previous_suppression = self._suppress_config_changed
                self._suppress_config_changed = True
                self.output_edit.setText(str(path.parent))
                self._suppress_config_changed = previous_suppression
                self._automatic_output_dir = path.parent
            else:
                self._automatic_output_dir = None
        self._emit_preparation_changed()

    def set_sources(
        self,
        h5_path: Path | None,
        msh_path: Path | None,
        dimension: int,
        materials: list[str],
    ) -> None:
        previous_suppression = self._suppress_config_changed
        self._suppress_config_changed = True
        self.h5_path = Path(h5_path) if h5_path else None
        self.msh_path = Path(msh_path) if msh_path and Path(msh_path).is_file() else None
        self.native_dimension = dimension
        self.materials = list(materials)
        self.selection_index = None
        self.chk_allow_unrepresented_connections.setChecked(False)
        h5_item = self.source_combo.model().item(0)
        msh_item = self.source_combo.model().item(1)
        if h5_item is not None:
            h5_item.setEnabled(self.h5_path is not None)
        if msh_item is not None:
            msh_item.setEnabled(self.msh_path is not None)
        self.source_combo.setCurrentIndex(0 if self.h5_path is not None else 1)
        is_2d = dimension == 2
        self.extrude_group.setEnabled(True)
        self.entry_height.setEnabled(is_2d)
        self.combo_axis.setEnabled(is_2d)
        self.layers_spin.setEnabled(is_2d)
        if is_2d:
            ahtx_mode = "extrusion"
        else:
            ahtx_mode = "lateral"
        extrusion_item = self.combo_ahtx_mode.model().item(
            self.combo_ahtx_mode.findData("extrusion")
        )
        if extrusion_item is not None:
            extrusion_item.setEnabled(is_2d)
        index = self.combo_ahtx_mode.findData(ahtx_mode)
        if index >= 0:
            self.combo_ahtx_mode.setCurrentIndex(index)
        self.info_label.setText(
            _t(
                f"原始维数：{dimension}D；材料：{', '.join(self.materials) or 'DEFAULT'}",
                f"Native dimension: {dimension}D; materials: {', '.join(self.materials) or 'DEFAULT'}",
            )
        )
        self._populate_material_entries()
        self.combo_selection_mode.setCurrentIndex(0)
        self.combo_inactive_material.clear()
        self.combo_boundary_group.clear()
        self.set_selection_ready(False)
        self.selection_summary.setText(
            _t("正在准备求解器网格和边界索引……", "Preparing the solver mesh and boundary index…")
        )
        self.set_output_ready(False)
        self._source_selected()
        self._suppress_config_changed = previous_suppression

    def set_output_path(self, path: Path) -> None:
        previous_suppression = self._suppress_config_changed
        self._suppress_config_changed = True
        self.output_edit.setText(str(path))
        self._suppress_config_changed = previous_suppression
        source = self.source_path()
        self._automatic_output_dir = source.parent if source and path == source.parent else None

    def set_solver_mesh_info(self, model) -> None:
        """Show concise, file-specific information for the prepared solver mesh."""
        points = np.asarray(model.points, dtype=float)
        minimum = np.min(points, axis=0)
        maximum = np.max(points, axis=0)
        materials = len({cell.material for cell in model.cells})
        self.info_label.setText(
            _t(
                f"{model.dimension}D；单元 {len(model.cells):,}；内部连接 "
                f"{len(model.connections):,}；外边界面 {len(model.boundaries):,}；"
                f"材料组 {materials:,}\n"
                f"X：{minimum[0]:.6g} ～ {maximum[0]:.6g} m；"
                f"Y：{minimum[1]:.6g} ～ {maximum[1]:.6g} m；"
                f"Z：{minimum[2]:.6g} ～ {maximum[2]:.6g} m",
                f"{model.dimension}D; {len(model.cells):,} cells; "
                f"{len(model.connections):,} internal connections; "
                f"{len(model.boundaries):,} exterior faces; {materials:,} material groups\n"
                f"X: {minimum[0]:.6g} to {maximum[0]:.6g} m; "
                f"Y: {minimum[1]:.6g} to {maximum[1]:.6g} m; "
                f"Z: {minimum[2]:.6g} to {maximum[2]:.6g} m",
            )
        )

    @staticmethod
    def _clear_rows(layout: QGridLayout, first_row: int) -> None:
        for index in reversed(range(layout.count())):
            row, _, _, _ = layout.getItemPosition(index)
            if row >= first_row:
                item = layout.takeAt(index)
                if item.widget():
                    item.widget().deleteLater()

    def _populate_material_entries(self) -> None:
        old_volumes = {name: edit.text() for name, edit in self.vol_entries.items()}
        old_ahtx = {name: edit.text() for name, edit in self.ahtx_entries.items()}
        self._clear_rows(self.vol_material_layout, 0)
        self._clear_rows(self.ahtx_layout, 3)
        self.vol_entries = {}
        self.ahtx_entries = {}
        self.vol_material_layout.addWidget(QLabel(_t("材料", "Material")), 0, 0)
        self.vol_material_layout.addWidget(
            QLabel(_t("体积覆盖（留空不改）", "Volume override (blank = unchanged)")), 0, 1
        )
        self.ahtx_layout.addWidget(QLabel(_t("材料", "Material")), 3, 0)
        self.ahtx_layout.addWidget(
            QLabel(_t("AHTX 覆盖（留空自动）", "AHTX override (blank = automatic)")), 3, 1
        )
        self.vol_material_layout.itemAtPosition(0, 1).widget().setText(
            _t('\u4f53\u79ef\u8986\u76d6\uff08\u7559\u7a7a = \u4f7f\u7528\u51e0\u4f55\u4f53\u79ef\uff09', 'Volume override (blank = geometric volume)')
        )
        self.ahtx_layout.itemAtPosition(3, 1).widget().setText(
            _t(
                'AHTX \u8986\u76d6\uff08\u7559\u7a7a = \u81ea\u52a8\u7ed3\u679c\uff1b\u5173\u95ed\u81ea\u52a8\u8ba1\u7b97\u65f6\u4e3a 0\uff09',
                'AHTX override (blank = automatic result; 0 when automatic calculation is off)',
            )
        )
        for row, material in enumerate(self.materials, 1):
            self.vol_material_layout.addWidget(QLabel(material), row, 0)
            volume = QLineEdit(old_volumes.get(material, ""))
            volume.textChanged.connect(self._emit_config_changed)
            self.vol_material_layout.addWidget(volume, row, 1)
            self.vol_entries[material] = volume
            self.ahtx_layout.addWidget(QLabel(material), row + 3, 0)
            ahtx = QLineEdit(old_ahtx.get(material, ""))
            ahtx.textChanged.connect(self._emit_config_changed)
            self.ahtx_layout.addWidget(ahtx, row + 3, 1)
            self.ahtx_entries[material] = ahtx
    def _update_volume_mode_ui(self):
        mode = self.combo_selection_mode.currentData()
        pages = {
            self.SELECTION_MATERIAL: 1,
            self.SELECTION_BOUNDARY: 2,
            self.SELECTION_COORDINATE: 3,
            self.SELECTION_EXPOSED: 4,
            self.SELECTION_GLOBAL: 5,
        }
        self.selection_stack.setCurrentIndex(pages.get(mode, 0))
        self._selection_control_changed()

    @staticmethod
    def _casefold_index(combo: QComboBox, name: str) -> int:
        target = name.casefold()
        for index in range(combo.count()):
            if combo.itemText(index).casefold() == target:
                return index
        return -1

    def set_selection_index(self, index: BoundarySelectionIndex) -> None:
        """Install one prepared-model index and apply the documented smart default."""
        previous_suppression = self._suppress_config_changed
        self._suppress_config_changed = True
        self.selection_index = index
        self.combo_inactive_material.clear()
        self.combo_inactive_material.addItems(list(index.material_cells))
        self.combo_boundary_group.clear()
        self.combo_boundary_group.addItems(list(index.boundary_groups))
        bound = self._casefold_index(self.combo_inactive_material, "BOUND")
        top = self._casefold_index(self.combo_boundary_group, "Top")
        if bound >= 0:
            self.combo_inactive_material.setCurrentIndex(bound)
            self.combo_selection_mode.setCurrentIndex(
                self.combo_selection_mode.findData(self.SELECTION_MATERIAL)
            )
        elif top >= 0:
            self.combo_boundary_group.setCurrentIndex(top)
            self.combo_selection_mode.setCurrentIndex(
                self.combo_selection_mode.findData(self.SELECTION_BOUNDARY)
            )
        else:
            self.combo_selection_mode.setCurrentIndex(0)
        self._suppress_config_changed = previous_suppression
        self._update_volume_mode_ui()
        self.set_selection_ready(self.combo_selection_mode.currentData() is not None)

    def set_selection_ready(self, ready: bool) -> None:
        self._selection_valid = bool(ready)
        self.btn_preview.setEnabled(ready)
        self.btn_generate.setEnabled(ready)

    def set_selection_summary(self, report: dict | None = None, error: str | None = None) -> None:
        if error:
            self.selection_summary.setText(
                _t(f"当前选择无效：{error}", f"The current selection is invalid: {error}")
            )
            self.set_selection_ready(False)
            return
        if not report:
            self.selection_summary.setText(
                _t("请选择一种无限体积单元定义方式。", "Select one infinite-volume definition method.")
            )
            self.set_selection_ready(False)
            return
        minimum = report.get("node_coordinate_min")
        maximum = report.get("node_coordinate_max")
        coordinate = ""
        if minimum is not None and maximum is not None:
            coordinate = _t(
                f"；Z 节点范围：{float(minimum[2]):.6g} ～ {float(maximum[2]):.6g} m",
                f"; node Z range: {float(minimum[2]):.6g} to {float(maximum[2]):.6g} m",
            )
        self.selection_summary.setText(
            _t(
                f"方式：{report.get('selection_label', '—')}；二维边界面：{int(report.get('boundary_face_count', 0)):,}；"
                f"唯一三维单元：{int(report.get('inactive_count', 0)):,}{coordinate}",
                f"Method: {report.get('selection_label', '—')}; 2-D boundary faces: {int(report.get('boundary_face_count', 0)):,}; "
                f"unique 3-D cells: {int(report.get('inactive_count', 0)):,}{coordinate}",
            )
        )
        self.set_selection_ready(True)

    def set_task_busy(self, busy: bool, message: str = "") -> None:
        self.btn_preview.setEnabled(not busy and self._selection_valid)
        self.btn_generate.setEnabled(not busy and self._selection_valid)
        if busy and message:
            self.selection_summary.setText(message)

    def source_path(self) -> Path | None:
        return self.h5_path if self.source_combo.currentData() == "h5" else self.msh_path

    def extrusion(self) -> ExtrusionOptions | None:
        if self.native_dimension != 2:
            return None
        total = float(self.entry_height.text())
        layers = self.layers_spin.value()
        if total <= 0.0:
            raise ValueError(
                _t("拉伸总厚度必须大于零。", "Total extrusion thickness must be positive.")
            )
        directions = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
        return ExtrusionOptions(
            directions[self.combo_axis.currentIndex()], (total / layers,) * layers
        )

    def inactive_selection(self) -> dict:
        mode = self.combo_selection_mode.currentData()
        if mode is None:
            raise ValueError(
                _t("请选择无限体积单元定义方式。", "Select an infinite-volume definition method.")
            )
        if mode == self.SELECTION_MATERIAL:
            name = self.combo_inactive_material.currentText().strip()
            if not name:
                raise ValueError(_t("请选择材料组。", "Select a material group."))
            return {"method": mode, "material": name}
        if mode == self.SELECTION_BOUNDARY:
            name = self.combo_boundary_group.currentText().strip()
            if not name:
                raise ValueError(_t("请选择边界面组。", "Select a boundary face group."))
            return {"method": mode, "boundary_group": name}
        if mode == self.SELECTION_COORDINATE:
            value = self.entry_coordinate_value.text().strip()
            if not value:
                raise ValueError(_t("请输入坐标阈值。", "Enter a coordinate threshold."))
            return {
                "method": mode,
                "axis": self.combo_coordinate_axis.currentIndex(),
                "operator": self.combo_coordinate_operator.currentData(),
                "value": float(value),
            }
        if mode == self.SELECTION_EXPOSED:
            return {
                "method": mode,
                "axis": self.combo_exposed_axis.currentIndex(),
                "direction": int(self.combo_exposed_direction.currentData()),
                "minimum_normal": float(self.entry_minimum_normal.text()),
            }
        tolerance = self.entry_global_tolerance.text().strip()
        return {
            "method": self.SELECTION_GLOBAL,
            "axis": self.combo_global_axis.currentIndex(),
            "side": "max",
            "tolerance": float(tolerance) if tolerance else None,
        }

    def config(self) -> dict:
        config: dict = {
            "boundary_mode": "auto",
            "infinite_volume": float(self.infinite_volume_edit.text()),
            "vertical_axis": self.combo_vertical_axis.currentIndex(),
            "inactive_selection": self.inactive_selection(),
            "allow_unrepresented_source_connections": (
                self.chk_allow_unrepresented_connections.isChecked()
            ),
            "ahtx": {
                "mode": (
                    self.combo_ahtx_mode.currentData()
                    if self.chk_auto_ahtx.isChecked()
                    else "none"
                ),
                "heat_axis": self.combo_axis.currentIndex(),
                "vertical_axis": self.combo_vertical_axis.currentIndex(),
                "material_overrides": {
                    name: float(edit.text())
                    for name, edit in self.ahtx_entries.items()
                    if edit.text().strip()
                },
            },
        }
        if self.volume_override_group.isChecked():
            config["volume_overrides"] = {
                name: float(edit.text())
                for name, edit in self.vol_entries.items()
                if edit.text().strip()
            }
        return config

    def show_json(self, value) -> None:
        self.output.setPlainText(format_tough_report(value))

    def set_output_ready(self, ready: bool) -> None:
        self.open_folder_button.setEnabled(ready)

    def mark_output_stale(self) -> None:
        self.set_output_ready(False)
        self.output.setPlainText(
            _t(
                '\u7b2c 4 \u9875\u53c2\u6570\u5df2\u66f4\u6539\u3002\u8bf7\u91cd\u65b0\u9884\u89c8\u5e76\u751f\u6210 MESH\uff0c\u518d\u7ee7\u7eed flow.inp \u548c INCON\u3002',
                'Stage 4 settings changed. Preview and regenerate MESH before continuing to flow.inp or INCON.',
            )
        )

    def clear_output(self) -> None:
        self.output.clear()
        self.set_output_ready(False)
