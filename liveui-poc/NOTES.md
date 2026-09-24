# Rapid-spike notes

## Provenance method

The spike uses runtime constructor interception, not a shadow workspace.
`provenance.py` temporarily replaces only `PySide6.QtWidgets.QPushButton` and
`QLabel` with Python callables. Each callable constructs the original Shiboken
widget, captures its immediate Python caller with `sys._getframe(1)`, and
returns the real widget.

LibCST separately maps the captured constructor line to a simple assignment
target such as `self.save`, `self.cancel`, or `button`. Runtime instances receive
an epoch-qualified ID. The three loop instances therefore have different IDs
but share one static source anchor and the `button` binding.

## Why Strategy A was accepted for this spike

- It captures the exact demo callsite without modifying canonical source.
- It returns real Qt widgets and the demo's layout behavior remains intact.
- QPushButton and QLabel both pass subprocess tests.
- The target QApplication runs in a separate process, so its crash cannot crash
  the controller.

This is not yet a general interception design. Replacing a Qt class with a
callable can break code that subclasses the imported name, performs
`isinstance(..., QPushButton)`, or caches the class before interception. A
production design should prefer shadow instrumentation for those patterns.

## Deterministic mutation boundary

The transformer supports exactly one shape in exactly one lexical scope:

```python
<binding>.setMinimumWidth(<literal integer>)
```

It requires one unambiguous match. Missing, duplicated, dynamic, keyword, or
non-literal forms return `unsupported` with the original source unchanged.

## Process boundary

`poc.py` starts `provenance.py` as a subprocess and receives one JSON snapshot
over captured stdout. This is sufficient local IPC for the proof; there is no
service, socket framework, GUI, database, or persistent runtime process.

The target runner compiles canonical source bytes directly on every launch.
An early regression test caught Python reusing timestamp-and-size-valid `.pyc`
bytecode after the rapid same-length `120` to `280` edit. Direct compilation
removes that cache ambiguity from restart verification.

## Known limitations

- Only QPushButton and QLabel constructors are intercepted.
- Only simple direct/annotated assignments are resolved to bindings.
- Aliased constructors, factories, nested constructor expressions, and
  constructors split across helper modules are unsupported.
- Runtime state restoration is not attempted.
- The test deliberately does not uniquely edit one loop-created widget.
- Gate 4's constrained model interface passed with an authenticated Claude
  making exactly one selection call and one setter call. Gate 5 stale-revision
  and stale-file rejection pass.

## Follow-up shadow instrumentation proof

The follow-up proof generates a unique shadow workspace for every launch. A
LibCST pass wraps supported constructors with `_liveui_capture_widget(...)` and
simple assignment calls with `_liveui_bind_widget(...)`. The two identities are
kept separate:

- a helper-created Save and Cancel share the constructor anchor inside
  `widgets.py`;
- the outer assignments provide distinct `self.save` and `self.cancel` binding
  anchors in `main_window.py`;
- loop instances share a creation/binding anchor but retain unique runtime IDs.

Custom QWidget names are discovered through a small two-pass inheritance scan.
The proof captures both an `InspectorPanel` instance and a QLabel created inside
that class. Canonical files are never instrumented; only the requested width
edit is written to canonical source, and the evidence run restores it afterward.

This follow-up still uses name-based project-wide custom-class discovery. It
does not yet resolve aliased imports or same-named classes in different modules.
Each generated workspace is retained for inspection rather than cleaned up.

## Conservative adversarial behavior

Runtime records now distinguish creation-provenance confidence from assignment-
binding confidence. Unrecognized constructors that still appear in a supported
assignment are marked `binding_only`; captured constructors without a supported
assignment, such as items created in a comprehension, retain
`binding_status = unresolved`. Downstream editing must require both relevant
identities to be resolved.

## Revision gate

The revision controller checks the transaction's base revision before operation
dispatch. It also compares the exact canonical file hash with the hash recorded
for the current revision. A mismatch returns a structured rejection without
running LibCST or writing source. Successful width mutations reuse the existing
shadow generation, restart, binding reacquisition, and runtime verification
path before incrementing the revision.

## Claude tool boundary

`gate4_tools.py` exposes only `get_selected_component` and
`set_minimum_width`. A setter request must reproduce the currently selected
runtime ID and revision, and the source hash must still match the selection.
The implementation then delegates to `RevisionController`; it does not give the
model a second editing path.

`gate4_claude.py` launches the real Claude Code client with only the two tool
command patterns allow-listed, records stream-JSON evidence, and performs an
independent fresh-runtime read after the model finishes. The authenticated run
committed revision 2 and independently verified Save width `340` and Cancel
width `120` in a fresh process.
