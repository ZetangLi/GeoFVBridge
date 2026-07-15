"""Optional solver adapters built on the GeoFVBridge intermediate model."""

from .eco2m import export_eco2m, export_eco2m_mesh, read_flow_output, validate_eco2m
from .registry import BackendAdapter, get_backend, list_backends, register_backend

register_backend(
    BackendAdapter(
        identifier='tough2-eco2m',
        display_name='TOUGH2 / ECO2M',
        aliases=('tough', 'tough2', 'eco2m'),
        validate=validate_eco2m,
        export=export_eco2m,
        parse_results=read_flow_output,
        export_mesh=export_eco2m_mesh,
    )
)

__all__ = [
    'BackendAdapter',
    'export_eco2m',
    'export_eco2m_mesh',
    'get_backend',
    'list_backends',
    'read_flow_output',
    'register_backend',
    'validate_eco2m',
]
