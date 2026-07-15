"""Runtime translation service for GeoFVBridge."""

from __future__ import annotations

import warnings
from typing import Any

from .config import config
from .locales.en_US import STRINGS as EN_US
from .locales.zh_CN import STRINGS as ZH_CN

DEFAULT_LANGUAGE = "en_US"
SUPPORTED_LANGUAGES = ("en_US", "zh_CN")
TRANSLATIONS: dict[str, dict[str, str]] = {
    "en_US": EN_US,
    "zh_CN": ZH_CN,
}

_configured_language = config.get("language", DEFAULT_LANGUAGE)
_current_language = (
    _configured_language if _configured_language in SUPPORTED_LANGUAGES else DEFAULT_LANGUAGE
)


def set_language(language: str) -> None:
    """Persist a supported language for use after the application restarts."""
    global _current_language
    if language not in SUPPORTED_LANGUAGES:
        warnings.warn(f"Unsupported language: {language}", RuntimeWarning, stacklevel=2)
        return
    _current_language = language
    config.set("language", language)


def get_language() -> str:
    """Return the currently selected language code."""
    return _current_language


def tr(key: str, **kwargs: Any) -> str:
    """Resolve a semantic translation ID and optionally format named fields."""
    selected = TRANSLATIONS.get(_current_language, EN_US)
    template = selected.get(key)
    if template is None:
        template = EN_US.get(key)
        if template is not None:
            warnings.warn(
                f"Missing {_current_language} translation for {key}",
                RuntimeWarning,
                stacklevel=2,
            )
    if template is None:
        warnings.warn(f"Unknown translation ID: {key}", RuntimeWarning, stacklevel=2)
        return key
    if not kwargs:
        return template
    try:
        return template.format(**kwargs)
    except (KeyError, ValueError, IndexError) as exc:
        warnings.warn(
            f"Could not format translation {key}: {exc}",
            RuntimeWarning,
            stacklevel=2,
        )
        return template
