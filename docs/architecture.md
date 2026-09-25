# GeoFVBridge architecture and conventions

## Data flow

```text
Gmsh .msh -> inspect -> native-dimensional FVModel
                           |-> <stem>.geofv.h5
                           |-> <stem>.summary.json
                           |-> <stem>.vtu / PyVista
                           `-> solver selection
                                  `-> solver preparation (2-D extrusion only here)
                                         `-> MESH -> flow.inp -> INCON

.geofv.h5 ----------------------------^
```

`meshio` supplies coordinates, connectivity, and Gmsh tags. GeoFVBridge owns
all finite-volume geometry, topology, semantic mapping, validation, and solver
adaptation. The GUI and CLI call the same public Python API.

## Supported cells

Top-dimensional first-order triangles, quadrilaterals, tetrahedra, wedges
(prisms), hexahedra, pyramids, and voxels are accepted. Voxels are normalized
to the hexahedron node convention on import. Mixed meshes must be conforming:
two neighbouring cells share an entire face with identical node IDs.
High-order cells, hanging nodes, arbitrary polyhedra, and embedded
lower-dimensional fracture formulations are outside version 1.1.

## Geometry

Polygon faces use deterministic fan triangulation. Cell measures and true
centroids are accumulated from oriented tetrahedra between an interior
reference point and the triangulated boundary. A face normal is oriented from
its owner toward its neighbour, or outward for an exterior boundary.

For an internal face, GeoFVBridge stores

- face measure and centroid;
- the intersection of the adjacent-cell centroid line with the face plane;
- `d1` and `d2`, the Euclidean distances from the two centroids to that
  intersection along the centroid line;
- `normal_d1` and `normal_d2`, the centroid-to-plane normal projections,
  retained only as diagnostics;
- centre-to-centre distance and the owner-to-neighbour direction;
- signed gravity-direction displacement;
- `q = abs(dot(L_hat, n_hat))` in `[0, 1]`.

The TOUGH `CONNE` record uses the intersection distances `d1/d2`, not
`normal_d1/normal_d2`. A centroid line parallel to the shared-face plane, an
intersection outside the centroid segment, a degenerate face/cell, or a face
shared by more than two cells is a blocking validation error. Face
non-planarity and low `q` are reported as diagnostics/warnings.

TOUGH export selects `CONNE.ISOT` from the existing signed gravity cosine
(`BETAX`): angles from 45 through 135 degrees to gravity use `ISOT=1`;
the remaining angles use `ISOT=3`. `ExportConnection.isot` compares
`abs(BETAX)` with `sqrt(0.5)`, allowing `1e-12` cosine roundoff at the
inclusive horizontal endpoints. A zero projection, including that produced
by a zero gravity vector, selects 1. This rule assumes horizontal isotropy,
with `ROCKS.PER(1)` horizontal and `PER(3)` vertical; it is a two-class
approximation for inclined connections, not a non-orthogonality correction.
The signed BETAX, distances, area, labels and ROCKS ordering are unchanged.
The shared MESH writer applies the rule to both ordinary connections and
connections created by explicitly configured fixed-state boundaries.

## Physical groups

The default dimension-aware mapping is:

| Gmsh entity dimension | Default FV role |
|---|---|
| model dimension | material/control volume |
| model dimension - 1 | boundary face |
| lower dimensions | source candidate |

The reusable-dataset GUI applies this mapping automatically and does not ask
the user to edit roles. Coordinate sources use the nearest cell centroid. The
selected cell and distance are persisted so the choice remains auditable.

## Two-dimensional models

File conversion preserves a 2-D Gmsh mesh as a 2-D FV dataset. Its original
points and top-dimensional triangle/quad connectivity are stored unchanged;
FV edges, connections, geometric boundaries, and source candidates are added
without changing dimension.

When a three-dimensional solver backend is selected, `prepare_solver_model`
extrudes triangles to wedges and quadrilaterals to hexahedra using an explicit
direction, total thickness, and one or more positive layer thicknesses. H5 and
MSH sources first produce the same native FVModel and then use this single
preparation path. A native 3-D FVModel is copied without coordinate or
topology modification.

## Petrel/ECLIPSE route

The Petrel route reads an ECLIPSE simulator export directly rather than
creating an intermediate MSH. EGRID supplies COORD, ZCORN, ACTNUM, MAPAXES,
and logical dimensions. INIT supplies regular TRAN and simulator properties;
property GRDECL, NNC GRDECL, and the first UNRST state are optional.

Native mode creates one FV cell per active Petrel cell. Conforming positive
regular TRAN pairs share a complete face and receive both geometric and source
connection records. Zero TRAN faces remain split. Positive non-matching fault
faces and NNC remain authoritative source connections without invented TOUGH
area or distance geometry.

Vertical-runs mode merges each uninterrupted ACTNUM run in an I/J column.
Source membership is retained. PORV is summed, continuous properties are
volume weighted, initial state is PORV weighted, and external regular TRAN
and NNC are summed by coarse cell pair. The metadata records volume, PORV,
TRAN, and connectivity conservation diagnostics.

## HDF5 schema 1.2

The authoritative file contains `/nodes`, `/cells`, `/faces`, `/connections`,
`/boundaries`, and `/sources`. Ragged connectivity is encoded as a flat array
plus offsets. Root attributes carry schema version, dimension, conversion
options, source metadata, and validation results. Schema 1.1 includes face
planarity, centroid-line intersection coordinates, and separate normal
projection distances. The reader remains compatible with schema 1.0 and
reconstructs the newer connection diagnostics when possible. The adjacent
JSON file is a compact human-readable summary, not a duplicate data store.
Schema 1.2 adds columnar cell fields, Petrel global/active/IJK identity,
vertical-run membership, normalized source connections, and the link from a
source TRAN record to its matching geometric FV connection. The reader remains
compatible with schemas 1.0 and 1.1.

## Public API

- `inspect_mesh(path)`
- `convert_mesh(path, options=None, *, extrusion=None) -> FVModel`
- `default_fv_dataset_path(input_path) -> Path`
- `save_fv_dataset(model, path) -> DatasetArtifacts`
- `load_fv_dataset(path) -> FVModel`
- `prepare_solver_model(model_or_path, extrusion=None) -> FVModel`
- `export_solver_mesh(model_or_path, backend, config, output) -> ExportManifest`
- `export_model(model_or_h5, backend, config, output) -> ExportManifest`
- `to_pyvista(model, display_mode, *, inactive_cells=None, visible_materials=None)`

Version 1.1 also exposes inspect_source(path), convert_petrel(source, options),
and convert_source(source, ...) for automatic Gmsh/Petrel dispatch.

The GUI and CLI use these functions; there is no separate direct
Gmsh-to-`MESH` geometry path.

## ECO2M boundary mapping

The backend supports:

- `auto`: exterior no-flow faces need no connection; flux faces become GENER
  records weighted by interface measure; fixed-state faces receive mirrored,
  inactive external control volumes.
- prebuilt/infinite-volume selection by explicit cell IDs, material, centroid
  Z threshold, or exposed global-top faces.

Infinite-volume selection changes only exported solver cells; it never changes
the FV dataset. It replaces only the `ELEME` volume and always preserves the
geometric-intersection `CONNE d1/d2`, matching the retained GUI behavior and
the solver-independent FV geometry definition.

All generated five-character element labels use the deterministic TOUGH
`A3,I2` sequence (`A11 0`, `A11 1`, ..., `A1110`, ..., `A12 0`).
The same labels are used by ELEME, CONNE, GENER, INCON, result extraction,
`cell_map.csv`, and the export manifest. The manifest also records the final
inactive-cell list and selection reason.

## Desktop workflow

The seven GUI stages are original FE mesh import, native FV dataset creation
and saving, solver selection, TOUGH `MESH`, `flow.inp`, `INCON`, and
`flow.out` extraction. The solver page remains disabled until a valid HDF5
dataset has been saved. `flow.inp` and `INCON` remain disabled until `MESH`
has created a `SolverMeshContext` containing the prepared 3-D model, stable
labels, material map, output directory, and boundary configuration.
The right-hand view can display materials, quality, wireframe, FV connections,
boundary faces, source cells, and the current TOUGH inactive-cell preview.
Its lithology checklist filters only the rendered PyVista bundle. It keeps
material IDs and colors stable, shows a connection only when both adjacent
cells are visible, and filters boundary/source overlays by their owner cell.
The underlying FVModel and every saved or exported file remain unchanged.
