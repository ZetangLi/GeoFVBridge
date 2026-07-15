"""Shared state produced by the solver-mesh stage."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..model import FVModel
from .mesh_view import SolverMeshView


@dataclass(slots=True)
class SolverMeshContext:
    """One prepared solver mesh shared by MESH, flow.inp, and INCON."""

    model: FVModel
    backend: str
    source_path: Path
    output_dir: Path
    config: dict[str, Any]
    manifest: dict[str, Any]
    material_map: dict[str, str]
    mesh_view: SolverMeshView

    @classmethod
    def from_export(
        cls,
        model: FVModel,
        backend: str,
        source_path: Path,
        output_dir: Path,
        config: dict[str, Any],
        manifest: dict[str, Any],
    ) -> "SolverMeshContext":
        material_map = {
            str(original): str(encoded)
            for original, encoded in manifest.get("materials", {}).items()
        }
        return cls(
            model=model,
            backend=backend,
            source_path=source_path,
            output_dir=output_dir,
            config=dict(config),
            manifest=dict(manifest),
            material_map=material_map,
            mesh_view=SolverMeshView(model, material_map=material_map),
        )
