# -*- coding: utf-8 -*-
"Embedded application log console."

import sys
from datetime import datetime

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QColor, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ..i18n import tr
from ..styles import Colors, Fonts, Sizes


class _StdoutRedirector(QObject):
    "Provide the StdoutRedirector component."

    text_written = Signal(str, str)  # (text, level)

    def __init__(self, level="INFO"):
        super().__init__()
        self._level = level

    def write(self, text):
        if text.strip():
            self.text_written.emit(text, self._level)

    def flush(self):
        pass


class LogConsole(QWidget):
    "Provide the LogConsole component."

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ConsoleFrame")
        self._setup_ui()
        self._setup_redirect()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QWidget()
        header.setFixedHeight(28)
        header.setStyleSheet(
            f"background-color: {Colors.BG_PANEL}; border-top: 1px solid {Colors.BORDER};"
        )
        hl = QHBoxLayout(header)
        hl.setContentsMargins(12, 0, 8, 0)

        title = QLabel("▸ " + tr("console.console_log"))
        title.setStyleSheet(
            f"color: {Colors.TEXT_DIM}; font-size: {Fonts.SIZE_S}pt; font-weight: bold;"
        )
        hl.addWidget(title)
        hl.addStretch()

        btn_clear = QPushButton(tr("console.clear"))
        btn_clear.setFixedSize(50, 22)
        btn_clear.clicked.connect(self.clear)
        hl.addWidget(btn_clear)

        btn_export = QPushButton(tr("console.export"))
        btn_export.setFixedSize(50, 22)
        btn_export.clicked.connect(self.export_log)
        hl.addWidget(btn_export)

        layout.addWidget(header)

        self.output = QTextEdit()
        self.output.setObjectName("ConsoleOutput")
        self.output.setReadOnly(True)
        self.output.setMinimumHeight(Sizes.CONSOLE_H - 28)
        layout.addWidget(self.output)

    def _setup_redirect(self):
        "Set up redirect."
        self._stdout_redirector = _StdoutRedirector("INFO")
        self._stderr_redirector = _StdoutRedirector("ERROR")
        self._stdout_redirector.text_written.connect(self._append)
        self._stderr_redirector.text_written.connect(self._append)
        self._original_stdout = sys.stdout
        self._original_stderr = sys.stderr
        sys.stdout = self._stdout_redirector
        sys.stderr = self._stderr_redirector

    def restore_stdout(self):
        "Restore stdout."
        sys.stdout = self._original_stdout
        sys.stderr = self._original_stderr

    def log(self, message: str, level: str = "INFO"):
        "Log."
        self._append(message, level)

    def _append(self, text: str, level: str = "INFO"):
        "Append."
        cursor = self.output.textCursor()
        cursor.movePosition(QTextCursor.End)

        fmt = QTextCharFormat()
        timestamp = datetime.now().strftime("%H:%M:%S")

        color_map = {
            "INFO": Colors.TEXT,
            "SUCCESS": Colors.SUCCESS,
            "WARNING": Colors.WARNING,
            "ERROR": Colors.ERROR,
            "DEBUG": Colors.TEXT_DIM,
        }
        fmt.setForeground(QColor(color_map.get(level, Colors.TEXT)))

        prefix = f"[{timestamp}] "
        cursor.insertText(prefix + text + "\n", fmt)
        self.output.setTextCursor(cursor)
        self.output.ensureCursorVisible()

    def clear(self):
        self.output.clear()

    def export_log(self):
        path, _ = QFileDialog.getSaveFileName(
            self, tr("console.export_log"), "geofvbridge_log.txt", "Text Files (*.txt)"
        )
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.output.toPlainText())
            self.log(f"{tr('console.log_exported_to')} {path}", "SUCCESS")
