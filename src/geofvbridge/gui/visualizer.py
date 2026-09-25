# -*- coding: utf-8 -*-
"PyVista-based mesh visualization panel."

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
    QWidgetAction,
)

from ..api import to_pyvista
from ..converter import cell_type_dimension
from ..i18n import get_language, tr
from ..styles import APP_NAME, Colors, Fonts, Sizes
from ..visualization import VisualizationBundle, filter_visualization_bundle

FIELD_TITLE_KEYS = {
    "material": "common.lithology_distribution",
    "quality": "visualizer.mesh_quality",
    "wireframe": "visualizer.mesh_wireframe",
}

MODEL_MODES = (
    "material",
    "quality",
    "wireframe",
    "connections",
    "boundaries",
    "sources",
    "tough_inactive",
)


_pyvista_available = False
try:
    import os

    os.environ["QT_API"] = "pyside6"
    import pyvista as pv
    from pyvistaqt import QtInteractor

    _pyvista_available = True
except ImportError:
    pass

_interactive_available = _pyvista_available and os.environ.get("PYVISTA_OFF_SCREEN", "false").lower() not in {
    "1",
    "true",
    "yes",
}


def _meshio_visualization_copy(mesh, dimension: int):
    """Return a top-dimensional copy safe for ``pyvista.from_meshio``.

    Meshio's Gmsh reader may expose entity-based ``cell_sets`` whose indices
    refer to the original entity block rather than a compact per-block array.
    PyVista asks Meshio to convert those sets in place and can consequently
    raise ``IndexError``. FE display needs only top-dimensional connectivity
    and aligned cell data, so cell/point sets are deliberately omitted here.
    """
    import meshio
    import numpy as np

    selected = [
        index
        for index, block in enumerate(mesh.cells)
        if cell_type_dimension(block.type) == dimension
    ]
    if not selected:
        selected = list(range(len(mesh.cells)))
    cells = [
        (mesh.cells[index].type, np.asarray(mesh.cells[index].data, dtype=int).copy())
        for index in selected
    ]
    cell_data = {
        name: [np.asarray(values[index]).copy() for index in selected]
        for name, values in mesh.cell_data.items()
        if len(values) == len(mesh.cells)
    }
    return meshio.Mesh(
        np.asarray(mesh.points, dtype=float).copy(),
        cells,
        point_data={name: np.asarray(values).copy() for name, values in mesh.point_data.items()},
        cell_data=cell_data,
        field_data={name: np.asarray(values).copy() for name, values in mesh.field_data.items()},
    )


