# GeoFVBridge repository layout

This document describes the stable directory-level organization of the
repository. Generated datasets, solver files, caches, and build products are
not source files and are excluded through `.gitignore`.

## Root files

| Path | Purpose |
|---|---|
| `README.md` | Installation, first use, supported scope, and development checks. |
| `pyproject.toml` | Package metadata, dependencies, entry point, and tool configuration. |
| `LICENSE` | MIT software license. |
| `CITATION.cff` | Machine-readable software citation metadata. |
| `CHANGELOG.md` | User-visible release history. |
| `.github/workflows/tests.yml` | Windows lint, test, and package-build workflow. |

## Source package

All importable code lives under `src/geofvbridge`.

| Area | Responsibility |
|---|---|
| Top-level modules | Public API, CLI, model types, conversion, geometry, persistence, validation, visualization, configuration, and localization. |
| `backends/` | Solver-backend registry and the TOUGH2/ECO2M adapter. |
| `core/` | TOUGH input, initial-condition, and result-file helpers used by the desktop workflow. |
| `gui/` | PySide6 application shell, shared state, reports, visualization, and staged pages. |
| `locales/` | English and Simplified Chinese interface strings. |

The GUI and CLI call the same public API. Solver-specific behavior remains in
the backend, solver-preparation, or TOUGH workflow layers.

## Tests and examples

- `tests/` contains geometry, topology, persistence, backend, CLI, GUI,
  visualization, report, TOUGH-page, workflow, and example tests.
- `examples/eg_3d004/` contains an authored three-dimensional case, conversion
  artifacts, TOUGH inputs, and result data.
- `examples/eg_Ff006/` contains an authored two-dimensional FluidFlower case,
  conversion artifacts, TOUGH inputs, result data, and comparison figures.
- `examples/README.md` documents the numbered workflow stages, provenance, Git
  LFS usage, and quick inspection commands.

The public mesh examples are exercised by the normal test suite. Historical
external regression data is optional and is selected with the
`GEOFVBRIDGE_REGRESSION_ROOT` environment variable.

## Generated files

GeoFVBridge can create `.geofv.h5`, summary JSON, VTU, `MESH`, `flow.inp`,
`INCON`, mapping files, manifests, extracted results, and local runtime state.
These outputs are ignored by default. The curated datasets under `examples/`
are explicit exceptions; large raw result files there are stored with Git LFS.
Python, pytest, Ruff, coverage, and packaging caches must not be committed.
