# Changelog

## 1.1.2 - 2026-09-25

This release collects the changes developed after the public 1.0.1 release;
1.1.0 and 1.1.1 were not separate GitHub releases. See the
[English/Chinese comparison and migration notes](docs/releases/v1.1.2.md).

- Added Petrel/ECLIPSE EGRID import, optional INIT/GRDECL/UNRST data, MAPAXES,
  active-cell identity, and auditable regular TRAN/NNC source connections.
- Added optional vertical-run coarsening with source membership and conservation
  diagnostics for volume, pore volume, and external source connections.
- Added HDF5 schema 1.2 while retaining readers for schemas 1.0 and 1.1.
- Added automatic Gmsh/Petrel API and CLI dispatch and GUI import options.
- Moved GUI conversion to a cancellable process with progress events and staged
  output; moved solver preparation, boundary preview, and export off the GUI thread.
- Reworked inactive-cell selection with five mutually exclusive selection methods,
  reusable indexing, explicit previews, and protection against stale worker results.
- Reused visualization geometry for boundary previews and retained material filters.
- Aggregated non-planar-face diagnostics and deduplicated validation issues.
- Blocked TOUGH export when positive source connections lack geometric interfaces,
  unless an explicit approximation override records their omission.
- Replaced constant CONNE ISOT=1 with gravity-based horizontal ISOT=1 / vertical
  ISOT=3 classification, including the inclusive 45/135-degree thresholds.
- Updated public documentation, release metadata, synthetic examples, and tests.
  Existing public simulation results are retained as historical examples.

## 1.0.1 - 2026-07-24

- Added complete public two-dimensional and three-dimensional example workflows,
  including authored Gmsh inputs, GeoFVBridge outputs, TOUGH inputs and results,
  and FluidFlower comparison artifacts.
- Stored large raw result files with Git LFS and treated TOUGH `MESH` files as
  binary so their exact bytes are preserved across platforms.
- Updated GitHub Actions to Node.js 24-compatible component releases.

## 1.0.0 - 2026-07-13

- Added solver-independent Gmsh-to-finite-volume conversion.
- Added a versioned HDF5 dataset with JSON and VTU companion artifacts.
- Added Python, command-line, and staged desktop GUI workflows.
- Added two-dimensional solver-stage extrusion and TOUGH2/ECO2M export.
- Added geometry, topology, persistence, backend, GUI, and example regression tests.
