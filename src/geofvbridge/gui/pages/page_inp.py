# -*- coding: utf-8 -*-
"TOUGH input configuration page."

from PySide6.QtCore import QPoint, QRect, QSize, Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLayout,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ...i18n import tr
from ...styles import Colors, Fonts


class FlowLayout(QLayout):
    "Provide the FlowLayout component."

    def __init__(self, parent=None, h_spacing=6, v_spacing=4):
        super().__init__(parent)
        self._h_spacing = h_spacing
        self._v_spacing = v_spacing
        self._items = []

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, index):
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index):
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._do_layout(QRect(0, 0, width, 0), test_only=True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do_layout(rect, test_only=False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        m = self.contentsMargins()
        size += QSize(m.left() + m.right(), m.top() + m.bottom())
        return size

    def _do_layout(self, rect, test_only):
        m = self.contentsMargins()
        effective = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        x = effective.x()
        y = effective.y()
        line_height = 0

        for item in self._items:
            space_x = self._h_spacing
            space_y = self._v_spacing
            next_x = x + item.sizeHint().width() + space_x
            if next_x - space_x > effective.right() and line_height > 0:
                x = effective.x()
                y = y + line_height + space_y
                next_x = x + item.sizeHint().width() + space_x
                line_height = 0
            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), item.sizeHint()))
            x = next_x
            line_height = max(line_height, item.sizeHint().height())

        return y + line_height - rect.y() + m.bottom()


def _add_field(layout, row, label_text, default="", width=120):
    "Add field."
    lbl = QLabel(label_text)
    lbl.setStyleSheet(f"font-size: {Fonts.SIZE_S}pt;")
    layout.addWidget(lbl, row, 0)
    entry = QLineEdit(str(default))
    entry.setFixedWidth(width)
    layout.addWidget(entry, row, 1)
    return entry