class Visualizer(QWidget):
    "Provide the Visualizer component."

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("VisualizerFrame")
        self.setMinimumWidth(Sizes.VISUALIZER_W)
        self.plotter = None
        self._mesh_mode = "2d"
        self._view_key = "auto"
        self._annotations = {}
        self._model = None
        self._inactive_cells = set()
        self._inactive_face_ids = set()
        self._bundle = None
        self._bundle_cache = {}
        self._full_mesh = None
        self._total_cells = 0
        self._material_names = ()
        self._material_ids_by_name = {}
        self._visible_materials = set()
        self._material_checks = {}
        self._updating_material_checks = False
        self._display_mode = "material"
        self._origin_mode = "direct_3d"
        self._popout_plotters = []
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QWidget()
        header.setFixedHeight(36)
        header.setStyleSheet(
            f"background-color: {Colors.BG_PANEL}; border-left: 1px solid {Colors.BORDER};"
        )
        hl = QHBoxLayout(header)
        hl.setContentsMargins(12, 0, 8, 0)

        title = QLabel(tr("visualizer.title"))
        title.setStyleSheet(
            f"color: {Colors.TEXT_DIM}; font-size: {Fonts.SIZE_S}pt; font-weight: bold;"
        )
        hl.addWidget(title)
        hl.addStretch()

        self.combo_mode = QComboBox()
        zh = get_language() == "zh_CN"
        mode_items = [
            ("material", tr("common.lithology_distribution")),
            ("quality", tr("visualizer.mesh_quality")),
            ("wireframe", tr("visualizer.mesh_wireframe")),
            ("connections", "FV 连接网络" if zh else "FV connections"),
            ("boundaries", "边界面" if zh else "Boundary faces"),
            ("sources", "源项单元" if zh else "Source cells"),
            (
                "tough_inactive",
                "TOUGH 无限体积单元" if zh else "TOUGH inactive cells",
            ),
        ]
        for mode, label in mode_items:
            self.combo_mode.addItem(label, mode)
        self.combo_mode.setMinimumWidth(125)
        self.combo_mode.setStyleSheet(f"font-size: {Fonts.SIZE_S}pt;")
        self.combo_mode.currentIndexChanged.connect(self._on_mode_change)
        hl.addWidget(self.combo_mode)

        self.combo_view = QComboBox()
        self.combo_view.addItem(tr("visualizer.auto_view"), "auto")
        self.combo_view.addItem(tr("visualizer.isometric"), "isometric")
        self.combo_view.addItem("XY", "xy")
        self.combo_view.addItem("XZ", "xz")
        self.combo_view.addItem("YZ", "yz")
        self.combo_view.setMinimumWidth(105)
        self.combo_view.setStyleSheet(f"font-size: {Fonts.SIZE_S}pt;")
        self.combo_view.setToolTip(tr("visualizer.help.auto_view"))
        self.combo_view.currentIndexChanged.connect(self._on_view_change)
        hl.addWidget(self.combo_view)

        self.btn_reset = QPushButton(tr("visualizer.reset_view"))
        self.btn_reset.setFixedHeight(26)
        self.btn_reset.clicked.connect(self._reset_view)
        hl.addWidget(self.btn_reset)

        self.btn_popout = QPushButton(tr("visualizer.popout_view"))
        self.btn_popout.setObjectName("AccentButton")
        self.btn_popout.setProperty("compact", True)
        self.btn_popout.setFixedHeight(26)
        self.btn_popout.setMinimumWidth(90)
        self.btn_popout.clicked.connect(self._popout_view)
        hl.addWidget(self.btn_popout)

        layout.addWidget(header)
        self._setup_material_filter(layout)

        if _interactive_available:
            try:
                pv.global_theme.background = Colors.BG_DARK
                pv.global_theme.font.color = Colors.TEXT

                interactor = QtInteractor()
                interactor.set_background(Colors.BG_DARK)
                self.plotter = interactor

                layout.addWidget(self.plotter)
            except Exception as e:
                try:
                    if "interactor" in locals() and interactor is not None:
                        interactor.hide()
                        interactor.setParent(None)
                        interactor.close()
                        interactor.deleteLater()
                except Exception:
                    pass
                self.plotter = None

                import traceback

                err_detail = traceback.format_exc()
                print(
                    f"[Visualizer] {tr('visualizer.error.rendering_init_failed')} {e}\n{err_detail}"
                )
                self._add_placeholder(
                    layout,
                    f"{tr('visualizer.error.rendering_init_failed')}\n{type(e).__name__}\n\n{tr('visualizer.please_run_the_program_in_terminal')}\n{tr('visualizer.not_ipython_jupyter')}",
                )
        else:
            self._add_placeholder(
                layout, tr("visualizer.pyvista_is_not_installed_cannot_display_3d_view")
            )

        self.status_label = QLabel(tr("visualizer.ready_please_generate_mesh_first"))
        self.status_label.setStyleSheet(f"""
            color: {Colors.TEXT_DIM};
            font-size: {Fonts.SIZE_S}pt;
            padding: 4px 12px;
            background-color: {Colors.BG_PANEL};
        """)
        self.status_label.setFixedHeight(24)
        layout.addWidget(self.status_label)

        self._mesh = None
        self._field_name = None
        self._set_available_modes(set())

    def _setup_material_filter(self, layout) -> None:
        self.filter_bar = QWidget()
        self.filter_bar.setObjectName("MaterialFilterBar")
        self.filter_bar.setFixedHeight(34)
        self.filter_bar.setStyleSheet(
            f"background-color:{Colors.BG_PANEL};"
            f"border-left:1px solid {Colors.BORDER};"
            f"border-top:1px solid {Colors.BORDER};"
        )
        row = QHBoxLayout(self.filter_bar)
        row.setContentsMargins(12, 3, 8, 3)
        row.setSpacing(8)
        label = QLabel(tr("visualizer.lithology_filter"))
        label.setStyleSheet(f"color:{Colors.TEXT_DIM};font-size:{Fonts.SIZE_S}pt;")
        row.addWidget(label)
        self.filter_summary = QLabel()
        self.filter_summary.setStyleSheet(f"color:{Colors.TEXT};font-size:{Fonts.SIZE_S}pt;")
        row.addWidget(self.filter_summary)
        row.addStretch()

        self.btn_material_filter = QPushButton()
        self.btn_material_filter.setText(tr("visualizer.choose_lithologies"))
        self.btn_material_filter.setProperty("compact", True)
        self.btn_material_filter.setFixedHeight(26)
        self.btn_material_filter.setMinimumWidth(96)
        row.addWidget(self.btn_material_filter)

        self.material_menu = QMenu(self.btn_material_filter)
        popup = QWidget()
        popup_layout = QVBoxLayout(popup)
        popup_layout.setContentsMargins(8, 8, 8, 8)
        popup_layout.setSpacing(6)
        controls = QHBoxLayout()
        self.btn_select_all_materials = QPushButton(tr("visualizer.select_all"))
        self.btn_clear_materials = QPushButton(tr("visualizer.clear_all"))
        for button in (self.btn_select_all_materials, self.btn_clear_materials):
            button.setProperty("compact", True)
            button.setFixedHeight(24)
            controls.addWidget(button)
        popup_layout.addLayout(controls)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setMinimumWidth(220)
        scroll.setMaximumHeight(240)
        self.material_check_widget = QWidget()
        self.material_check_layout = QVBoxLayout(self.material_check_widget)
        self.material_check_layout.setContentsMargins(2, 2, 2, 2)
        self.material_check_layout.setSpacing(3)
        self.material_check_layout.addStretch()
        scroll.setWidget(self.material_check_widget)
        popup_layout.addWidget(scroll)
        action = QWidgetAction(self.material_menu)
        action.setDefaultWidget(popup)
        self.material_menu.addAction(action)
        self.btn_material_filter.setMenu(self.material_menu)
        self.btn_select_all_materials.clicked.connect(
            lambda: self.set_visible_materials(self._material_names)
        )
        self.btn_clear_materials.clicked.connect(lambda: self.set_visible_materials(()))
        self.filter_bar.hide()
        layout.addWidget(self.filter_bar)

    def _add_placeholder(self, layout, text):
        "Add placeholder."
        placeholder = QLabel(text)
        placeholder.setAlignment(Qt.AlignCenter)
        placeholder.setStyleSheet(f"""
            color: {Colors.TEXT_DIM};
            font-size: {Fonts.SIZE_L}pt;
            border: 2px dashed {Colors.BORDER};
            border-radius: {Sizes.RADIUS}px;
            margin: 20px;
        """)
        layout.addWidget(placeholder)

    @property
    def available_materials(self) -> tuple[str, ...]:
        return self._material_names

    @property
    def visible_materials(self) -> frozenset[str]:
        return frozenset(self._visible_materials)

    def _set_material_catalog(self, materials, material_ids) -> None:
        names = tuple(dict.fromkeys(str(name) for name in materials))
        old_names = set(self._material_names)
        old_visible = set(self._visible_materials)
        new_names = set(names)
        if old_names:
            selected = (old_visible & new_names) | (new_names - old_names)
        else:
            selected = set(new_names)
        catalog_changed = names != self._material_names
        self._material_names = names
        self._material_ids_by_name = {
            name: int(material_ids[name]) for name in names if name in material_ids
        }
        self._visible_materials = selected
        if catalog_changed:
            self._rebuild_material_checks()
        else:
            self._sync_material_checks()
        self.filter_bar.setVisible(bool(names))
        self._update_material_filter_summary()

    def _rebuild_material_checks(self) -> None:
        while self.material_check_layout.count():
            item = self.material_check_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._material_checks = {}
        for name in self._material_names:
            checkbox = QCheckBox(name)
            checkbox.setChecked(name in self._visible_materials)
            checkbox.toggled.connect(
                lambda checked, material=name: self._material_toggled(material, checked)
            )
            self.material_check_layout.addWidget(checkbox)
            self._material_checks[name] = checkbox
        self.material_check_layout.addStretch()

    def _sync_material_checks(self) -> None:
        self._updating_material_checks = True
        try:
            for name, checkbox in self._material_checks.items():
                blocked = checkbox.blockSignals(True)
                checkbox.setChecked(name in self._visible_materials)
                checkbox.blockSignals(blocked)
        finally:
            self._updating_material_checks = False

    def _material_toggled(self, material: str, checked: bool) -> None:
        if self._updating_material_checks:
            return
        if checked:
            self._visible_materials.add(material)
        else:
            self._visible_materials.discard(material)
        self._update_material_filter_summary()
        self._refresh_material_filter()

    def set_visible_materials(self, materials) -> None:
        selected = {str(name) for name in materials} & set(self._material_names)
        changed = selected != self._visible_materials
        self._visible_materials = selected
        self._sync_material_checks()
        self._update_material_filter_summary()
        if changed:
            self._refresh_material_filter()

    def _update_material_filter_summary(self) -> None:
        total = len(self._material_names)
        selected = len(self._visible_materials)
        if total and selected == total:
            text = tr("visualizer.all_lithologies", count=total)
        else:
            text = tr("visualizer.selected_lithologies", selected=selected, total=total)
        self.filter_summary.setText(text)

    def _clear_material_filter(self) -> None:
        self._material_names = ()
        self._material_ids_by_name = {}
        self._visible_materials.clear()
        self._rebuild_material_checks()
        self._update_material_filter_summary()
        self.filter_bar.hide()

    def _visible_model_cell_ids(self) -> set[int]:
        if self._model is None:
            return set()
        return {
            cell.id
            for cell in self._model.cells
            if cell.material in self._visible_materials
        }

    def set_annotations(self, annotations):
        "Set annotations."
        self._annotations = annotations

    def _set_available_modes(self, modes) -> None:
        available = set(modes)
        model = self.combo_mode.model()
        for index in range(self.combo_mode.count()):
            item = model.item(index)
            if item is not None:
                item.setEnabled(self.combo_mode.itemData(index) in available)

    def clear_display(self) -> None:
        self._model = None
        self._bundle = None
        self._bundle_cache.clear()
        self._full_mesh = None
        self._mesh = None
        self._total_cells = 0
        self._field_name = None
        self._inactive_cells.clear()
        self._inactive_face_ids.clear()
        self._clear_material_filter()
        self._set_available_modes(set())
        if self.plotter:
            self.plotter.clear()
            self.plotter.update()
        self.status_label.setText(tr("visualizer.ready_please_generate_mesh_first"))

    def display_mesh(
        self,
        mesh,
        field_name="material",
        title_key="common.lithology_distribution",
        mesh_mode=None,
    ):
        "Display mesh."

        self._model = None
        self._bundle = None
        self._mesh = mesh
        self._field_name = field_name
        self._display_mode = field_name
        if mesh_mode in ("2d", "3d"):
            self._mesh_mode = mesh_mode
            self._origin_mode = "native_2d" if mesh_mode == "2d" else "direct_3d"

        if not self.plotter:
            self._update_status(title_key)
            return

        self.plotter.clear()
        if mesh.n_cells == 0:
            self._render_empty_view(self.plotter)
            self._update_status(title_key)
            return

        if field_name and field_name in mesh.cell_data:
            if field_name == "material":
                material_ids = tuple(self._material_ids_by_name.values())
                self.plotter.add_mesh(
                    mesh,
                    scalars=field_name,
                    show_edges=True,
                    edge_color="#333333",
                    cmap="Set1",
                    line_width=0.5,
                    annotations=getattr(self, "_annotations", None),
                    clim=(
                        min(material_ids) - 0.5,
                        max(material_ids) + 0.5,
                    )
                    if material_ids
                    else None,
                    scalar_bar_args={"title": tr("visualizer.material")},
                )
            elif field_name == "quality":
                self.plotter.add_mesh(
                    mesh,
                    scalars=field_name,
                    show_edges=True,
                    edge_color="#333333",
                    cmap="RdBu",
                    clim=(0.0, 1.0),
                    line_width=0.5,
                    scalar_bar_args={"title": tr("visualizer.average_cell_quality")},
                )
            else:
                self.plotter.add_mesh(
                    mesh,
                    scalars=field_name,
                    show_edges=True,
                    edge_color="#333333",
                    cmap="viridis",
                    line_width=0.5,
                )
        else:
            self.plotter.add_mesh(
                mesh, show_edges=True, edge_color="#555555", color=Colors.ACCENT, line_width=0.5
            )
        self._add_orientation_axes(self.plotter)
        self._apply_view(self.plotter)

        self.plotter.update()

        self._update_status(title_key)

    def display_meshio(self, mesh, dimension: int):
        """Display the original finite-element mesh before FV conversion."""
        view_mesh = _meshio_visualization_copy(mesh, dimension)
        has_material = any("physical" in name.lower() for name in view_mesh.cell_data)
        fe_modes = {"wireframe"}
        if has_material:
            fe_modes.add("material")
        self._set_available_modes(fe_modes)
        if not _pyvista_available:
            self._model = None
            self._bundle = None
            self._full_mesh = None
            self._mesh = None
            self._clear_material_filter()
            self._mesh_mode = "3d" if dimension == 3 else "2d"
            self._origin_mode = "direct_3d" if dimension == 3 else "native_2d"
            self.status_label.setText(
                f"{sum(len(block.data) for block in view_mesh.cells):,} FE cells · "
                f"{len(view_mesh.points):,} points"
            )
            return
        grid = pv.from_meshio(view_mesh)
        physical_key = next(
            (name for name in grid.cell_data if "physical" in name.lower()), None
        )
        if physical_key is not None:
            grid.cell_data["material"] = grid.cell_data[physical_key]
            annotations = {
                int(values[0]): name
                for name, values in view_mesh.field_data.items()
                if len(values) >= 2 and int(values[1]) == dimension
            }
            physical_ids = sorted(
                int(value) for value in np.unique(grid.cell_data["material"])
            )
            for physical_id in physical_ids:
                annotations.setdefault(physical_id, f"Physical {physical_id}")
            materials = [annotations[physical_id] for physical_id in physical_ids]
            material_ids = {
                annotations[physical_id]: physical_id for physical_id in physical_ids
            }
            self._set_material_catalog(materials, material_ids)
        else:
            self._clear_material_filter()
        initial_mode = "material" if physical_key is not None else "wireframe"
        self._model = None
        self._bundle = None
        self._bundle_cache.clear()
        self._full_mesh = grid
        self._total_cells = grid.n_cells
        self._mesh_mode = "3d" if dimension == 3 else "2d"
        self._mesh = self._filtered_fe_mesh()
        self._field_name = initial_mode
        self._display_mode = initial_mode
        self._sync_mode_combo(initial_mode)
        self._origin_mode = "direct_3d" if dimension == 3 else "native_2d"
        self._render_fe_mode(initial_mode)

    @staticmethod
    def _selected_boundary_overlay(model, face_ids):
        selected = {int(value) for value in face_ids}
        if not selected:
            return pv.PolyData()
        owners = {boundary.face: boundary.cell for boundary in model.boundaries}
        faces: list[int] = []
        owner_ids: list[int] = []
        kept_face_ids: list[int] = []
        for face_id in selected:
            owner = owners.get(face_id)
            if owner is None:
                continue
            nodes = model.faces[face_id].nodes
            faces.extend((len(nodes), *nodes))
            owner_ids.append(owner)
            kept_face_ids.append(face_id)
        overlay = pv.PolyData(model.points, faces=np.asarray(faces, dtype=int))
        overlay.cell_data["owner_cell_id"] = np.asarray(owner_ids, dtype=int)
        overlay.cell_data["face_id"] = np.asarray(kept_face_ids, dtype=int)
        return overlay

    def display_model(
        self,
        model,
        mode="material",
        inactive_cells=None,
        inactive_face_ids=None,
    ):
        """Display an FVModel and its optional topology/semantic overlay."""
        mode = mode.lower().replace("-", "_")
        if mode not in MODEL_MODES:
            raise ValueError(f"Unknown visualization mode: {mode}")
        self._set_available_modes(MODEL_MODES)
        inactive = set(inactive_cells or ())
        inactive_faces = set(inactive_face_ids or ())
        if model is not self._model:
            self._bundle_cache.clear()
        self._model = model
        self._full_mesh = None
        self._inactive_cells = inactive
        self._inactive_face_ids = inactive_faces
        self._display_mode = mode
        self._field_name = mode
        self._sync_mode_combo(mode)
        self._mesh_mode = "3d" if model.dimension == 3 else "2d"
        preparation = model.metadata.get("solver_preparation", {})
        if model.metadata.get("extrusion") or preparation.get("mode") == "extruded_2d":
            self._origin_mode = "extruded_2d"
        elif model.dimension == 2:
            self._origin_mode = "native_2d"
        else:
            self._origin_mode = "direct_3d"
        materials = list(dict.fromkeys(cell.material for cell in model.cells))
        material_ids = {name: index for index, name in enumerate(materials)}
        self._set_material_catalog(materials, material_ids)
        self._total_cells = len(model.cells)
        if not _pyvista_available:
            self._mesh = None
            self._bundle = None
            self.status_label.setText(
                f"{len(model.cells):,} cells · {len(model.connections):,} connections"
            )
            return
        full_bundle = self._bundle_cache.get(mode)
        if full_bundle is None:
            if mode == "tough_inactive":
                reusable = next(
                    (
                        cached
                        for cached in self._bundle_cache.values()
                        if cached.grid is not None
                        and cached.grid.n_cells == len(model.cells)
                    ),
                    None,
                )
                if reusable is not None:
                    full_bundle = VisualizationBundle(
                        reusable.grid,
                        scalars="tough_inactive",
                        categorical=True,
                    )
                else:
                    full_bundle = to_pyvista(
                        model,
                        mode,
                        inactive_cells=self._inactive_cells,
                    )
            else:
                full_bundle = to_pyvista(model, mode, inactive_cells=self._inactive_cells)
            self._bundle_cache[mode] = full_bundle
        if mode == "tough_inactive":
            cell_ids = np.asarray(full_bundle.grid.cell_data["cell_id"], dtype=int)
            full_bundle.grid.cell_data["tough_inactive"] = np.isin(
                cell_ids,
                tuple(self._inactive_cells),
            ).astype(int)
            full_bundle.overlay = self._selected_boundary_overlay(
                model,
                self._inactive_face_ids,
            )
        bundle = filter_visualization_bundle(
            full_bundle,
            self._visible_model_cell_ids(),
            mode,
        )
        self._bundle = bundle
        self._mesh = bundle.grid
        self._annotations = {
            material_ids[name]: name
            for name in materials
            if name in self._visible_materials
        }
        if not _interactive_available or not self.plotter:
            self._update_status()
            return
        self._render_bundle(self.plotter, bundle, mode)
        self._update_status()

    def _filtered_fe_mesh(self):
        if self._full_mesh is None:
            return None
        if "material" not in self._full_mesh.cell_data:
            return self._full_mesh
        selected_ids = [
            self._material_ids_by_name[name]
            for name in self._material_names
            if name in self._visible_materials
        ]
        values = np.asarray(self._full_mesh.cell_data["material"], dtype=int)
        indices = np.flatnonzero(np.isin(values, selected_ids))
        return self._full_mesh.extract_cells(indices)

    def _refresh_material_filter(self) -> None:
        camera_position = None
        if self.plotter is not None and hasattr(self.plotter, "camera_position"):
            camera_position = self.plotter.camera_position
        if self._model is not None:
            self.display_model(
                self._model,
                self._display_mode,
                self._inactive_cells,
                self._inactive_face_ids,
            )
        elif self._full_mesh is not None:
            self._mesh = self._filtered_fe_mesh()
            self._render_fe_mode(self._display_mode)
        if (
            camera_position is not None
            and self.plotter is not None
            and self._mesh is not None
            and self._mesh.n_cells
        ):
            self.plotter.camera_position = camera_position
            self.plotter.update()

    def _render_fe_mode(self, mode: str) -> None:
        if self._mesh is None:
            return
        self._display_mode = mode
        self._field_name = mode
        self._annotations = {
            material_id: name
            for name, material_id in self._material_ids_by_name.items()
            if name in self._visible_materials
        }
        title_key = FIELD_TITLE_KEYS.get(mode, "visualizer.title")
        if mode == "wireframe":
            if not self.plotter:
                self._update_status(title_key)
                return
            self.plotter.clear()
            if self._mesh.n_cells:
                self.plotter.add_mesh(
                    self._mesh,
                    style="wireframe",
                    color=Colors.ACCENT,
                    line_width=1,
                )
                self._add_orientation_axes(self.plotter)
                self._apply_view(self.plotter)
                self.plotter.update()
            else:
                self._render_empty_view(self.plotter)
            self._update_status(title_key)
            return
        self.display_mesh(
            self._mesh,
            "material" if mode == "material" else mode,
            title_key,
        )

    def _sync_mode_combo(self, mode: str) -> None:
        index = self.combo_mode.findData(mode)
        if index < 0 or index == self.combo_mode.currentIndex():
            return
        previous = self.combo_mode.blockSignals(True)
        self.combo_mode.setCurrentIndex(index)
        self.combo_mode.blockSignals(previous)

    def _render_bundle(self, plotter, bundle, mode: str) -> None:
        """Render one bundle identically in the embedded and pop-out views."""
        plotter.clear()
        plotter.set_background(Colors.BG_DARK)
        if bundle.grid.n_cells == 0:
            self._render_empty_view(plotter, already_cleared=True)
            return
        if mode == "wireframe":
            plotter.add_mesh(
                bundle.grid,
                style="wireframe",
                color=Colors.ACCENT,
                line_width=1,
            )
        elif bundle.overlay is None:
            kwargs = {
                "show_edges": True,
                "edge_color": "#333333",
                "line_width": 0.5,
            }
            if bundle.scalars and bundle.scalars in bundle.grid.cell_data:
                kwargs["scalars"] = bundle.scalars
                if mode == "material":
                    kwargs["cmap"] = "Set1"
                    kwargs["clim"] = (-0.5, max(len(self._material_names) - 0.5, 0.5))
                    kwargs["annotations"] = self._annotations
                    kwargs["scalar_bar_args"] = {"title": tr("visualizer.material")}
                elif mode == "tough_inactive":
                    kwargs["cmap"] = ["#707080", Colors.ERROR]
                    kwargs["clim"] = (-0.5, 1.5)
                    kwargs["annotations"] = {
                        0: "Active",
                        1: "TOUGH inactive",
                    }
                    kwargs["scalar_bar_args"] = {"title": "TOUGH"}
                else:
                    kwargs["cmap"] = "RdBu"
                    kwargs["clim"] = (0.0, 1.0)
                    kwargs["scalar_bar_args"] = {
                        "title": tr("visualizer.average_cell_quality")
                    }
            else:
                kwargs["color"] = Colors.ACCENT
            plotter.add_mesh(bundle.grid, **kwargs)
        elif mode == "tough_inactive":
            plotter.add_mesh(
                bundle.grid,
                scalars="tough_inactive",
                cmap=["#707080", Colors.ERROR],
                clim=(-0.5, 1.5),
                annotations={0: "Active", 1: "TOUGH inactive"},
                scalar_bar_args={"title": "TOUGH"},
                show_edges=True,
                edge_color="#333333",
                line_width=0.5,
            )
            if bundle.overlay.n_points:
                plotter.add_mesh(
                    bundle.overlay,
                    color="#FFD54F",
                    opacity=0.9,
                    show_edges=True,
                    edge_color="#5D4A00",
                )
        else:
            plotter.add_mesh(
                bundle.grid,
                color="#707080",
                opacity=0.22,
                show_edges=True,
                edge_color="#404050",
            )
            if bundle.overlay.n_points:
                if mode in {"connections", "fv_topology"}:
                    plotter.add_mesh(
                        bundle.overlay,
                        scalars=bundle.scalars,
                        cmap="RdBu",
                        clim=(0.0, 1.0),
                        line_width=3,
                    )
                elif mode == "sources":
                    plotter.add_mesh(
                        bundle.overlay,
                        color=Colors.ERROR,
                        point_size=14,
                        render_points_as_spheres=True,
                    )
                else:
                    plotter.add_mesh(
                        bundle.overlay,
                        scalars=bundle.scalars,
                        cmap="Set1",
                        opacity=0.85,
                        show_edges=True,
                    )
        self._add_orientation_axes(plotter)
        self._apply_view(plotter)
        plotter.update()

    def _render_empty_view(self, plotter, *, already_cleared: bool = False) -> None:
        """Render a stable empty state when no lithology is selected."""
        if not already_cleared:
            plotter.clear()
            if hasattr(plotter, "set_background"):
                plotter.set_background(Colors.BG_DARK)
        if hasattr(plotter, "add_text"):
            plotter.add_text(
                tr("visualizer.no_lithology_selected"),
                position="upper_left",
                color=Colors.TEXT_MUTED,
                font_size=11,
            )
        self._add_orientation_axes(plotter)
        plotter.update()

    def _resolved_view_key(self):
        "Resolved view key."
        view_key = self.combo_view.currentData() or "auto"
        if view_key == "auto":
            if self._mesh_mode == "3d":
                return "isometric"
            if self._mesh is not None and getattr(self._mesh, "n_points", 1):
                bounds = tuple(self._mesh.bounds)
                spans = (
                    bounds[1] - bounds[0],
                    bounds[3] - bounds[2],
                    bounds[5] - bounds[4],
                )
                normal_axis = min(range(3), key=lambda axis: spans[axis])
                return {0: "yz", 1: "xz", 2: "xy"}[normal_axis]
            return "xy"
        return view_key

    def _apply_view(self, plotter):
        "Apply view."
        if self._mesh is not None and getattr(self._mesh, "n_points", 1) == 0:
            return
        view_key = self._resolved_view_key()
        view_methods = {
            "isometric": plotter.view_isometric,
            "xy": plotter.view_xy,
            "xz": plotter.view_xz,
            "yz": plotter.view_yz,
        }
        view_methods[view_key]()
        plotter.reset_camera()

    def _add_orientation_axes(self, plotter):
        "Add orientation axes."
        if self._mesh_mode == "3d":
            try:
                plotter.add_axes(
                    xlabel="X",
                    ylabel="Y",
                    zlabel="Z",
                    line_width=2,
                )
            except Exception:
                pass

    def _on_view_change(self, _idx):
        self._view_key = self.combo_view.currentData() or "auto"
        if self.plotter and self._mesh is not None:
            self._apply_view(self.plotter)
            self.plotter.update()
            self._update_status()

    def _update_status(self, title_key=None):
        if self._mesh is None:
            return
        if title_key is None:
            title_key = FIELD_TITLE_KEYS.get(self._field_name, "visualizer.title")
        if self._origin_mode == "extruded_2d":
            mode_text = tr("common.conversion.extruded_2d")
        elif self._origin_mode == "native_2d":
            mode_text = "原生二维" if get_language() == "zh_CN" else "native 2-D"
        else:
            mode_text = tr("common.conversion.direct_3d")
        view_text = self.combo_view.currentText()
        field_text = (
            self.combo_mode.currentText()
            if self._model is not None
            else tr(title_key)
        )
        visible_cells = self._mesh.n_cells
        total_cells = max(self._total_cells, visible_cells)
        cell_text = f"{visible_cells:,}/{total_cells:,}"
        self.status_label.setText(
            f"{tr('common.cells.label')}: {cell_text} · "
            f"{tr('visualizer.nodes')}: {self._mesh.n_points:,} · "
            f"{field_text} · {mode_text} · {tr('visualizer.view')}: {view_text}"
        )

    def _on_mode_change(self, idx):
        mode = self.combo_mode.itemData(idx)
        if not mode:
            return

        if self._model is not None:
            self.display_model(
                self._model,
                mode,
                self._inactive_cells,
                self._inactive_face_ids,
            )
            return

        if self._full_mesh is not None:
            self._render_fe_mode(mode)

    def _reset_view(self):
        if self.plotter and self._mesh is not None and getattr(self._mesh, "n_points", 1):
            self._apply_view(self.plotter)
            self.plotter.update()

    def _popout_view(self):
        "Popout view."
        if self._mesh is None:
            return

        try:
            from pyvistaqt import BackgroundPlotter

            title = f"{APP_NAME}: {self.combo_mode.currentText()}"
            p = BackgroundPlotter(
                show=True,
                app=QApplication.instance(),
                window_size=(800, 800),
                toolbar=True,
                menu_bar=True,
                editor=False,
                title=title,
            )
            if hasattr(p, "app_window"):
                p.app_window.setWindowTitle(title)
            if self._mesh.n_cells == 0:
                self._render_empty_view(p)
            elif self._bundle is not None and self._model is not None:
                self._render_bundle(p, self._bundle, self._display_mode)
            elif self._field_name == "wireframe":
                p.add_mesh(self._mesh, style="wireframe", color=Colors.ACCENT, line_width=1)
            elif self._field_name and self._field_name in self._mesh.cell_data:
                if self._field_name == "material":
                    p.add_mesh(
                        self._mesh,
                        scalars=self._field_name,
                        show_edges=True,
                        edge_color="#333333",
                        cmap="Set1",
                        clim=(-0.5, max(len(self._material_names) - 0.5, 0.5)),
                        annotations=getattr(self, "_annotations", None),
                        scalar_bar_args={"title": tr("visualizer.material")},
                    )
                elif self._field_name == "quality":
                    p.add_mesh(
                        self._mesh,
                        scalars=self._field_name,
                        show_edges=True,
                        edge_color="#333333",
                        cmap="RdBu",
                        clim=(0.0, 1.0),
                        scalar_bar_args={"title": tr("visualizer.average_cell_quality")},
                    )
                else:
                    p.add_mesh(
                        self._mesh,
                        scalars=self._field_name,
                        show_edges=True,
                        edge_color="#333333",
                        cmap="viridis",
                    )
            else:
                p.add_mesh(self._mesh, show_edges=True, edge_color="#555555", color=Colors.ACCENT)

            if self._bundle is None and self._mesh.n_cells:
                self._add_orientation_axes(p)
            if self.plotter is not None and hasattr(self.plotter, "camera_position"):
                p.camera_position = self.plotter.camera_position
            else:
                self._apply_view(p)
            p.update()
            self._popout_plotters.append(p)

        except Exception as e:
            print(f"{tr('visualizer.dialog_display_failed')} {e}")

    def close_plotter(self):
        for popout in self._popout_plotters:
            try:
                popout.close()
            except Exception:
                pass
        self._popout_plotters.clear()
        if self.plotter:
            self.plotter.close()
