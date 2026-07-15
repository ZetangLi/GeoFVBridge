"""TOUGH MESH preparation page built on the independent FV core."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal
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
    QVBoxLayout,
    QWidget,
)

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
    open_requested = Signal(str)

    VOLUME_MODE_MATERIAL = "material"
    VOLUME_MODE_Z = "z_threshold"
    VOLUME_MODE_TOP = "top_boundary"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.native_dimension: int | None = None
        self.materials: list[str] = []
        self.h5_path: Path | None = None
        self.msh_path: Path | None = None
        self.vol_entries: dict[str, QLineEdit] = {}
        self.ahtx_entries: dict[str, QLineEdit] = {}
        self._automatic_output_dir: Path | None = None
        self._suppress_config_changed = False

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
        self.chk_auto_bound = QCheckBox(
            _t("三维模式自动将 BOUND 设为无限体积单元", "Set BOUND to infinite volume in 3-D mode")
        )
        self.chk_auto_bound.setChecked(True)
        self.chk_auto_bound.stateChanged.connect(self._update_bound_volume_state)
        ext.addWidget(self.chk_auto_bound, 3, 0, 1, 2)
        layout.addWidget(self.extrude_group)

        volume = QGroupBox(_t("Step 4：边界条件与体积修改", "Step 4: boundary and volume"))
        self.vol_layout = QGridLayout(volume)
        self.combo_volume_mode = QComboBox()
        self.combo_volume_mode.addItem(
            _t("按材料修改体积", "Volume overrides by material"), self.VOLUME_MODE_MATERIAL
        )
        self.combo_volume_mode.addItem(
            _t("按 Z 阈值定义无限体积", "Infinite volume by Z threshold"), self.VOLUME_MODE_Z
        )
        self.combo_volume_mode.addItem(
            _t("自动选择全局顶部", "Automatic global top"), self.VOLUME_MODE_TOP
        )
        self.combo_volume_mode.currentIndexChanged.connect(self._update_volume_mode_ui)
        self.infinite_volume_edit = QLineEdit("1.0E50")
        self.vol_layout.addWidget(QLabel(_t("定义模式：", "Definition mode:")), 0, 0)
        self.vol_layout.addWidget(self.combo_volume_mode, 0, 1)
        self.vol_layout.addWidget(QLabel(_t("无限体积：", "Infinite volume:")), 1, 0)
        self.vol_layout.addWidget(self.infinite_volume_edit, 1, 1)
        self.vol_material_widget = QWidget()
        self.vol_material_layout = QGridLayout(self.vol_material_widget)
        self.vol_material_layout.setContentsMargins(0, 0, 0, 0)
        self.vol_layout.addWidget(self.vol_material_widget, 2, 0, 1, 2)
        self.vol_z_widget = QWidget()
        z_layout = QFormLayout(self.vol_z_widget)
        z_layout.setContentsMargins(0, 0, 0, 0)
        self.entry_volume_z = QLineEdit()
        z_layout.addRow(_t("质心 Z 下限：", "Centroid Z minimum:"), self.entry_volume_z)
        self.vol_layout.addWidget(self.vol_z_widget, 3, 0, 1, 2)
        self.vol_top_widget = QLabel(
            _t("选择拥有全局最高外露面的单元。", "Select cells owning exposed faces at the global maximum.")
        )
        self.vol_top_widget.setWordWrap(True)
        self.vol_layout.addWidget(self.vol_top_widget, 4, 0, 1, 2)
        layout.addWidget(volume)

        ahtx = QGroupBox(_t("Step 5：热传导面积 AHTX", "Step 5: heat-transfer area AHTX"))
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

        actions = QGroupBox(_t("Step 6：预览并生成 MESH", "Step 6: preview and generate MESH"))
        action_layout = QVBoxLayout(actions)
        buttons = QHBoxLayout()
        preview = QPushButton(_t("预览边界清单", "Preview boundary list"))
        preview.clicked.connect(self.preview_requested)
        self.btn_generate = QPushButton(_t("生成 MESH", "Generate MESH"))
        self.btn_generate.setObjectName("AccentButton")
        self.btn_generate.clicked.connect(self.generate_requested)
        self.open_folder_button = QPushButton(_t("打开输出目录", "Open output folder"))
        self.open_folder_button.setEnabled(False)
        self.open_folder_button.clicked.connect(lambda: self.open_requested.emit("mesh_folder"))
        buttons.addWidget(preview)
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

    def _connect_config_signals(self) -> None:
        for edit in (
            self.output_edit,
            self.entry_height,
            self.infinite_volume_edit,
            self.entry_volume_z,
        ):
            edit.textChanged.connect(self._emit_config_changed)
        for combo in (
            self.combo_axis,
            self.combo_volume_mode,
            self.combo_ahtx_mode,
            self.combo_vertical_axis,
        ):
            combo.currentIndexChanged.connect(self._emit_config_changed)
        self.layers_spin.valueChanged.connect(self._emit_config_changed)
        self.chk_auto_bound.stateChanged.connect(self._emit_config_changed)
        self.chk_auto_ahtx.stateChanged.connect(self._emit_config_changed)

    def _emit_config_changed(self, *_args) -> None:
        if not self._suppress_config_changed:
            self.config_changed.emit()

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
        self._emit_config_changed()

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
        self.chk_auto_bound.setEnabled(not is_2d and "BOUND" in self.materials)
        if is_2d:
            self.chk_auto_bound.setChecked(False)
            ahtx_mode = "extrusion"
        else:
            self.chk_auto_bound.setChecked("BOUND" in self.materials)
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
        self._update_bound_volume_state()

    def _update_volume_mode_ui(self):
        mode = self.combo_volume_mode.currentData()
        self.vol_material_widget.setVisible(mode == self.VOLUME_MODE_MATERIAL)
        self.vol_z_widget.setVisible(mode == self.VOLUME_MODE_Z)
        self.vol_top_widget.setVisible(mode == self.VOLUME_MODE_TOP)
        self._update_bound_volume_state()

    def _update_bound_volume_state(self):
        entry = self.vol_entries.get("BOUND")
        if entry is None:
            return
        automatic = (
            self.combo_volume_mode.currentData() == self.VOLUME_MODE_MATERIAL
            and self.chk_auto_bound.isEnabled()
            and self.chk_auto_bound.isChecked()
        )
        entry.setEnabled(not automatic)
        if automatic:
            entry.clear()
            entry.setPlaceholderText(_t("由自动 BOUND 设置", "Set by automatic BOUND"))
        else:
            entry.setPlaceholderText("")

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

    def config(self) -> dict:
        mode = self.combo_volume_mode.currentData()
        config: dict = {
            "boundary_mode": "auto",
            "infinite_volume": float(self.infinite_volume_edit.text()),
            "vertical_axis": self.combo_vertical_axis.currentIndex(),
            "inactive_cells": [],
            "inactive_materials": [],
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
        if mode == self.VOLUME_MODE_MATERIAL:
            config["volume_overrides"] = {
                name: float(edit.text())
                for name, edit in self.vol_entries.items()
                if edit.text().strip()
            }
            if self.chk_auto_bound.isChecked() and self.chk_auto_bound.isEnabled():
                config["inactive_materials"] = ["BOUND"]
        elif mode == self.VOLUME_MODE_Z:
            if not self.entry_volume_z.text().strip():
                raise ValueError(_t("请输入 Z 阈值。", "Enter a Z threshold."))
            config["inactive_z_min"] = float(self.entry_volume_z.text())
        elif mode == self.VOLUME_MODE_TOP:
            config["inactive_top"] = True
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
