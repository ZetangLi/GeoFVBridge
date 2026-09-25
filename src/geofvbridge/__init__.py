"""GeoFVBridge public API."""

from .api import (
    DatasetArtifacts,
    available_backends,
    convert_mesh,
    convert_source,
    default_fv_dataset_path,
    export_model,
    export_solver_mesh,
    inspect_mesh,
    inspect_source,
    load_fv_dataset,
    prepare_solver_model,
    read_results,
    save_fv_dataset,
    to_pyvista,
    validate_model,
)
from .extrusion import extrude_meshio
from .model import ConversionOptions, ExtrusionOptions, FVModel, ValidationReport
from .petrel import PetrelImportOptions, PetrelInputFiles, convert_petrel, inspect_petrel

__all__ = [
    "ConversionOptions",
    "DatasetArtifacts",
    "ExtrusionOptions",
    "FVModel",
    "PetrelImportOptions",
    "PetrelInputFiles",
    "ValidationReport",
    "available_backends",
    "convert_mesh",
    "convert_petrel",
    "convert_source",
    "default_fv_dataset_path",
    "export_model",
    "export_solver_mesh",
    "extrude_meshio",
    "inspect_mesh",
    "inspect_petrel",
    "inspect_source",
    "load_fv_dataset",
    "prepare_solver_model",
    "read_results",
    "save_fv_dataset",
    "to_pyvista",
    "validate_model",
]

__version__ = "1.1.2"
