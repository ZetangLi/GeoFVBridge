# Changelog

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
