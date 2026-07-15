import os
import tempfile
import unittest
from collections import defaultdict
from pathlib import Path

import numpy as np

from geofvbridge.api import convert_mesh, export_model, inspect_mesh, prepare_solver_model
from geofvbridge.model import ExtrusionOptions

_EXTERNAL_EXAMPLE_ROOT = os.environ.get("GEOFVBRIDGE_REGRESSION_ROOT")
EXAMPLE_ROOT = Path(_EXTERNAL_EXAMPLE_ROOT).expanduser() if _EXTERNAL_EXAMPLE_ROOT else None


def _parse_mesh(path):
    elements = []
    connections = {}
    labels = {}
    mode = None
    for line in Path(path).read_text(encoding='latin-1').splitlines():
        if line.startswith('ELEME'):
            mode = 'elements'
            continue
        if line.startswith('CONNE'):
            mode = 'connections'
            continue
        if not line.strip():
            continue
        if mode == 'elements' and len(line) >= 70:
            label = line[:5].strip()
            labels[label] = len(elements)
            elements.append(
                (
                    line[15:20].strip().upper(),
                    float(line[20:30]),
                    np.array([float(line[50:60]), float(line[60:70]), float(line[70:80])]),
                )
            )
        elif mode == 'connections' and len(line) >= 70:
            label1, label2 = line[:5].strip(), line[5:10].strip()
            if label1 not in labels or label2 not in labels:
                continue
            first, second = labels[label1], labels[label2]
            d1, d2 = float(line[30:40]), float(line[40:50])
            area, gravity = float(line[50:60]), float(line[60:70])
            if first > second:
                first, second, d1, d2, gravity = second, first, d2, d1, -gravity
            connections[(first, second)] = np.array([d1, d2, area, gravity])
    return elements, connections


def _element_labels(path):
    labels = []
    in_elements = False
    for line in Path(path).read_text(encoding="latin-1").splitlines():
        if line.startswith("ELEME"):
            in_elements = True
            continue
        if line.startswith("CONNE"):
            break
        if in_elements and line.strip():
            labels.append(line[:5])
    return labels


def _match_cells(reference_elements, generated_elements):
    coordinates = np.array([item[2] for item in reference_elements + generated_elements])
    scales = np.maximum(np.max(np.abs(coordinates), axis=0) * 1.0e-5, 1.0e-7)
    reference_buckets = defaultdict(list)
    for reference_id, (material, _, center) in enumerate(reference_elements):
        key = tuple(np.floor(center / scales).astype(int))
        reference_buckets[(material, key)].append(reference_id)

    generated_to_reference = {}
    for generated_id, (material, _, center) in enumerate(generated_elements):
        key = np.floor(center / scales).astype(int)
        candidates = []
        for x_offset in (-1, 0, 1):
            for y_offset in (-1, 0, 1):
                for z_offset in (-1, 0, 1):
                    neighbor = tuple(key + np.array([x_offset, y_offset, z_offset]))
                    for reference_id in reference_buckets.get((material, neighbor), ()):
                        delta = np.abs(center - reference_elements[reference_id][2])
                        if np.all(delta <= scales):
                            candidates.append(
                                (float(np.linalg.norm(delta / scales)), reference_id)
                            )
        if not candidates:
            raise AssertionError(
                f"could not match cell {generated_id}: {material} {center}"
            )
        generated_to_reference[generated_id] = min(candidates)[1]

    if len(set(generated_to_reference.values())) != len(generated_elements):
        raise AssertionError("nearest-centroid matching is not one-to-one")
    return generated_to_reference


def _remap_connections(connections, cell_map):
    remapped = {}
    for (cell1, cell2), values in connections.items():
        first, second = cell_map[cell1], cell_map[cell2]
        d1, d2, area, gravity = values
        if first > second:
            first, second, d1, d2, gravity = second, first, d2, d1, -gravity
        remapped[(first, second)] = np.array([d1, d2, area, gravity])
    return remapped


@unittest.skipUnless(
    EXAMPLE_ROOT is not None and EXAMPLE_ROOT.is_dir(),
    "set GEOFVBRIDGE_REGRESSION_ROOT to run the external reference regressions",
)
class ReferenceRegressionTests(unittest.TestCase):
    CASES = ('eg3d003', 'Ff006_run_incon', 'Otway001', 'Pruess002')
    EXTRUSION_THICKNESS = {
        'Ff006_run_incon': 0.019,
        'Otway001': 0.019,
        'Pruess002': 5.0,
    }
    INACTIVE_TOP_CASES = {'Pruess002'}

    def test_default_generated_mesh_geometry(self):
        for name in self.CASES:
            with self.subTest(case=name), tempfile.TemporaryDirectory() as directory:
                case = EXAMPLE_ROOT / name
                source = next(case.glob('*.msh'))
                extrusion = None
                if inspect_mesh(source)['dimension'] == 2:
                    extrusion = ExtrusionOptions(
                        (0.0, 1.0, 0.0),
                        (self.EXTRUSION_THICKNESS[name],),
                    )
                native = convert_mesh(source)
                model = prepare_solver_model(native, extrusion)
                backend_config = {'ahtx': {'mode': 'extrusion', 'heat_axis': 1}}
                if name in self.INACTIVE_TOP_CASES:
                    backend_config['inactive_top'] = True
                manifest = export_model(
                    model,
                    'tough2-eco2m',
                    backend_config,
                    directory,
                )
                reference_elements, reference_connections = _parse_mesh(case / 'MESH')
                new_elements, new_connections = _parse_mesh(manifest['files']['mesh'])
                self.assertEqual(
                    _element_labels(manifest['files']['mesh']),
                    _element_labels(case / 'MESH'),
                    "TOUGH cell labels differ from the reference A3,I2 sequence",
                )
                reference_inactive = {
                    cell_id
                    for cell_id, element in enumerate(reference_elements)
                    if element[1] >= 1.0e40
                }
                self.assertEqual(len(new_elements), len(reference_elements))
                self.assertEqual(len(new_connections), len(reference_connections))
                generated_to_reference = _match_cells(reference_elements, new_elements)
                new_connections = _remap_connections(
                    new_connections, generated_to_reference
                )
                missing = set(reference_connections) - set(new_connections)
                added = set(new_connections) - set(reference_connections)
                self.assertEqual(
                    (len(missing), len(added)),
                    (0, 0),
                    f"connection topology differs: missing={len(missing)}, added={len(added)}, "
                    f"examples={list(missing)[:5]} / {list(added)[:5]}",
                )
                for new_id, new in enumerate(new_elements):
                    reference_id = generated_to_reference[new_id]
                    reference = reference_elements[reference_id]
                    self.assertEqual(new[0], reference[0])
                    if reference_id not in reference_inactive:
                        self.assertTrue(
                            np.isclose(new[1], reference[1], rtol=5.0e-4, atol=1.0e-10),
                            f"cell {new_id} ({new[0]}) volume: "
                            f"new={new[1]}, reference={reference[1]}",
                        )
                    np.testing.assert_allclose(
                        new[2], reference[2], rtol=5.0e-4, atol=1.0e-6
                    )
                for key, reference in reference_connections.items():
                    if reference_inactive.intersection(key):
                        continue
                    np.testing.assert_allclose(
                        new_connections[key], reference, rtol=1.0e-3, atol=1.0e-8
                    )
