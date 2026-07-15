# Examples

The example inputs in this directory were created by the GeoFVBridge author
and are distributed under the repository's MIT license. Each case includes an
editable Gmsh geometry file (`.geo`) and a ready-to-read ASCII Gmsh mesh
(`.msh`), so Gmsh is not required for a quick software check.

| Directory | Model |
|---|---|
| `eg_3d004` | Three-dimensional geological volume with fracture and boundary physical groups. |
| `eg_Ff006` | Two-dimensional geological cross-section with material physical groups. |

From the repository root, inspect either mesh with:

```powershell
geofvbridge inspect examples/eg_3d004/eg3d004.msh
geofvbridge inspect examples/eg_Ff006/Ff006.msh
```

To create a native finite-volume dataset beside an input mesh:

```powershell
geofvbridge convert examples/eg_3d004/eg3d004.msh
```

Generated HDF5, JSON, and VTU artifacts are intentionally ignored by Git.
