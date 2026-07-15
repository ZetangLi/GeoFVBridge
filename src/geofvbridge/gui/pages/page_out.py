# -*- coding: utf-8 -*-
"TOUGH output extraction page."

import os

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ...i18n import tr
from ...styles import Colors, Fonts


class ExtractWorker(QThread):
    "Provide the ExtractWorker component."

    progress = Signal(int, str)
    result_ready = Signal(list)
    error = Signal(str)

    def __init__(self, out_path, mesh_path, output_dir, parent=None):
        super().__init__(parent)
        self.out_path = out_path
        self.mesh_path = mesh_path
        self.output_dir = output_dir

    def run(self):
        try:
            from ...core.out import parse_flow_out, parse_mesh_coords, write_tecplot

            def report_progress(percent, message):
                if self.isInterruptionRequested():
                    raise InterruptedError
                self.progress.emit(percent, message)

            self.progress.emit(2, tr("page.out.parsing_mesh_file"))
            coords, elem_order = parse_mesh_coords(self.mesh_path)
            if self.isInterruptionRequested():
                return
            if len(coords) == 0:
                self.error.emit(tr("page.out.error_no_cell_coordinates_found_in_mesh_file"))
                return

            self.progress.emit(5, tr("page.out.parsing_flow_out"))
            known_elements = set(coords.keys())
            time_steps = parse_flow_out(
                self.out_path,
                known_elements,
                progress_callback=report_progress,
            )
            if len(time_steps) == 0:
                self.error.emit(tr("page.out.error_no_time_step_data_extracted_from_flow_out"))
                return

            self.progress.emit(90, tr("page.out.generating_tecplot_files"))
            output_files = write_tecplot(
                time_steps,
                coords,
                elem_order,
                self.output_dir,
                progress_callback=report_progress,
            )

            self.result_ready.emit(output_files)

        except InterruptedError:
            return
        except Exception as e:
            import traceback

            traceback.print_exc()
            self.error.emit(str(e))