class InpPage(QWidget):
    "Provide the InpPage component."

    inp_generated = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.mat_names = []
        self.rock_entries = {}
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)

        title = QLabel(tr("page.inp.simulation_parameters_flow_inp"))
        title.setObjectName("SectionTitle")
        layout.addWidget(title)

        desc = QLabel(tr("page.inp.description"))
        desc.setWordWrap(True)
        desc.setStyleSheet(
            f"color: {Colors.TEXT_DIM}; font-size: {Fonts.SIZE_M}pt; margin-bottom: 4px;"
        )
        layout.addWidget(desc)

        self.tabs = QTabWidget()
        self.tabs.setStyleSheet(f"""
            QTabWidget::pane {{
                border: 1px solid {Colors.BORDER};
                border-radius: 4px;
            }}
            QTabBar::tab {{
                padding: 6px 16px;
                font-size: {Fonts.SIZE_S}pt;
            }}
            QTabBar::tab:selected {{
                color: {Colors.ACCENT};
                font-weight: bold;
            }}
        """)

        self.rocks_scroll = QScrollArea()
        self.rocks_scroll.setWidgetResizable(True)
        self.rocks_widget = QWidget()
        self.rocks_layout = QVBoxLayout(self.rocks_widget)
        self.rocks_layout.setSpacing(6)
        self.rocks_placeholder = QLabel(tr("page.inp.placeholder.no_mesh"))
        self.rocks_placeholder.setWordWrap(True)
        self.rocks_placeholder.setStyleSheet(f"color: {Colors.TEXT_DIM}; padding: 20px;")
        self.rocks_layout.addWidget(self.rocks_placeholder)
        self.rocks_layout.addStretch()
        self.rocks_scroll.setWidget(self.rocks_widget)
        self.tabs.addTab(self.rocks_scroll, "ROCKS")

        # Tab 2: MULTI
        self.tab_multi = self._create_multi_tab()
        self.tabs.addTab(self.tab_multi, "MULTI")

        # Tab 3: SELEC
        self.tab_selec = self._create_selec_tab()
        self.tabs.addTab(self.tab_selec, "SELEC")

        # Tab 4: PARAM
        self.tab_param = self._create_param_tab()
        self.tabs.addTab(self.tab_param, "PARAM")

        # Tab 5: TIMES
        self.tab_times = self._create_times_tab()
        self.tabs.addTab(self.tab_times, "TIMES")

        # Tab 6: GENER
        self.tab_gener = self._create_gener_tab()
        self.tabs.addTab(self.tab_gener, "GENER")

        # Tab 7: OUTPU
        self.tab_outpu = self._create_outpu_tab()
        self.tabs.addTab(self.tab_outpu, "OUTPU")

        layout.addWidget(self.tabs)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self.btn_generate = QPushButton("▶  " + tr("page.inp.generate_flow_inp"))
        self.btn_generate.setObjectName("AccentButton")
        self.btn_generate.setFixedHeight(38)
        self.btn_generate.clicked.connect(self._generate_inp)
        btn_row.addWidget(self.btn_generate)

        self._btn_open_dir = QPushButton("📂 " + tr("common.open_output_folder"))
        self._btn_open_dir.setFixedHeight(32)
        self._btn_open_dir.setEnabled(False)
        self._btn_open_dir.clicked.connect(self._open_output_dir)
        btn_row.addWidget(self._btn_open_dir)
        layout.addLayout(btn_row)

    def _create_multi_tab(self):
        "Create multi tab."
        from ...core.inp import get_default_multi

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        widget = QWidget()
        main_layout = QVBoxLayout(widget)
        main_layout.setSpacing(10)

        multi_group = QGroupBox(tr("page.inp.multi_components_equations_phases"))
        mg = QGridLayout(multi_group)
        dm = get_default_multi()
        self.multi_entries = {}
        multi_fields = [
            (tr("page.inp.nk_fluid_components_eco2m_3"), "nk", dm[0]),
            (tr("page.inp.neq_equations_eco2m_4"), "neq", dm[1]),
            (tr("page.inp.nph_phases_eco2m_4"), "nph", dm[2]),
            (tr("page.inp.nb_secondary_parameters_6_standard"), "nb", dm[3]),
        ]
        for r, (lbl, key, val) in enumerate(multi_fields):
            self.multi_entries[key] = _add_field(mg, r, lbl, val, 60)
        main_layout.addWidget(multi_group)

        main_layout.addStretch()
        scroll.setWidget(widget)
        return scroll

    def _create_selec_tab(self):
        "Create selec tab."
        from ...core.inp import get_default_selec

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        widget = QWidget()
        main_layout = QVBoxLayout(widget)
        main_layout.setSpacing(10)

        selec_group = QGroupBox(tr("page.inp.selec_eco2m_specific_parameters"))
        sg = QGridLayout(selec_group)
        ds = get_default_selec()
        self.selec_entries = {}

        ie_title = QLabel(tr("page.inp.integer_parameters_ie"))
        ie_title.setStyleSheet(
            f"font-weight: bold; color: {Colors.ACCENT}; font-size: {Fonts.SIZE_S}pt;"
        )
        sg.addWidget(ie_title, 0, 0, 1, 2)

        ie_fields = [
            (tr("page.inp.ie_1_additional_data_records_fixed_1"), "ie1"),
            (tr("page.inp.ie_7_extra_print_0_off_0_per_element_extra"), "ie7"),
            (tr("page.inp.ie_8_supercritical_phase_switch"), "ie8"),
            (tr("page.inp.ie_9_finite_phase_change_window"), "ie9"),
            (tr("page.inp.ie_11_permeability_vs_solid_salt_0_1_2_3"), "ie11"),
            (tr("page.inp.ie_12_h2o_solubility_in_co2_0_spycher_1_evap"), "ie12"),
            (tr("page.inp.ie_13_brine_density_co2_dependence_0_dep_1_indep"), "ie13"),
            (tr("page.inp.ie_14_properties_salinity_dependence_0_full_1_ignore"), "ie14"),
            (tr("page.inp.ie_15_brine_enthalpy_relation"), "ie15"),
        ]
        for i, (lbl, key) in enumerate(ie_fields):
            self.selec_entries[key] = _add_field(sg, i + 1, lbl, ds[key], 50)

        fe_title = QLabel(tr("page.inp.floating_parameters_fe"))
        fe_title.setStyleSheet(
            f"font-weight: bold; color: {Colors.ACCENT}; font-size: {Fonts.SIZE_S}pt;"
        )
        sg.addWidget(fe_title, len(ie_fields) + 2, 0, 1, 2)

        fe_fields = [
            (tr("page.inp.fe_1_permeability_salting_parameter_gamma_phir"), "fe1"),
            (tr("page.inp.fe_2_permeability_salting_parameter"), "fe2"),
            (tr("page.inp.fe_3_phase_change_window_size"), "fe3"),
            (tr("page.inp.fe_4_phase_change_window_size"), "fe4"),
        ]
        fe_start = len(ie_fields) + 3
        for i, (lbl, key) in enumerate(fe_fields):
            self.selec_entries[key] = _add_field(sg, fe_start + i, lbl, ds[key], 80)

        main_layout.addWidget(selec_group)
        main_layout.addStretch()
        scroll.setWidget(widget)
        return scroll

    def _create_param_tab(self):
        "Create param tab."
        from ...core.inp import get_default_param

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        widget = QWidget()
        main_layout = QVBoxLayout(widget)
        main_layout.setSpacing(10)

        dp = get_default_param()
        self.param_entries = {}

        r1_group = QGroupBox(tr("page.inp.record_1_control_integers"))
        r1g = QGridLayout(r1_group)
        r1_fields = [
            (tr("page.inp.mcyc_max_time_steps"), "mcyc", dp["mcyc"], 80),
            (tr("page.inp.mcypr_print_interval"), "mcypr", dp["mcypr"], 80),
            (tr("page.inp.texp_time_step_index_usually_4"), "texp", dp["texp"].strip(), 50),
            (tr("page.inp.be_solver_3_direct"), "be", dp["be"].strip(), 50),
        ]
        for r, (lbl, key, val, w) in enumerate(r1_fields):
            self.param_entries[key] = _add_field(r1g, r, lbl, val, w)
        main_layout.addWidget(r1_group)

        mop_group = QGroupBox(tr("page.inp.mop_simulation_options_1_digit_per_bit"))
        mg = QGridLayout(mop_group)
        default_mop = dp["mop_str"].ljust(24, "0")
        self.mop_entries = {}
        mop_defs = [
            (tr("page.inp.mop_1_short_printout_for_non_convergent_iterations"), 0),
            (tr("page.inp.mop_2_cycit_debug_print_0_off"), 1),
            (tr("page.inp.mop_3_multi_debug_print_0_off"), 2),
            (tr("page.inp.mop_4_qu_source_debug_print_0_off"), 3),
            (tr("page.inp.mop_5_eos_debug_print_0_off"), 4),
            (tr("page.inp.mop_6_lineq_debug_print_0_off"), 5),
            (tr("page.inp.mop_7_print_input_data_0_off_1_on"), 6),
            (tr("page.inp.mop_9_production_fluid_composition_0_mobility_1_phase"), 8),
            (tr("page.inp.mop_10_heat_conductivity_interpolation_0_sqrt_1_linear"), 9),
            (tr("page.inp.mop_11_interfacial_mobility_0_4"), 10),
            (tr("page.inp.mop_12_time_dependent_source_sink_interpolation_0_1_2"), 11),
            (tr("page.inp.mop_15_heat_exchange_0_off_1_on"), 14),
            (tr("page.inp.mop_16_automatic_time_step_control_0_off_2_4"), 15),
        ]
        for r, (lbl, idx) in enumerate(mop_defs):
            e = _add_field(mg, r, lbl, default_mop[idx], 30)
            self.mop_entries[idx] = e
        main_layout.addWidget(mop_group)

        r2_group = QGroupBox(tr("page.inp.param.record2_title"))
        r2g = QGridLayout(r2_group)
        r2_fields = [
            (tr("page.inp.tstart_start_time_s"), "tstart", dp.get("tstart", "0.").strip(), 100),
            (tr("page.inp.timax_max_simulation_time_s"), "timax", dp.get("timax", "4.3200e5"), 100),
            (tr("page.inp.delten_time_step_control_1_auto"), "delten", dp["delten"].strip(), 80),
            (
                tr("page.inp.deltmx_max_time_step_s_empty_inf"),
                "deltmx",
                dp.get("deltmx", "").strip(),
                100,
            ),
            (tr("page.inp.gravity_gf_m_s2_0_ignore"), "gravity", dp["gravity"], 80),
        ]
        for r, (lbl, key, val, w) in enumerate(r2_fields):
            self.param_entries[key] = _add_field(r2g, r, lbl, val, w)
        main_layout.addWidget(r2_group)

        r34_group = QGroupBox(tr("page.inp.param.record3_4_title"))
        r34g = QGridLayout(r34_group)
        r34_fields = [
            (tr("page.inp.re1_relative_convergence_criterion"), "re1", dp["re1"], 80),
            (tr("page.inp.re2_absolute_convergence_criterion"), "re2", dp["re2"].strip(), 80),
            (tr("page.inp.dlt_time_step_multiplier"), "dlt", dp["dlt"].strip(), 80),
        ]
        for r, (lbl, key, val, w) in enumerate(r34_fields):
            self.param_entries[key] = _add_field(r34g, r, lbl, val, w)
        main_layout.addWidget(r34_group)

        r5_group = QGroupBox(tr("page.inp.record_5_default_initial_conditions"))
        r5g = QGridLayout(r5_group)
        ic = dp["default_ic"]
        ic_fields = [
            (tr("page.inp.x1_pressure_p_pa"), "ic_p", ic[0], 120),
            (tr("page.inp.x2_gas_saturation_sg"), "ic_sg", ic[1], 120),
            (tr("page.inp.x3_dissolved_co2_mass_fraction_xco2"), "ic_xco2", ic[2], 120),
            (tr("page.inp.x4_temperature_t_c"), "ic_t", ic[3], 120),
        ]
        for r, (lbl, key, val, w) in enumerate(ic_fields):
            self.param_entries[key] = _add_field(r5g, r, lbl, val, w)
        main_layout.addWidget(r5_group)

        main_layout.addStretch()
        scroll.setWidget(widget)
        return scroll

    def _create_times_tab(self):
        "Create times tab."
        from ...core.inp import get_default_times

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        widget = QWidget()
        main_layout = QVBoxLayout(widget)
        main_layout.setSpacing(10)

        times_group = QGroupBox(tr("page.inp.times_output_times_one_per_line_unit_s"))
        tg = QVBoxLayout(times_group)
        self.text_times = QTextEdit()
        dt = get_default_times()
        self.text_times.setPlainText("\n".join(str(t) for t in dt))
        self.text_times.setStyleSheet(f"font-family: {Fonts.MONO}; font-size: {Fonts.SIZE_S}pt;")
        tg.addWidget(self.text_times)
        main_layout.addWidget(times_group)

        main_layout.addStretch()
        scroll.setWidget(widget)
        return scroll

    def set_mesh_data(self, mesh_data):
        "Set mesh data."
        self._mesh_data = mesh_data

        if hasattr(self, "_btn_find"):
            self._btn_find.setEnabled(True)
            self._btn_find.setToolTip("")

    def reset_mesh_context(self) -> None:
        self._mesh_data = None
        self._last_found_name = None
        self._btn_find.setEnabled(False)
        self._btn_copy.setEnabled(False)
        self._result_text.clear()
        self._output_dir = None
        self._btn_open_dir.setEnabled(False)

    def _create_gener_tab(self):
        "Create gener tab."
        from ...core.inp import get_default_gener

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        widget = QWidget()
        main_layout = QVBoxLayout(widget)
        main_layout.setSpacing(10)

        locate_group = QGroupBox(tr("page.inp.injection_point_locator"))
        locate_layout = QVBoxLayout(locate_group)
        locate_layout.setSpacing(6)

        desc = QLabel(tr("page.inp.help.nearest_cell_coordinates"))
        desc.setWordWrap(True)
        desc.setStyleSheet(
            f"color: {Colors.TEXT_DIM}; font-size: {Fonts.SIZE_S}pt; margin-bottom: 4px;"
        )
        locate_layout.addWidget(desc)

        coord_row = QHBoxLayout()
        coord_row.setSpacing(8)
        coord_row.addWidget(QLabel("X:"))
        self._entry_x = QLineEdit()
        self._entry_x.setFixedWidth(100)
        self._entry_x.setPlaceholderText(tr("page.inp.placeholder.x_coordinate"))
        coord_row.addWidget(self._entry_x)

        coord_row.addWidget(QLabel("Y:"))
        self._entry_y = QLineEdit("0")
        self._entry_y.setFixedWidth(80)
        self._entry_y.setPlaceholderText("0")
        self._entry_y.setToolTip(tr("page.inp.help.optional_y_coordinate"))
        coord_row.addWidget(self._entry_y)

        coord_row.addWidget(QLabel("Z:"))
        self._entry_z = QLineEdit()
        self._entry_z.setFixedWidth(100)
        self._entry_z.setPlaceholderText(tr("page.inp.placeholder.z_coordinate"))
        coord_row.addWidget(self._entry_z)

        self._btn_find = QPushButton("🔍 " + tr("page.inp.find_nearest_cell"))
        self._btn_find.setObjectName("AccentButton")
        self._btn_find.setFixedHeight(28)
        self._btn_find.setEnabled(False)
        self._btn_find.setToolTip(tr("page.inp.please_generate_mesh_first"))
        self._btn_find.clicked.connect(self._find_nearest_cell)
        coord_row.addWidget(self._btn_find)
        coord_row.addStretch()
        locate_layout.addLayout(coord_row)

        self._result_text = QTextEdit()
        self._result_text.setReadOnly(True)
        self._result_text.setFixedHeight(120)
        self._result_text.setStyleSheet(f"""
            background-color: {Colors.BG_INPUT};
            color: {Colors.TEXT};
            font-family: {Fonts.MONO};
            font-size: {Fonts.SIZE_S}pt;
            border: 1px solid {Colors.BORDER};
            border-radius: 4px;
            padding: 6px;
        """)
        self._result_text.setPlaceholderText(tr("page.inp.search_results_will_appear_here"))
        locate_layout.addWidget(self._result_text)

        copy_row = QHBoxLayout()
        copy_row.addStretch()
        self._btn_copy = QPushButton("📋 " + tr("page.inp.copy_element_name"))
        self._btn_copy.setFixedHeight(26)
        self._btn_copy.setEnabled(False)
        self._btn_copy.clicked.connect(self._copy_element_name)
        copy_row.addWidget(self._btn_copy)
        locate_layout.addLayout(copy_row)

        main_layout.addWidget(locate_group)

        gener_group = QGroupBox(tr("page.inp.gener_sources_sinks_paste_raw_format"))
        gg = QVBoxLayout(gener_group)
        self.text_gener = QTextEdit()
        self.text_gener.setPlainText(get_default_gener())
        self.text_gener.setStyleSheet(f"font-family: {Fonts.MONO}; font-size: {Fonts.SIZE_S}pt;")
        gg.addWidget(self.text_gener)
        main_layout.addWidget(gener_group)

        main_layout.addStretch()
        scroll.setWidget(widget)
        return scroll

    def _find_nearest_cell(self):
        "Find nearest cell."
        import numpy as np

        if not hasattr(self, "_mesh_data") or self._mesh_data is None:
            self._result_text.setPlainText(tr("page.inp.error.mesh_required"))
            return

        try:
            x = float(self._entry_x.text().strip())
        except ValueError:
            self._result_text.setPlainText(tr("page.inp.error.invalid_x_coordinate"))
            return
        try:
            z = float(self._entry_z.text().strip())
        except ValueError:
            self._result_text.setPlainText(tr("page.inp.error.invalid_z_coordinate"))
            return

        y_text = self._entry_y.text().strip()
        y = float(y_text) if y_text else 0.0

        target = np.array([x, y, z])
        centers = self._mesh_data.centers  # (n_cells, 3)
        labels = self._mesh_data.labels  # (n_cells,) 5-char element names
        materials = self._mesh_data.materials  # (n_cells,) material names

        dists = np.linalg.norm(centers - target, axis=1)
        idx = np.argmin(dists)

        nearest_name = labels[idx]
        nearest_mat = materials[idx]
        nearest_coord = centers[idx]
        min_dist = dists[idx]

        self._last_found_name = nearest_name.strip()

        lines = [
            f"{tr('page.inp.target_coords')}  X={x},  Y={y},  Z={z}",
            f"{'─' * 40}",
            f"{tr('page.inp.nearest_element')}  {nearest_name}",
            f"{tr('page.inp.material')}      {nearest_mat}",
            f"{tr('page.inp.cell_center')}  X={nearest_coord[0]:.6f},  Y={nearest_coord[1]:.6f},  Z={nearest_coord[2]:.6f}",
            f"{tr('page.inp.euclidean_dist')}      {min_dist:.6f}",
        ]
        self._result_text.setPlainText("\n".join(lines))
        self._btn_copy.setEnabled(True)

        print(
            f"{tr('page.inp.injection_point_located')} ({x}, {y}, {z}) → {nearest_name} ({tr('page.inp.dist')} {min_dist:.6f})"
        )

    def _copy_element_name(self):
        "Copy element name."
        from PySide6.QtWidgets import QApplication

        if hasattr(self, "_last_found_name") and self._last_found_name:
            QApplication.clipboard().setText(self._last_found_name)
            print(f"{tr('page.inp.element_name_copied_to_clipboard')} {self._last_found_name}")

    def _create_outpu_tab(self):
        "Create outpu tab."
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        widget = QWidget()
        main_layout = QVBoxLayout(widget)
        main_layout.setSpacing(10)

        outpu_group = QGroupBox(tr("page.inp.outpu_output_variables_control"))
        og = QVBoxLayout(outpu_group)
        self.text_outpu = QTextEdit()
        self.text_outpu.setPlainText("2\nSATURATION              1\nCOORDINATE")
        self.text_outpu.setStyleSheet(f"font-family: {Fonts.MONO}; font-size: {Fonts.SIZE_S}pt;")
        og.addWidget(self.text_outpu)
        main_layout.addWidget(outpu_group)

        main_layout.addStretch()
        scroll.setWidget(widget)
        return scroll

    IRP_MODELS = {
        "1": {
            "desc": tr("page.inp.linear_model"),
            "labels": ["Sl_min", "Sg_min", "Sl_max", "Sg_max"],
            "defaults": [0.0, 0.0, 1.0, 1.0],
        },
        "2": {"desc": tr("page.inp.power_law_model_krl_sl_n"), "labels": ["n"], "defaults": [1.0]},
        "3": {
            "desc": tr("page.inp.corey_s_curves"),
            "labels": ["Slr", "Sgr"],
            "defaults": [0.30, 0.05],
        },
        "4": {
            "desc": tr("page.inp.grant_s_curves"),
            "labels": ["Slr", "Sgr"],
            "defaults": [0.30, 0.05],
        },
        "5": {"desc": tr("page.inp.option.perfect_mobility"), "labels": [], "defaults": []},
        "6": {
            "desc": tr("page.inp.modified_stone_model"),
            "labels": ["Sar", "Slr", "Sgr", "n"],
            "defaults": [0.300, 0.01, 0.01, 3.0],
        },
        "7": {
            "desc": tr("page.inp.van_genuchten"),
            "labels": ["λ", "Slr", "Sls", "Sgr"],
            "defaults": [0.32, 0.15, 1.0, 0.01],
        },
        "8": {
            "desc": tr("page.inp.verma_et_al_sandstone_model"),
            "labels": ["Slr", "Sls", "A", "B", "C"],
            "defaults": [0.2, 0.895, 1.259, -1.7615, 0.5089],
        },
        "9": {
            "desc": tr("page.inp.parker_s_three_phase_model"),
            "labels": ["Sm", "n"],
            "defaults": [0.0, 1.84],
        },
        "10": {
            "desc": tr("page.inp.linear_relative_permeability_for_all_phases"),
            "labels": ["Sar", "Slr", "Sgr", "n"],
            "defaults": [0.3, 0.01, 0.01, 1.0],
        },
        "11": {"desc": tr("page.inp.faust_buckley_leverett"), "labels": [], "defaults": []},
        "12": {
            "desc": tr("page.inp.modified_stone_co2_corrected"),
            "labels": ["Sar", "Slr", "Sgr", "n"],
            "defaults": [0.300, 0.01, 0.01, 3.0],
        },
    }

    ICP_MODELS = {
        "1": {
            "desc": tr("page.inp.linear_model"),
            "labels": ["Pcp_max(Pa)", "Sl_min", "Sl_max"],
            "defaults": [0.0, 0.0, 1.0],
        },
        "2": {
            "desc": tr("page.inp.pickens_model"),
            "labels": ["P0(Pa)", "Slr", "Sl0", "x"],
            "defaults": [0.0, 0.0, 1.0, 1.0],
        },
        "3": {
            "desc": tr("page.inp.trust_model"),
            "labels": ["P0(Pa)", "Slr", "η", "Pe(Pa)"],
            "defaults": [0.0, 0.0, 1.0, 0.0],
        },
        "4": {"desc": tr("page.inp.milly_s_model"), "labels": ["Slr"], "defaults": [0.0]},
        "6": {
            "desc": tr("page.inp.leverett_model"),
            "labels": ["P0(Pa)", "Slr"],
            "defaults": [0.0, 0.0],
        },
        "7": {
            "desc": tr("page.inp.van_genuchten"),
            "labels": ["λ", "Slr", "1/P0(1/Pa)", "Pmax(Pa)", "Sls"],
            "defaults": [0.635, 0.01, 6.8e-4, 1.0e6, 0.999],
        },
        "8": {"desc": tr("page.inp.no_capillary_pressure"), "labels": [], "defaults": []},
        "9": {
            "desc": tr("page.inp.parker_et_al_three_phase_capillary"),
            "labels": ["Sm", "n", "α_gl", "α_la"],
            "defaults": [0.0, 1.84, 3.16, 3.48],
        },
        "10": {
            "desc": tr("page.inp.parker_direct_specification"),
            "labels": ["Sm", "n", "Pcgl_0(Pa)", "Pcla_0(Pa)"],
            "defaults": [0.0, 1.84, 0.0, 0.0],
        },
    }

    def populate_rocks(self, mat_names):
        "Populate rocks."
        from ...core.inp import get_default_rock

        self.mat_names = mat_names
        self.rock_entries = {}

        while self.rocks_layout.count():
            item = self.rocks_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        for mat in mat_names:
            dr = get_default_rock(mat)
            group = QGroupBox(tr("page.inp.lithology") + mat)
            g_main = QVBoxLayout(group)

            entries = {}

            props_widget = QWidget()
            flow = FlowLayout(props_widget, h_spacing=8, v_spacing=4)

            nad_pair = QWidget()
            nad_hl = QHBoxLayout(nad_pair)
            nad_hl.setContentsMargins(0, 0, 0, 0)
            nad_hl.setSpacing(3)
            nad_hl.addWidget(QLabel("NAD:"))
            cb_nad = QComboBox()
            cb_nad.addItems(["0", "1", "2"])
            cb_nad.setCurrentText(str(dr.get("nadm", 2)))
            cb_nad.setFixedWidth(50)
            nad_hl.addWidget(cb_nad)
            flow.addWidget(nad_pair)
            entries["nadm"] = cb_nad

            all_fields = [
                (tr("page.inp.density_kg_m3"), "density", dr["density"], 70),
                (tr("page.inp.porosity"), "porosity", dr["porosity"], 60),
                ("Kx(m²)", "perm_x", dr["perm_x"], 80),
                ("Ky(m²)", "perm_y", dr["perm_y"], 80),
                ("Kz(m²)", "perm_z", dr["perm_z"], 80),
                (tr("page.inp.conductivity_w_m_k"), "conductivity", dr["conductivity"], 60),
                (tr("page.inp.specific_heat_j_kg_k"), "specific_heat", dr["specific_heat"], 70),
                (tr("page.inp.compressibility_1_pa"), "compressibility", dr["compressibility"], 80),
            ]
            for label, key, val, w in all_fields:
                pair = QWidget()
                hl = QHBoxLayout(pair)
                hl.setContentsMargins(0, 0, 0, 0)
                hl.setSpacing(3)
                hl.addWidget(QLabel(label))
                e = QLineEdit(str(val))
                e.setFixedWidth(w)
                hl.addWidget(e)
                flow.addWidget(pair)
                entries[key] = e

            g_main.addWidget(props_widget)

            row_irp_widget = QWidget()
            row_irp = QHBoxLayout(row_irp_widget)
            row_irp.setContentsMargins(0, 0, 0, 0)

            row_irp.addWidget(QLabel(tr("page.inp.irp_model")))
            cb_irp = QComboBox()
            cb_irp.addItems(list(self.IRP_MODELS.keys()))
            cb_irp.setCurrentText(str(dr.get("irp", 12)))
            cb_irp.setFixedWidth(55)
            row_irp.addWidget(cb_irp)
            entries["irp"] = cb_irp

            irp_params_container = QWidget()
            irp_params_layout = QHBoxLayout(irp_params_container)
            irp_params_layout.setContentsMargins(0, 0, 0, 0)
            row_irp.addWidget(irp_params_container)
            row_irp.addStretch()
            entries["rp_params"] = []

            g_main.addWidget(row_irp_widget)

            row_icp_widget = QWidget()
            row_icp = QHBoxLayout(row_icp_widget)
            row_icp.setContentsMargins(0, 0, 0, 0)

            row_icp.addWidget(QLabel(tr("page.inp.icp_model")))
            cb_icp = QComboBox()
            cb_icp.addItems(list(self.ICP_MODELS.keys()))
            cb_icp.setCurrentText(str(dr.get("icp", 8)))
            cb_icp.setFixedWidth(55)
            row_icp.addWidget(cb_icp)
            entries["icp"] = cb_icp

            icp_params_container = QWidget()
            icp_params_layout = QHBoxLayout(icp_params_container)
            icp_params_layout.setContentsMargins(0, 0, 0, 0)
            row_icp.addWidget(icp_params_container)
            row_icp.addStretch()
            entries["cp_params"] = []

            g_main.addWidget(row_icp_widget)

            def _make_update_irp(container, combo, ent):
                def update(_=None):
                    model = combo.currentText()

                    layout = container.layout()
                    while layout.count():
                        item = layout.takeAt(0)
                        if item.widget():
                            item.widget().deleteLater()
                    info = self.IRP_MODELS.get(model, {"desc": "", "labels": [], "defaults": []})

                    desc_lbl = QLabel(f"[{info['desc']}]")
                    desc_lbl.setStyleSheet(
                        f"color: {Colors.ACCENT}; font-weight: bold; font-size: {Fonts.SIZE_S}pt;"
                    )
                    layout.addWidget(desc_lbl)

                    ent["rp_params"] = []
                    for label, default in zip(info["labels"], info["defaults"]):
                        layout.addWidget(QLabel(f"{label}:"))
                        e = QLineEdit(str(default))
                        e.setFixedWidth(65)
                        layout.addWidget(e)
                        ent["rp_params"].append(e)

                return update

            def _make_update_icp(container, combo, ent):
                def update(_=None):
                    model = combo.currentText()
                    layout = container.layout()
                    while layout.count():
                        item = layout.takeAt(0)
                        if item.widget():
                            item.widget().deleteLater()
                    info = self.ICP_MODELS.get(model, {"desc": "", "labels": [], "defaults": []})
                    desc_lbl = QLabel(f"[{info['desc']}]")
                    desc_lbl.setStyleSheet(
                        f"color: {Colors.ACCENT}; font-weight: bold; font-size: {Fonts.SIZE_S}pt;"
                    )
                    layout.addWidget(desc_lbl)
                    ent["cp_params"] = []
                    for label, default in zip(info["labels"], info["defaults"]):
                        layout.addWidget(QLabel(f"{label}:"))
                        e = QLineEdit(str(default))
                        e.setFixedWidth(75)
                        layout.addWidget(e)
                        ent["cp_params"].append(e)

                return update

            upd_irp = _make_update_irp(irp_params_container, cb_irp, entries)
            upd_icp = _make_update_icp(icp_params_container, cb_icp, entries)

            cb_irp.currentIndexChanged.connect(upd_irp)
            cb_icp.currentIndexChanged.connect(upd_icp)
            upd_irp()
            upd_icp()

            def _make_toggle_nad(r_irp, r_icp, cb):
                def toggle(_=None):
                    show = cb.currentText() == "2"
                    r_irp.setVisible(show)
                    r_icp.setVisible(show)

                return toggle

            toggle_nad = _make_toggle_nad(row_irp_widget, row_icp_widget, cb_nad)
            cb_nad.currentIndexChanged.connect(toggle_nad)
            toggle_nad()

            self.rock_entries[mat] = entries
            self.rocks_layout.addWidget(group)

        self.rocks_layout.addStretch()

    def _generate_inp(self):
        "Generate inp."
        print(tr("page.inp.start_generating_flow_inp"))
        self.inp_generated.emit()

    def collect_data(self, out_dir):
        "Collect data."
        from ...core.inp import write_flow_inp

        rocks_data = []
        for mat in self.mat_names:
            ent = self.rock_entries[mat]
            # NAD: QComboBox → currentText()
            nadm_widget = ent["nadm"]
            if isinstance(nadm_widget, QComboBox):
                nadm = int(nadm_widget.currentText())
            else:
                nadm = int(nadm_widget.text())
            # IRP/ICP: QComboBox → currentText()
            irp_widget = ent["irp"]
            if isinstance(irp_widget, QComboBox):
                irp = int(irp_widget.currentText())
            else:
                irp = int(irp_widget.text())
            icp_widget = ent["icp"]
            if isinstance(icp_widget, QComboBox):
                icp = int(icp_widget.currentText())
            else:
                icp = int(icp_widget.text())

            rock = {
                "name": mat[:5],
                "nadm": nadm,
                "density": float(ent["density"].text()),
                "porosity": float(ent["porosity"].text()),
                "perm_x": float(ent["perm_x"].text()),
                "perm_y": float(ent["perm_y"].text()),
                "perm_z": float(ent["perm_z"].text()),
                "conductivity": float(ent["conductivity"].text()),
                "specific_heat": float(ent["specific_heat"].text()),
                "compressibility": float(ent["compressibility"].text()),
                "irp": irp,
                "rp_params": [float(e.text()) for e in ent["rp_params"]],
                "icp": icp,
                "cp_params": [float(e.text()) for e in ent["cp_params"]],
            }
            rocks_data.append(rock)

        # PARAM
        pe = self.param_entries
        mop_vals = [0] * 24
        for idx, entry in self.mop_entries.items():
            mop_vals[idx] = int(entry.text())

        param_data = {
            "mcyc": int(pe["mcyc"].text()),
            "mcypr": int(pe["mcypr"].text()),
            "mop_vals": mop_vals,
            "texp": f"{pe['texp'].text():>3s}",
            "be": f"{pe['be'].text():>5s}",
            "tstart": pe["tstart"].text(),
            "timax": pe["timax"].text(),
            "delten": pe["delten"].text(),
            "deltmx": pe["deltmx"].text(),
            "gravity": float(pe["gravity"].text()),
            "re1": pe["re1"].text(),
            "re2": pe["re2"].text(),
            "dlt": pe["dlt"].text(),
            "default_ic": [
                pe["ic_p"].text().strip(),
                pe["ic_sg"].text().strip(),
                pe["ic_xco2"].text().strip(),
                pe["ic_t"].text().strip(),
            ],
        }

        # TIMES
        times_text = self.text_times.toPlainText().strip()
        times_data = [float(x.strip()) for x in times_text.split("\n") if x.strip()]

        # GENER / OUTPU
        gener_data = self.text_gener.toPlainText().strip()
        outpu_data = self.text_outpu.toPlainText().strip()

        # MULTI
        multi_data = [int(self.multi_entries[k].text()) for k in ("nk", "neq", "nph", "nb")]

        # SELEC
        selec_data = {k: self.selec_entries[k].text() for k in self.selec_entries}

        output_path = write_flow_inp(
            str(out_dir / "flow.inp"),
            rocks_data,
            param_data,
            times_data,
            gener_data,
            multi_data,
            selec_data,
            outpu_data,
        )

        self._output_dir = str(out_dir)
        if hasattr(self, "_btn_open_dir"):
            self._btn_open_dir.setEnabled(True)
        return output_path

    def _open_output_dir(self):
        "Open output dir."
        import os

        if hasattr(self, "_output_dir") and self._output_dir and os.path.isdir(self._output_dir):
            os.startfile(os.path.normpath(self._output_dir))
