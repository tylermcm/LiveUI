# LiveUI feasibility prototype

This repository is a deliberately narrow feasibility spike for LiveUI. The
current implementation covers the first two milestones:

1. an ordinary, deliberately varied PySide6 sample application; and
2. LibCST-based discovery and stable identity for supported UI source sites.

The prototype does **not** yet instrument or launch a shadow copy, map live Qt
objects to these anchors, edit source, or transact revisions. Those are later
milestones and are tracked honestly in [docs/feasibility.md](docs/feasibility.md).

## Setup

Python 3.9 or newer is supported.

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[test]"
```

## Run the demo

```powershell
.venv\Scripts\python examples\provenance_demo\main.py
```

The demo contains direct constructors, nested layouts, loop-created buttons,
a reused helper factory, a custom widget class, a grid layout, and a connected
signal. It contains no LiveUI imports or instrumentation.

On a conda installation whose Qt metadata points at the wrong plugin folder,
set the package-owned platform path before launching:

```powershell
$env:QT_QPA_PLATFORM_PLUGIN_PATH = .venv\Scripts\python -c "from pathlib import Path; import PySide6; print(Path(PySide6.__file__).parent / 'plugins' / 'platforms')"
.venv\Scripts\python examples\provenance_demo\main.py
```

## Run the tests

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
.venv\Scripts\python -m pytest
```

## Source-anchor model

`liveui.provenance.anchors.analyze_project()` performs a two-pass scan:

- pass one identifies project-local classes derived from supported QWidget
  classes;
- pass two discovers supported widget constructors, layout insertions, and
  signal connections.

An anchor ID is derived from the schema version, normalized relative path,
qualified lexical scope, site kind, called symbol, an AST-normalized syntax
hash, and the occurrence number among otherwise identical sites in that scope.
Absolute line and column numbers and the whole-file revision hash are metadata,
not identity. Therefore, inserting unrelated lines does not change the anchor
ID. Identical duplicated expressions in one scope remain an explicitly
documented ambiguity.

## Current validation

- 12 tests pass on Python 3.9 / PySide6 6.10.2 / LibCST 1.9.0.
- The native demo process creates and shows `MainWindow`, then exits cleanly.
- The analyzer finds 29 supported source sites in the demo: 13 widget
  constructors, 15 layout operations, and one signal connection.
