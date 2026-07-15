"""Small registry for solver adapters consuming :class:`FVModel`."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from ..model import FVModel


@dataclass(frozen=True, slots=True)
class BackendAdapter:
    identifier: str
    display_name: str
    aliases: tuple[str, ...]
    validate: Callable[[FVModel, Any], list[str]]
    export: Callable[[FVModel, Any, Any], Any]
    parse_results: Callable[[Any, FVModel], Any]
    export_mesh: Callable[[FVModel, Any, Any], Any] | None = None


_BACKENDS: dict[str, BackendAdapter] = {}


def register_backend(adapter: BackendAdapter) -> None:
    keys = {adapter.identifier.lower(), *(alias.lower() for alias in adapter.aliases)}
    for key in keys:
        existing = _BACKENDS.get(key)
        if existing is not None and existing is not adapter:
            raise ValueError(f'Backend alias {key!r} is already registered.')
        _BACKENDS[key] = adapter


def get_backend(identifier: str) -> BackendAdapter:
    try:
        return _BACKENDS[identifier.lower()]
    except KeyError as error:
        choices = ', '.join(item.identifier for item in list_backends())
        raise ValueError(f'Unknown export backend {identifier!r}; available: {choices}.') from error


def list_backends() -> list[BackendAdapter]:
    unique = {adapter.identifier: adapter for adapter in _BACKENDS.values()}
    return [unique[key] for key in sorted(unique)]
