"""Narrow attribute view used by the retained INP and INCON Qt pages."""

from __future__ import annotations

import numpy as np

from ..backends.eco2m import labels_for_model
from ..model import FVModel


class LegacyMeshView:
    """Expose only centers, materials, and labels; no external mesh library object."""

    def __init__(self, model: FVModel, material_map: dict[str, str] | None = None):
        labels = labels_for_model(model)
        material_map = material_map or {}
        self.centers = np.vstack([cell.centroid for cell in model.cells])
        self.original_materials = np.asarray([cell.material for cell in model.cells], dtype=str)
        self.materials = np.asarray(
            [material_map.get(cell.material, cell.material) for cell in model.cells], dtype=str
        )
        self.labels = np.asarray([labels[cell.id] for cell in model.cells], dtype=str)
