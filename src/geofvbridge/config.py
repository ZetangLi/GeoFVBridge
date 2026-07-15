"""Persistent user configuration for GeoFVBridge."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any


def default_config_path() -> Path:
    """Return the per-user settings path without writing into the package."""
    override = os.environ.get("GEOFVBRIDGE_CONFIG_DIR")
    if override:
        return Path(override).expanduser() / "settings.json"

    appdata = os.environ.get("APPDATA")
    base = Path(appdata) if appdata else Path.home() / "AppData" / "Roaming"
    return base / "GeoFVBridge" / "settings.json"


class ConfigManager:
    """Load and atomically persist the small set of user preferences."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path is not None else default_config_path()
        self._data: dict[str, Any] = {"language": "en_US"}
        self.load()

    def load(self) -> None:
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                self._data.update(data)
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            print(f"Failed to load config: {exc}", file=sys.stderr)

    def save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(".tmp")
            temporary.write_text(
                json.dumps(self._data, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            temporary.replace(self.path)
        except OSError as exc:
            print(f"Failed to save config: {exc}", file=sys.stderr)

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self._data[key] = value
        self.save()


config = ConfigManager()
