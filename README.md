# GeoFVBridge

[![Tests](https://github.com/ZetangLi/GeoFVBridge/actions/workflows/tests.yml/badge.svg)](https://github.com/ZetangLi/GeoFVBridge/actions/workflows/tests.yml)
[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.21522917.svg)](https://doi.org/10.5281/zenodo.21522917)

GeoFVBridge converts **Gmsh meshes** and **Petrel-exported ECLIPSE grids** into
reusable, cell-centred finite-volume datasets, then prepares **TOUGH2/ECO2M**
input files. It includes a desktop GUI, command-line tools, and a Python API.

**Current release: [v1.1.2](https://github.com/ZetangLi/GeoFVBridge/releases/tag/v1.1.2).**
See the [English/Chinese release notes](docs/releases/v1.1.2.md) for the changes
since v1.0.1 and compatibility guidance.

## 1. Install and launch

Use **Python 3.12**. Run these commands in a terminal, such as Windows
PowerShell or an Anaconda Prompt with a Python 3.12 environment activated.

### Install the stable release

```powershell
python --version
python -m pip install --upgrade pip
python -m pip install "geofvbridge[visualization] @ https://github.com/ZetangLi/GeoFVBridge/archive/refs/tags/v1.1.2.zip"
```

The `visualization` extra installs PyVista and its Qt integration for the
desktop viewer. This method does not require Git or a manual source-code download.

### Launch the application

```powershell
python -m geofvbridge
```

This opens the desktop GUI. Use the **same Python environment** for installation
and launch. You can launch it from any working directory.

To check the installed version:

```powershell
python -m geofvbridge --version
```

### Install the latest main-branch code instead

To use the current development code rather than the fixed v1.1.2 snapshot:

```powershell
python -m pip install --upgrade "geofvbridge[visualization] @ https://github.com/ZetangLi/GeoFVBridge/archive/refs/heads/main.zip"
python -m geofvbridge
```

The `main` URL changes as development continues; the version-tag URL installs
the published snapshot. Other versions remain available under
[Releases](https://github.com/ZetangLi/GeoFVBridge/releases).

<details>
<summary>Optional: create a separate Python environment on Windows</summary>

If you do not already have a suitable environment, create one with the Windows
Python launcher, then use its Python executable directly:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install "geofvbridge[visualization] @ https://github.com/ZetangLi/GeoFVBridge/archive/refs/tags/v1.1.2.zip"
.\.venv\Scripts\python.exe -m geofvbridge
```

This assumes Python 3.12 and the `py` launcher are installed. These commands
do not require running a PowerShell activation script.

</details>

## 2. Use the desktop GUI

The sidebar guides you through seven stages:

| Stage | What to do | Output |
|---|---|---|
| 1. Import | Select and inspect a Gmsh mesh or Petrel ECLIPSE export. | Input information and mesh preview |
| 2. FV dataset | Convert and save the reusable finite-volume model. | `.geofv.h5`, `.summary.json`, `.vtu` |
| 3. Solver | Select TOUGH2/ECO2M and prepare the solver model. | Solver preparation settings |
| 4. MESH | Configure extrusion for 2-D input, inactive cells and heat-exchange areas; preview and export. | `MESH`, `cell_map.csv`, `mesh_manifest.json` |
| 5. Simulation input | Set materials, run parameters and sources. | `flow.inp` |
| 6. Initial conditions | Set pressure, temperature and other initial-state parameters. | `INCON` |
| 7. Results | Load existing TOUGH output and extract results. | Extracted result files |

You can reopen a saved `.geofv.h5` dataset without its original source mesh.
TOUGH2/ECO2M itself is **not included**: run the exported inputs with your solver,
then return to the results page to read `flow.out`.

## 3. Use the command line

The examples below use `python -m geofvbridge`, so they use the same interpreter
as the installation commands. Replace the example filenames with your files;
quote paths that contain spaces.

### Convert a Gmsh mesh

```powershell
python -m geofvbridge inspect "model.msh"
python -m geofvbridge convert "model.msh"
python -m geofvbridge validate "model.geofv.h5"
```

By default, conversion writes these files beside the input:

| File | Purpose |
|---|---|
| `model.geofv.h5` | Reusable FV topology, geometry and metadata |
| `model.summary.json` | Statistics and validation report |
| `model.vtu` | ParaView/PyVista visualization data |

### Convert a Petrel ECLIPSE export

Place the EGRID file and any matching INIT, property GRDECL, NNC GRDECL and
UNRST files together, then run:

```powershell
python -m geofvbridge inspect "reservoir.EGRID"
python -m geofvbridge convert "reservoir.EGRID"
python -m geofvbridge validate "reservoir.geofv.h5"
```

Native mode preserves active corner-point cells. To merge each continuous
active K run in an I/J column, choose the optional `vertical-runs` mode and a
different output name:

```powershell
python -m geofvbridge convert "reservoir.EGRID" --grid-mode vertical-runs --output "reservoir_coarse.geofv.h5"
```

Use `--initial-state first` to import the first available UNRST state. Run
`python -m geofvbridge convert --help` for coordinate and property options.
This route reads ECLIPSE exports, not proprietary Petrel project databases.

### Export TOUGH2/ECO2M input files

Prepare a backend JSON configuration, such as the
[synthetic example configuration](examples/synthetic/eco2m.json), and adapt
its settings and boundary names to your model:

```powershell
python -m geofvbridge export eco2m "model.geofv.h5" --config "eco2m.json" --output "tough_input"
```

This creates `MESH`, `flow.inp`, `INCON` and mapping/manifest files in
`tough_input`. For a native 2-D dataset, include solver-stage extrusion settings
in the backend JSON; for example:

```json
{
  "extrusion": {
    "axis": "y",
    "total_thickness": 0.019,
    "layers": 1
  }
}
```

Choose the axis and thickness for your model. The GUI exposes these settings
on the TOUGH MESH page.

### Command help

```powershell
python -m geofvbridge --help
python -m geofvbridge convert --help
python -m geofvbridge export --help
```

The installed `geofvbridge` command is an equivalent entry point when your
environment's scripts directory is on `PATH`.

## 4. Download the example datasets

Installing the Python package does not place the repository's example datasets
in your working directory. For complete public examples, install Git and Git
LFS, then clone the repository:

```powershell
git lfs install
git clone https://github.com/ZetangLi/GeoFVBridge.git
cd GeoFVBridge
git lfs pull
python -m geofvbridge inspect "examples/eg_3d004/1_msh/eg3d004.msh"
```

Git LFS is needed for the large bundled result files, not for launching the
application. See [examples](examples/README.md) for the 3-D geological model
and 2-D FluidFlower workflow, or [synthetic examples](examples/synthetic/README.md)
for a small generated mesh. Bundled simulation results are historical examples;
they were not recomputed for v1.1.2.

## 5. Supported scope and numerical conventions

- Gmsh 2.2 and 4.1 input is read through `meshio`.
- Supported first-order cells include triangles, quadrilaterals, tetrahedra,
  wedges, hexahedra, pyramids, voxels and conforming mixtures.
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
- Windows is covered by the automated GUI test workflow. Python 3.12 is the
  supported interpreter version.

See [the architecture guide](docs/architecture.md) for geometry conventions,
the HDF5 schema, validation rules, and backend behavior. See
[the repository layout](docs/file_reference.md) and [examples](examples/README.md)
for source-tree orientation and bundled inputs.

## 6. Development installation

From the root of a cloned repository, in a Python 3.12 environment:

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

## 7. Citation and license

Citation metadata is available in [`CITATION.cff`](CITATION.cff). The archived
GeoFVBridge 1.0.1 snapshot is available at
[doi:10.5281/zenodo.21522918](https://doi.org/10.5281/zenodo.21522918).
That DOI identifies 1.0.1, not this release; use the GitHub 1.1.2 release link
when referring specifically to the new version.
GeoFVBridge is released under the [MIT License](LICENSE).
