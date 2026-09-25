"""Cancellable QProcess wrapper for long mesh conversions."""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, QTimer, Signal


class ConversionProcess(QObject):
    """Run geofvbridge.worker outside the GUI process."""

    progress = Signal(int, str)
    completed = Signal(object)
    failed = Signal(str, str)
    cancelled = Signal()

    def __init__(
        self,
        source: Path,
        output: Path,
        *,
        petrel_options: dict[str, object] | None = None,
        length_unit: str = "m",
        parent=None,
    ) -> None:
        super().__init__(parent)
        output = output.resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        self.staging_dir = Path(
            tempfile.mkdtemp(prefix=".geofvbridge-", dir=output.parent)
        ).resolve()
        self.request_path = self.staging_dir / "request.json"
        request = {
            "input": str(source.resolve()),
            "output": str(output),
            "staging_dir": str(self.staging_dir),
            "length_unit": length_unit,
            "petrel_options": petrel_options or {},
        }
        self.request_path.write_text(
            json.dumps(request, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self.process = QProcess(self)
        self.process.setProgram(sys.executable)
        self.process.setArguments(
            ["-m", "geofvbridge.worker", "--request", str(self.request_path)]
        )
        # A GUI launched directly from src/geofvbridge/gui/app.py can import
        # GeoFVBridge because app.py adjusts sys.path. QProcess only inherits the
        # operating-system environment, not that runtime sys.path, so explicitly
        # expose the package root to the isolated worker.
        environment = QProcessEnvironment.systemEnvironment()
        package_root = str(Path(__file__).resolve().parents[2])
        python_path = environment.value("PYTHONPATH")
        path_entries = [entry for entry in python_path.split(os.pathsep) if entry]
        normalized_entries = {os.path.normcase(os.path.abspath(entry)) for entry in path_entries}
        if os.path.normcase(os.path.abspath(package_root)) not in normalized_entries:
            path_entries.insert(0, package_root)
        environment.insert("PYTHONPATH", os.pathsep.join(path_entries))
        environment.insert("PYTHONUTF8", "1")
        environment.insert("PYTHONIOENCODING", "utf-8")
        self.process.setProcessEnvironment(environment)
        self.process.setProcessChannelMode(QProcess.SeparateChannels)
        self.process.readyReadStandardOutput.connect(self._read_stdout)
        self.process.readyReadStandardError.connect(self._read_stderr)
        self.process.errorOccurred.connect(self._process_error)
        self.process.finished.connect(self._finished)
        self._stdout_buffer = ""
        self._stderr = ""
        self._result: dict[str, object] | None = None
        self._error_message = ""
        self._cancel_requested = False
        self._terminal_emitted = False

    def start(self) -> None:
        self.process.start()

    def cancel(self) -> None:
        if self.process.state() == QProcess.NotRunning:
            return
        self._cancel_requested = True
        self.progress.emit(0, "cancelling")
        self.process.terminate()
        QTimer.singleShot(3000, self._kill_if_running)

    def _kill_if_running(self) -> None:
        if self.process.state() != QProcess.NotRunning:
            self.process.kill()

    def _process_error(self, error) -> None:
        if error != QProcess.FailedToStart or self._terminal_emitted:
            return
        self._terminal_emitted = True
        self._cleanup_staging()
        self.failed.emit(
            "The conversion worker process could not be started.",
            self.process.errorString(),
        )

    def _read_stdout(self) -> None:
        self._stdout_buffer += bytes(self.process.readAllStandardOutput()).decode(
            "utf-8", "replace"
        )
        lines = self._stdout_buffer.split("\n")
        self._stdout_buffer = lines.pop()
        for line in lines:
            self._handle_line(line.strip())

    def _read_stderr(self) -> None:
        self._stderr += bytes(self.process.readAllStandardError()).decode(
            "utf-8", "replace"
        )

    def _handle_line(self, line: str) -> None:
        if not line:
            return
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            self._stderr += line + "\n"
            return
        event = payload.get("event")
        if event == "progress":
            self.progress.emit(
                int(payload.get("percent", 0)),
                str(payload.get("stage", "")),
            )
        elif event == "complete":
            self._result = dict(payload.get("result") or {})
        elif event == "error":
            self._error_message = str(payload.get("message", "Conversion failed."))

    def _finished(self, exit_code: int, _exit_status) -> None:
        if self._terminal_emitted:
            return
        self._terminal_emitted = True
        self._read_stdout()
        self._read_stderr()
        if self._stdout_buffer.strip():
            self._handle_line(self._stdout_buffer.strip())
        self._cleanup_staging()
        if self._cancel_requested:
            self.cancelled.emit()
        elif exit_code == 0 and self._result is not None:
            self.completed.emit(self._result)
        else:
            message = self._error_message or f"Conversion worker exited with code {exit_code}."
            self.failed.emit(message, self._stderr)

    def _cleanup_staging(self) -> None:
        if (
            self.staging_dir.exists()
            and self.staging_dir.name.startswith(".geofvbridge-")
        ):
            shutil.rmtree(self.staging_dir, ignore_errors=True)
