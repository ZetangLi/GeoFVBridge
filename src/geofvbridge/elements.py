"""Definitions for supported first-order Gmsh/meshio cell families."""

from __future__ import annotations

CELL_DIMENSION = {
    'voxel': 3,
    "triangle": 2,
    "quad": 2,
    "tetra": 3,
    "wedge": 3,
    "hexahedron": 3,
    "pyramid": 3,
}

EXPECTED_NODES = {
    'voxel': 8,
    "triangle": 3,
    "quad": 4,
    "tetra": 4,
    "wedge": 6,
    "hexahedron": 8,
    "pyramid": 5,
}

# Cyclic local face order. Normals are normalized later from cell geometry.
LOCAL_FACES = {
    # meshio/VTK voxel ordering differs from the hexahedron ordering.
    'voxel': (
        (0, 2, 3, 1),
        (4, 5, 7, 6),
        (0, 1, 5, 4),
        (1, 3, 7, 5),
        (3, 2, 6, 7),
        (2, 0, 4, 6),
    ),
    "triangle": ((0, 1), (1, 2), (2, 0)),
    "quad": ((0, 1), (1, 2), (2, 3), (3, 0)),
    "tetra": ((0, 2, 1), (0, 1, 3), (1, 2, 3), (2, 0, 3)),
    "wedge": (
        (0, 2, 1),
        (3, 4, 5),
        (0, 1, 4, 3),
        (1, 2, 5, 4),
        (2, 0, 3, 5),
    ),
    "hexahedron": (
        (0, 3, 2, 1),
        (4, 5, 6, 7),
        (0, 1, 5, 4),
        (1, 2, 6, 5),
        (2, 3, 7, 6),
        (3, 0, 4, 7),
    ),
    "pyramid": ((0, 3, 2, 1), (0, 1, 4), (1, 2, 4), (2, 3, 4), (3, 0, 4)),
}

LOWER_DIMENSION_TYPES = {
    0: {"vertex"},
    1: {"line"},
    2: {"triangle", "quad"},
}


def canonical_cycle(nodes: tuple[int, ...]) -> tuple[int, ...]:
    """Return a direction-independent deterministic cyclic representation."""
    if len(nodes) <= 2:
        return tuple(sorted(nodes))
    forward = [nodes[i:] + nodes[:i] for i in range(len(nodes))]
    reverse_nodes = tuple(reversed(nodes))
    backward = [reverse_nodes[i:] + reverse_nodes[:i] for i in range(len(nodes))]
    return min(forward + backward)