class OutPage(QWidget):
    "Provide the OutPage component."

    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker = None
        self._out_path = None
        self._mesh_path = None
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        title = QLabel(tr("page.out.post_processing_out_file_extraction"))
        title.setObjectName("SectionTitle")
        layout.addWidget(title)

        desc = QLabel(tr("page.out.description"))
        desc.setWordWrap(True)
        desc.setStyleSheet(
            f"color: {Colors.TEXT_DIM}; font-size: {Fonts.SIZE_M}pt; margin-bottom: 4px;"
        )
        layout.addWidget(desc)

        file_group = QGroupBox(tr("page.out.file_selection"))
        file_layout = QVBoxLayout(file_group)
        file_layout.setSpacing(8)

        out_row = QHBoxLayout()
        self._btn_select_out = QPushButton("📂 " + tr("page.out.select_flow_out_file"))
        self._btn_select_out.setObjectName("AccentButton")
        self._btn_select_out.setFixedHeight(32)
        self._btn_select_out.clicked.connect(self._browse_out_file)
        out_row.addWidget(self._btn_select_out)

        self._lbl_out_path = QLabel(tr("page.out.no_file_selected"))
        self._lbl_out_path.setStyleSheet(f"color: {Colors.TEXT_DIM}; font-size: {Fonts.SIZE_S}pt;")
        self._lbl_out_path.setWordWrap(True)
        out_row.addWidget(self._lbl_out_path, 1)
        file_layout.addLayout(out_row)

        self._lbl_mesh_status = QLabel("")
        self._lbl_mesh_status.setStyleSheet(
            f"color: {Colors.TEXT_DIM}; font-size: {Fonts.SIZE_S}pt; padding-left: 4px;"
        )
        file_layout.addWidget(self._lbl_mesh_status)

        layout.addWidget(file_group)

        extract_group = QGroupBox(tr("page.out.extraction_control"))
        extract_layout = QVBoxLayout(extract_group)
        extract_layout.setSpacing(8)

        btn_row = QHBoxLayout()
        self._btn_extract = QPushButton("▶  " + tr("page.out.start_extraction"))
        self._btn_extract.setObjectName("AccentButton")
        self._btn_extract.setFixedHeight(38)
        self._btn_extract.setEnabled(False)
        self._btn_extract.clicked.connect(self._start_extraction)
        btn_row.addWidget(self._btn_extract)
        btn_row.addStretch()
        extract_layout.addLayout(btn_row)

        self._progress_bar = QProgressBar()
        self._progress_bar.setValue(0)
        self._progress_bar.setFixedHeight(22)
        self._progress_bar.setStyleSheet(f"""
            QProgressBar {{
                border: 1px solid {Colors.BORDER};
                border-radius: 4px;
                background-color: {Colors.BG_INPUT};
                text-align: center;
                font-size: {Fonts.SIZE_S}pt;
                color: {Colors.TEXT};
            }}
            QProgressBar::chunk {{
                background-color: {Colors.ACCENT};
                border-radius: 3px;
            }}
        """)
        extract_layout.addWidget(self._progress_bar)

        self._lbl_status = QLabel(tr("common.ready"))
        self._lbl_status.setStyleSheet(f"color: {Colors.TEXT_DIM}; font-size: {Fonts.SIZE_S}pt;")
        extract_layout.addWidget(self._lbl_status)

        layout.addWidget(extract_group)

        result_group = QGroupBox(tr("page.out.extraction_results"))
        result_layout = QVBoxLayout(result_group)
        result_layout.setSpacing(6)

        self._result_text = QTextEdit()
        self._result_text.setReadOnly(True)
        self._result_text.setStyleSheet(f"""
            background-color: {Colors.BG_INPUT};
            color: {Colors.TEXT};
            font-family: {Fonts.MONO};
            font-size: {Fonts.SIZE_S}pt;
            border: 1px solid {Colors.BORDER};
            border-radius: 4px;
            padding: 6px;
        """)
        self._result_text.setPlaceholderText(tr("page.out.extraction_results_will_appear_here"))
        result_layout.addWidget(self._result_text)

        open_row = QHBoxLayout()
        open_row.addStretch()
        self._btn_open_dir = QPushButton("📂 " + tr("common.open_output_folder"))
        self._btn_open_dir.setFixedHeight(28)
        self._btn_open_dir.setEnabled(False)
        self._btn_open_dir.clicked.connect(self._open_output_dir)
        open_row.addWidget(self._btn_open_dir)
        result_layout.addLayout(open_row)

        layout.addWidget(result_group)
        layout.addStretch()

    def _browse_out_file(self):
        "Browse for out file."
        path, _ = QFileDialog.getOpenFileName(
            self,
            tr("page.out.select_tough2_output_file"),
            "",
            tr("page.out.tough2_output_files") + " (*.out);;All files (*.*)",
        )
        if not path:
            return

        self._out_path = path
        self._lbl_out_path.setText(path)
        self._lbl_out_path.setStyleSheet(f"color: {Colors.TEXT}; font-size: {Fonts.SIZE_S}pt;")

        base_dir = os.path.dirname(os.path.abspath(path))
        mesh_path = os.path.join(base_dir, "MESH")

        if not os.path.exists(mesh_path):
            for fname in os.listdir(base_dir):
                if fname.upper() == "MESH":
                    mesh_path = os.path.join(base_dir, fname)
                    break

        if os.path.exists(mesh_path):
            self._mesh_path = mesh_path
            self._lbl_mesh_status.setText(f"✓ {tr('page.out.mesh_file_found')} {mesh_path}")
            self._lbl_mesh_status.setStyleSheet(
                f"color: {Colors.SUCCESS}; font-size: {Fonts.SIZE_S}pt; padding-left: 4px;"
            )
            self._btn_extract.setEnabled(True)
        else:
            self._mesh_path = None
            self._lbl_mesh_status.setText(f"✗ {tr('page.out.error.mesh_file_not_found')}")
            self._lbl_mesh_status.setStyleSheet(
                f"color: {Colors.ERROR}; font-size: {Fonts.SIZE_S}pt; padding-left: 4px;"
            )
            self._btn_extract.setEnabled(False)

    def _start_extraction(self):
        "Start extraction."
        if not self._out_path or not self._mesh_path:
            return
        if self._worker is not None and self._worker.isRunning():
            return

        output_dir = os.path.join(os.path.dirname(self._out_path), "GeoFVBridge_Extract")

        self._progress_bar.setValue(0)
        self._result_text.clear()
        self._btn_extract.setEnabled(False)
        self._btn_select_out.setEnabled(False)
        self._btn_open_dir.setEnabled(False)
        self._lbl_status.setText(tr("page.out.extracting"))
        self._output_dir = output_dir

        self._worker = ExtractWorker(self._out_path, self._mesh_path, output_dir, self)
        self._worker.progress.connect(self._on_progress)
        self._worker.result_ready.connect(self._on_finished)
        self._worker.error.connect(self._on_error)
        self._worker.finished.connect(self._worker_stopped)
        self._worker.start()

        print(f"{tr('page.out.starting_out_file_extraction')} {self._out_path}")
        print(f"  {tr('common.output_directory')} {output_dir}")

    def _on_progress(self, percent, message):
        "Handle progress."
        self._progress_bar.setValue(percent)
        self._lbl_status.setText(message)

    def _on_finished(self, output_files):
        "Handle finished."
        self._progress_bar.setValue(100)
        self._lbl_status.setText(f"✓ {tr('common.extraction_complete')}")
        self._lbl_status.setStyleSheet(
            f"color: {Colors.SUCCESS}; font-size: {Fonts.SIZE_S}pt;"
        )

        lines = [
            f"{tr('page.out.extraction_complete_generated')} {len(output_files)} {tr('common.files.unit')}",
            f"{tr('common.output_directory')} {self._output_dir}",
            "─" * 50,
        ]
        for f in output_files:
            lines.append(f"  📄 {os.path.basename(f)}")
        self._result_text.setPlainText("\n".join(lines))

        self._btn_extract.setEnabled(True)
        self._btn_select_out.setEnabled(True)
        self._btn_open_dir.setEnabled(True)

        print(
            f"✓ {tr('page.out.extraction_complete_generated')} {len(output_files)} {tr('common.files.unit')}"
        )

    def _on_error(self, error_msg):
        "Handle error."
        self._progress_bar.setValue(0)
        self._lbl_status.setText(f"✗ {tr('page.out.extraction_failed')}")
        self._lbl_status.setStyleSheet(
            f"color: {Colors.ERROR}; font-size: {Fonts.SIZE_S}pt;"
        )
        self._result_text.setPlainText(f"{tr('common.error')} {error_msg}")

        self._btn_extract.setEnabled(True)
        self._btn_select_out.setEnabled(True)

        print(f"✗ {tr('page.out.out_extraction_failed')} {error_msg}")

    def _worker_stopped(self):
        worker = self._worker
        self._worker = None
        if worker is not None:
            worker.deleteLater()

    def shutdown(self) -> None:
        worker = self._worker
        if worker is not None and worker.isRunning():
            worker.requestInterruption()
            worker.wait()

    def _open_output_dir(self):
        "Open output dir."
        if hasattr(self, "_output_dir") and os.path.isdir(self._output_dir):
            os.startfile(os.path.normpath(self._output_dir))
