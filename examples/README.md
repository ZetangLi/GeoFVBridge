# Examples

The example cases in this directory were created by the GeoFVBridge author and
are distributed under the repository's MIT license. They preserve successive
stages of the mesh-to-simulation workflow so that inputs and outputs can be
examined independently.

| Directory | Model |
|---|---|
| `eg_3d004` | Three-dimensional geological volume with fracture and boundary physical groups. |
| `eg_Ff006` | Two-dimensional FluidFlower cross-section with material physical groups. |

## Numbered stages

- `1_msh` contains the editable Gmsh geometry (`.geo`) and initial Gmsh mesh
  (`.msh`). Gmsh is not required to inspect the provided mesh.
- `2_turn` contains GeoFVBridge conversion and preparation artifacts, including
  HDF5, summary JSON, VTU, cell mapping, and export manifest files.
- `3_run` contains TOUGH-readable inputs and the corresponding run and extracted
  result files. The TOUGH solver executable is not included.
- `4_comparison` contains benchmark and simulation-data comparison outputs and
  is present only for `eg_Ff006`.

Raw `flow.out` and extracted `.dat` result files are stored with Git LFS. Run
`git lfs install` before cloning, or run `git lfs pull` in an existing clone to
download their full contents.

From the repository root, inspect either initial mesh with:

```powershell
geofvbridge inspect examples/eg_3d004/1_msh/eg3d004.msh
geofvbridge inspect examples/eg_Ff006/1_msh/Ff006.msh
```

To create a fresh native finite-volume dataset beside an initial mesh:

```powershell
geofvbridge convert examples/eg_3d004/1_msh/eg3d004.msh
```

To validate the provided converted dataset:

```powershell
geofvbridge validate examples/eg_3d004/2_turn/eg3d004.geofv.h5
```
