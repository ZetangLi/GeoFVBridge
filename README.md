# GeoFVBridge

[![Tests](https://github.com/ZetangLi/GeoFVBridge/actions/workflows/tests.yml/badge.svg)](https://github.com/ZetangLi/GeoFVBridge/actions/workflows/tests.yml)
[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.21522917.svg)](https://doi.org/10.5281/zenodo.21522917)

GeoFVBridge is a solver-independent preprocessing toolkit that converts
conforming Gmsh meshes or Petrel-exported ECLIPSE corner-point grids into
cell-centred finite-volume topology and geometry.
It provides a Python API, command-line interface, staged desktop GUI, a
versioned HDF5 interchange format, and a TOUGH2/ECO2M export backend.

The conversion core computes cells, faces, connections, boundaries, sources,
geometric measures and centroids, face normals, centroid-line intersection
distances, gravity projections, and non-orthogonality diagnostics. Supported
first-order cells include triangles, quadrilaterals, tetrahedra, wedges,
hexahedra, pyramids, voxels, and conforming mixtures of those families.

**Current release: 1.1.2.** See the [cumulative release notes](docs/releases/v1.1.2.md)
for the changes since 1.0.1, migration guidance, and a Chinese comparison.

## Requirements

- Python 3.12
- Git LFS for downloading the complete bundled result datasets
- Windows is covered by the automated GUI test workflow
- TOUGH2/ECO2M is not included; GeoFVBridge only prepares and reads its files

## Installation

```powershell
git lfs install
git clone https://github.com/ZetangLi/GeoFVBridge.git
cd GeoFVBridge
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[visualization]"
```

The `visualization` extra installs PyVista and its Qt integration. The core API
can be installed without it, but the complete desktop visualization workflow
uses this extra.

## Quick start

```powershell
geofvbridge inspect examples/eg_3d004/1_msh/eg3d004.msh
geofvbridge convert examples/eg_3d004/1_msh/eg3d004.msh
geofvbridge validate examples/eg_3d004/2_turn/eg3d004.geofv.h5
geofvbridge gui
```

For a Petrel ECLIPSE export, use an EGRID file with optional matching INIT,
property GRDECL, grid NNC GRDECL, and UNRST files:

```powershell
geofvbridge inspect reservoir.EGRID
geofvbridge convert reservoir.EGRID
geofvbridge convert reservoir.EGRID --grid-mode vertical-runs
```

Native mode preserves active corner-point cells. `vertical-runs` merges each
continuous active K run in an I/J column, retains source membership, and
records volume, pore-volume, and source-connection conservation diagnostics.
This reads simulator exports; it does not open proprietary Petrel projects.

Running `geofvbridge` or `python -m geofvbridge` without arguments also opens
the GUI. Each conversion writes three reusable artifacts beside the input:

- `<input-stem>.geofv.h5`: authoritative FV topology and geometry;
- `<input-stem>.summary.json`: statistics and validation report;
- `<input-stem>.vtu`: ParaView/PyVista visualization data.

The HDF5 file can be loaded later and exported without the original Gmsh file.
For a complete CLI/API export from a native two-dimensional dataset, provide
solver-stage extrusion settings in the backend JSON:

```json
{
  "extrusion": {
    "axis": "y",
    "total_thickness": 0.019,
    "layers": 1
  }
}
```

The GUI exposes the same settings on the TOUGH MESH page.

## Supported scope

- Gmsh 2.2 and 4.1 input is read through `meshio`.
- File conversion preserves a two-dimensional mesh as a native 2-D FV model.
- Solver preparation can extrude triangles to wedges and quads to hexahedra.
- High-order, arbitrary-polyhedral, hanging-node, and non-conforming meshes are
  rejected with diagnostics rather than silently modified.
- HDF5 schema 1.2 stores Petrel fields, cell identities, and source connections;
  the reader also accepts schema 1.0 and 1.1 datasets.
- Positive Petrel TRAN/NNC connections without a complete FV interface block
  TOUGH export by default. The advanced
  `allow_unrepresented_source_connections` option explicitly permits an
  approximate export that omits them and records the omission in the manifest.
- TOUGH `CONNE.ISOT` is selected from the connection angle to gravity:
  45–135 degrees inclusive uses 1 (horizontal); other angles use 3 (vertical).
  Configure `ROCKS.PER(1)` and `PER(3)` accordingly. This assumes horizontal
  isotropy and does not correct non-orthogonal flux discretization.
- Large GUI conversions run in a cancellable process with progress reporting.
  Solver preparation, boundary previews, and MESH exports use background workers.

See [the architecture guide](docs/architecture.md) for geometry conventions,
the HDF5 schema, validation rules, and backend behavior. See
[the repository layout](docs/file_reference.md) and [examples](examples/README.md)
for source-tree orientation and bundled inputs.

## Development

```powershell
python -m pip install -e ".[dev,visualization]"
python -m ruff check .
python -m pytest -q
python -m build
```

The bundled public examples are included in the normal test suite. An optional
private-data regression suite can be enabled by setting
`GEOFVBRIDGE_REGRESSION_ROOT` to the directory containing the four historical
reference cases.

## Citation and license

Citation metadata is available in [`CITATION.cff`](CITATION.cff). The archived
GeoFVBridge 1.0.1 snapshot is available at
[doi:10.5281/zenodo.21522918](https://doi.org/10.5281/zenodo.21522918).
That DOI identifies 1.0.1, not this release; use the GitHub 1.1.2 release link
when referring specifically to the new version.
GeoFVBridge is released under the [MIT License](LICENSE).
