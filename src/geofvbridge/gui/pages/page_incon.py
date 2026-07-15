# -*- coding: utf-8 -*-
"Initial-condition configuration page."

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ...i18n import tr
from ...styles import Colors, Fonts


class InconPage(QWidget):
    "Provide the InconPage component."

    incon_generated = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.mat_names = []
        self.incon_mat_entries = {}
        self._setup_ui()

    def _setup_ui(self):
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        outer_layout.addWidget(scroll)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        scroll.setWidget(container)

        title = QLabel(tr("page.incon.initial_conditions_incon"))
        title.setObjectName("SectionTitle")
        layout.addWidget(title)

        desc = QLabel(tr("page.incon.description"))
        desc.setWordWrap(True)
        desc.setStyleSheet(
            f"color: {Colors.TEXT_DIM}; font-size: {Fonts.SIZE_M}pt; margin-bottom: 4px;"
        )
        layout.addWidget(desc)
        axis_note = QLabel(tr("page.incon.z_axis_note"))
        axis_note.setWordWrap(True)
        axis_note.setStyleSheet(f"color: {Colors.TEXT_DIM}; font-size: {Fonts.SIZE_S}pt;")
        layout.addWidget(axis_note)

        # ══════════════════════════════════════════════════════

        # ══════════════════════════════════════════════════════
        param_group = QGroupBox(tr("page.incon.group.reservoir_parameters"))
        pg = QGridLayout(param_group)
        self.incon_entries = {}

        fields = [
            (tr("page.incon.reservoir_top_depth_z_top_m"), "z_top", "0.00", 120),
            (tr("page.incon.reservoir_bottom_depth_z_bot_m"), "z_bot", "0.00", 120),
            (tr("page.incon.pressure_gradient_pa_m"), "p_grad", "9810.0", 100),
            (tr("page.incon.top_pressure_p_top_pa"), "p_top", "1.01325E+05", 140),
            (tr("page.incon.bottom_pressure_p_bot_pa"), "p_bot", "1.01325E+05", 140),
            (tr("page.incon.geothermal_gradient_c_m"), "t_grad", "0.0250", 100),
            (tr("page.incon.top_temperature_t_top_c"), "t_top", "20.0", 80),
            (tr("page.incon.bottom_temperature_t_bot_c"), "t_bot", "20.0", 80),
            (tr("page.incon.default_gas_saturation_sg"), "sg", "0.0", 80),
            (tr("page.incon.default_dissolved_co2_xco2"), "xco2", "0.0", 80),
        ]
        for r, (lbl, key, val, w) in enumerate(fields):
            label = QLabel(lbl)
            label.setStyleSheet(f"font-size: {Fonts.SIZE_S}pt;")
            pg.addWidget(label, r, 0)
            entry = QLineEdit(val)
            entry.setFixedWidth(w)
            pg.addWidget(entry, r, 1)
            self.incon_entries[key] = entry

        hint = QLabel("💡 " + tr("page.incon.help.recalculate"))
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {Colors.TEXT_DIM}; font-size: {Fonts.SIZE_S}pt;")
        pg.addWidget(hint, len(fields), 0, 1, 2)

        btn_recalc = QPushButton(tr("page.incon.recalculate_bottom_p_bot_t_bot_based_on_gradients"))
        btn_recalc.setFixedHeight(32)
        btn_recalc.clicked.connect(self._recalc_bot)
        pg.addWidget(btn_recalc, len(fields) + 1, 0, 1, 2)

        layout.addWidget(param_group)

        # ══════════════════════════════════════════════════════

        # ══════════════════════════════════════════════════════
        self.mat_group = QGroupBox(tr("page.incon.group.lithology_configuration"))
        self.mat_layout = QGridLayout(self.mat_group)

        hdr_name = QLabel(tr("common.material_name"))
        hdr_name.setStyleSheet(f"font-weight: bold; color: {Colors.ACCENT};")
        self.mat_layout.addWidget(hdr_name, 0, 0)

        hdr_state = QLabel(tr("page.incon.phase_state"))
        hdr_state.setStyleSheet(f"font-weight: bold; color: {Colors.ACCENT};")
        self.mat_layout.addWidget(hdr_state, 0, 1)

        hdr_poro = QLabel(tr("page.incon.porosity"))
        hdr_poro.setStyleSheet(f"font-weight: bold; color: {Colors.ACCENT};")
        self.mat_layout.addWidget(hdr_poro, 0, 2)

        self.mat_placeholder = QLabel(tr("page.incon.placeholder.no_mesh"))
        self.mat_placeholder.setStyleSheet(f"color: {Colors.TEXT_DIM}; font-style: italic;")
        self.mat_layout.addWidget(self.mat_placeholder, 1, 0, 1, 3)

        layout.addWidget(self.mat_group)

        # ══════════════════════════════════════════════════════

        # ══════════════════════════════════════════════════════
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self.btn_generate = QPushButton("▶  " + tr("page.incon.generate_incon_file"))
        self.btn_generate.setObjectName("AccentButton")
        self.btn_generate.setFixedHeight(38)
        self.btn_generate.setEnabled(False)
        self.btn_generate.clicked.connect(self._generate_incon)
        btn_row.addWidget(self.btn_generate)

        self._btn_open_dir = QPushButton("📂 " + tr("common.open_output_folder"))
        self._btn_open_dir.setFixedHeight(32)
        self._btn_open_dir.setEnabled(False)
        self._btn_open_dir.clicked.connect(self._open_output_dir)
        btn_row.addWidget(self._btn_open_dir)

        layout.addLayout(btn_row)

        self.lbl_status = QLabel("")
        self.lbl_status.setWordWrap(True)
        layout.addWidget(self.lbl_status)

        layout.addStretch()

    def _recalc_bot(self):
        "Recalculate bot."
        try:
            ie = self.incon_entries
            z_top = float(ie["z_top"].text())
            z_bot = float(ie["z_bot"].text())
            p_top = float(ie["p_top"].text())
            t_top = float(ie["t_top"].text())
            p_grad = float(ie["p_grad"].text())
            t_grad = float(ie["t_grad"].text())

            dz = abs(z_top - z_bot)
            p_bot_new = p_top + p_grad * dz
            t_bot_new = t_top + t_grad * dz

            ie["p_bot"].setText(f"{p_bot_new:.5E}")
            ie["t_bot"].setText(f"{t_bot_new:.1f}")

            QMessageBox.information(
                self,
                tr("page.incon.recalculation_completed"),
                f"{tr('page.incon.updated_based_on_gradients')}\n"
                f"  P_bot = {p_bot_new:.5E} Pa\n"
                f"  T_bot = {t_bot_new:.1f} °C",
            )
        except Exception as ex:
            QMessageBox.critical(
                self,
                tr("page.incon.calculation_error"),
                f"{tr('page.incon.recalculation_failed')}\n{str(ex)}",
            )

    def populate_materials(self, mat_names, default_porosities=None):
        "Populate materials."
        from ...core.inp import get_default_rock

        self.mat_names = mat_names

        if self.mat_placeholder is not None:
            self.mat_placeholder.setParent(None)
            self.mat_placeholder = None

        for i in reversed(range(self.mat_layout.count())):
            item = self.mat_layout.itemAt(i)
            if item and item.widget():
                w = item.widget()
                r, c, _, _ = self.mat_layout.getItemPosition(i)
                if 1 <= r <= 99:
                    w.setParent(None)

        self.incon_mat_entries = {}

        for i, mat in enumerate(self.mat_names):
            row = i + 1

            lbl = QLabel(mat)
            lbl.setStyleSheet(f"color: {Colors.TEXT}; font-weight: bold;")
            self.mat_layout.addWidget(lbl, row, 0)

            e_state = QLineEdit("0")
            e_state.setFixedWidth(60)
            e_state.setToolTip(tr("page.incon.help.phase_code"))
            self.mat_layout.addWidget(e_state, row, 1)

            if default_porosities and mat in default_porosities:
                poro_val = default_porosities[mat]
            else:
                poro_val = get_default_rock(mat)["porosity"]
            e_poro = QLineEdit(str(poro_val))
            e_poro.setFixedWidth(100)
            e_poro.setToolTip(tr("page.incon.help.porosity_override"))
            self.mat_layout.addWidget(e_poro, row, 2)

            self.incon_mat_entries[mat] = {"state": e_state, "porosity": e_poro}

    def set_reservoir_depth(self, z_top, z_bot):
        "Set reservoir depth."
        ie = self.incon_entries
        ie["z_top"].setText(f"{z_top:.2f}")
        ie["z_bot"].setText(f"{z_bot:.2f}")

        p_grad = float(ie["p_grad"].text())
        t_grad = float(ie["t_grad"].text())
        p_top = float(ie["p_top"].text())
        t_top = float(ie["t_top"].text())
        dz = abs(z_top - z_bot)

        ie["p_bot"].setText(f"{p_top + p_grad * dz:.5E}")
        ie["t_bot"].setText(f"{t_top + t_grad * dz:.1f}")

    def enable_generation(self):
        self.btn_generate.setEnabled(True)

    def reset_mesh_context(self) -> None:
        self.btn_generate.setEnabled(False)
        self._output_dir = None
        self._btn_open_dir.setEnabled(False)
        self.lbl_status.clear()

    def _generate_incon(self):
        print(tr("page.incon.start_generating_incon"))
        self.incon_generated.emit()

    def generate(self, mesh_data, out_dir):
        "Generate."
        import numpy as np

        from ...core.incon import compute_initial_conditions, write_incon

        try:
            ie = self.incon_entries

            z_top = float(ie["z_top"].text())
            z_bot = float(ie["z_bot"].text())
            p_top = float(ie["p_top"].text())
            p_bot = float(ie["p_bot"].text())
            t_top = float(ie["t_top"].text())
            t_bot = float(ie["t_bot"].text())
            sg = float(ie["sg"].text())
            xco2 = float(ie["xco2"].text())

            centers = mesh_data.centers
            incon_data = compute_initial_conditions(
                centers, z_top, z_bot, p_top, p_bot, t_top, t_bot, sg, xco2
            )

            labels = mesh_data.labels
            materials = mesh_data.materials

            mat_states = {}
            mat_poros = {}
            for mat in self.mat_names:
                if mat in self.incon_mat_entries:
                    me = self.incon_mat_entries[mat]
                    mat_states[mat] = int(me["state"].text())
                    mat_poros[mat] = float(me["porosity"].text())
                else:
                    mat_states[mat] = 1
                    mat_poros[mat] = 0.0

            incon_path = write_incon(
                str(out_dir / "INCON"),
                labels,
                materials,
                incon_data,
                material_states=mat_states,
                material_porosities=mat_poros,
            )

            import os

            size = os.path.getsize(incon_path)
            n_cells = len(labels)

            p_min, p_max = np.min(incon_data[:, 0]), np.max(incon_data[:, 0])
            t_min, t_max = np.min(incon_data[:, 3]), np.max(incon_data[:, 3])

            print(f"{tr('page.incon.incon_generation_completed')} {incon_path} ({size:,} bytes)")
            print(
                f"  {n_cells} {tr('common.cells.label')}, P=[{p_min:.0f}, {p_max:.0f}] Pa, T=[{t_min:.2f}, {t_max:.2f}] °C"
            )

            self.lbl_status.setText(
                f"✓ {tr('page.incon.incon_generation_successful')} ({size:,} bytes)\n"
                f"  {n_cells} {tr('common.cells.label')}, P=[{p_min:.0f}, {p_max:.0f}] Pa, T=[{t_min:.2f}, {t_max:.2f}] °C"
            )
            self.lbl_status.setStyleSheet(f"color: {Colors.SUCCESS}; font-weight: bold;")

            self._output_dir = str(out_dir)
            if hasattr(self, "_btn_open_dir"):
                self._btn_open_dir.setEnabled(True)
            return incon_path

        except Exception as e:
            self.lbl_status.setText(f"✗ {tr('common.generation_failed')} {e}")
            self.lbl_status.setStyleSheet(f"color: {Colors.ERROR}; font-weight: bold;")
            print(f"{tr('page.incon.incon_generation_error')} {e}")
            import traceback

            traceback.print_exc()
            raise

    def _open_output_dir(self):
        "Open output dir."
        import os

        if hasattr(self, "_output_dir") and self._output_dir and os.path.isdir(self._output_dir):
            os.startfile(os.path.normpath(self._output_dir))
