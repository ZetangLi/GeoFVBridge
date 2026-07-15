"""Geometry kernels for supported first-order finite-volume cells."""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

from .elements import LOCAL_FACES

FloatArray = NDArray[np.float64]


class GeometryError(ValueError):
    pass


def _unit(vector: FloatArray, tolerance: float) -> FloatArray:
    length = float(np.linalg.norm(vector))
    if length <= tolerance:
        raise GeometryError("Cannot normalize a zero-length vector.")
    return vector / length


def polygon_geometry(vertices: FloatArray, tolerance: float = 1.0e-12):
    """Area, area-weighted centroid and unit normal of a convex 3-D polygon."""
    if len(vertices) < 3:
        raise GeometryError("A polygon needs at least three vertices.")
    origin = vertices[0]
    area = 0.0
    centroid_sum = np.zeros(3, dtype=float)
    normal_sum = np.zeros(3, dtype=float)
    for index in range(1, len(vertices) - 1):
        a, b = vertices[index], vertices[index + 1]
        cross = np.cross(a - origin, b - origin)
        triangle_area = 0.5 * float(np.linalg.norm(cross))
        if triangle_area <= tolerance:
            continue
        area += triangle_area
        centroid_sum += triangle_area * (origin + a + b) / 3.0
        normal_sum += cross
    if area <= tolerance:
        raise GeometryError("Degenerate polygon with zero area.")
    return area, centroid_sum / area, _unit(normal_sum, tolerance)


def polygon_planarity(vertices: FloatArray, centroid: FloatArray, normal: FloatArray) -> float:
    """Return the largest vertex distance from a polygon's representative plane."""
    offsets = np.asarray(vertices, dtype=float) - np.asarray(centroid, dtype=float)
    return float(np.max(np.abs(offsets @ np.asarray(normal, dtype=float))))


def cell_geometry(
    points: FloatArray,
    cell_type: str,
    nodes: tuple[int, ...],
    tolerance: float = 1.0e-12,
):
    """Return measure, centroid and a reference normal for a supported cell."""
    vertices = points[np.asarray(nodes, dtype=int)]
    if cell_type in {"triangle", "quad"}:
        return polygon_geometry(vertices, tolerance)

    # The vertex mean is an interior reference only. The returned centroid is
    # the volume-weighted tetrahedral moment, not the vertex mean.
    reference = vertices.mean(axis=0)
    volume = 0.0
    moment = np.zeros(3, dtype=float)
    for local_face in LOCAL_FACES[cell_type]:
        face = vertices[np.asarray(local_face, dtype=int)]
        face_center = face.mean(axis=0)
        for index in range(1, len(face) - 1):
            a, b, c = face[0], face[index], face[index + 1]
            cross = np.cross(b - a, c - a)
            if np.dot(cross, face_center - reference) < 0.0:
                b, c = c, b
            signed = float(np.dot(a - reference, np.cross(b - reference, c - reference))) / 6.0
            tetra_volume = abs(signed)
            if tetra_volume <= tolerance:
                continue
            volume += tetra_volume
            moment += tetra_volume * (reference + a + b + c) / 4.0
    if volume <= tolerance:
        raise GeometryError("Degenerate cell with zero volume.")
    return volume, moment / volume, None


def face_geometry(
    points: FloatArray,
    nodes: tuple[int, ...],
    dimension: int,
    owner_centroid: FloatArray,
    cell_normal: FloatArray | None,
    tolerance: float = 1.0e-12,
):
    vertices = points[np.asarray(nodes, dtype=int)]
    if dimension == 2:
        edge = vertices[1] - vertices[0]
        measure = float(np.linalg.norm(edge))
        if measure <= tolerance:
            raise GeometryError("Degenerate edge with zero length.")
        centroid = vertices.mean(axis=0)
        if cell_normal is None:
            raise GeometryError("A 2-D cell normal is required for edge geometry.")
        normal = _unit(np.cross(edge, cell_normal), tolerance)
    else:
        measure, centroid, normal = polygon_geometry(vertices, tolerance)
    planarity = polygon_planarity(vertices, centroid, normal) if dimension == 3 else 0.0
    if np.dot(normal, centroid - owner_centroid) < 0.0:
        normal = -normal
    return measure, centroid, normal, planarity
