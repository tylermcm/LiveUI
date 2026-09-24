# Feasibility evidence and limits

This is a live record of what the prototype has actually demonstrated. It is
intentionally more conservative than the eventual product vision.

## Works

### Milestone 1: ordinary sample project

- The sample starts as an ordinary PySide6 application with no LiveUI imports.
- It contains direct constructors, nested box layouts, loop-created buttons, a
  reused helper factory, a custom QWidget subclass, explicit grid coordinates,
  and a connected signal.
- Offscreen Qt tests instantiate the real window, distinguish all three loop
  objects, and exercise the save signal.

### Milestone 2: stable static source anchors

- LibCST locates supported widget constructor calls without changing source.
- A two-pass project scan recognizes project-local QWidget subclasses,
  including transitive subclasses by class name.
- Layout insertion calls and signal `connect` calls receive source sites so
  later milestones can attach graph and runtime data.
- Absolute source positions and the exact whole-file byte SHA-256 revision are
  recorded.
- Anchor identity ignores positions and the whole-file revision. It combines a
  normalized project-relative path, lexical scope, semantic site kind, called
  symbol, AST-normalized syntax hash, and occurrence among identical sites.
- Tests demonstrate that unrelated statements and formatting changes before a
  site do not change its anchor ID.

## Partially works

- Custom-widget recognition is intentionally name-based. It understands direct
  and transitive project-local inheritance, but does not yet perform Python
  import resolution or distinguish two classes with the same name in different
  modules.
- Helper-created widgets have a precise anchor at the constructor inside the
  helper. Mapping each runtime instance to that shared anchor belongs to the
  instrumentation milestone and is not yet proven.
- Layout calls are identified syntactically. The analyzer does not yet prove
  the receiver is a Qt layout object.
- Signal connection sites are retained, but signal semantics are not modeled.

## Does not work yet

- Shadow-workspace generation or runtime instrumentation.
- Cross-process target launching and IPC.
- Runtime widget IDs, epochs, hierarchy reporting, or click selection.
- Runtime-to-source resolution, including the primary loop-instance gate.
- Deterministic source transformations.
- Transactions, revisions, atomic writes, rollback, and stale-base detection.
- Runtime verification after an edit.
- Inspector UI, semantic context objects, or MCP.

## Dangerous / unsupported

- Calls through aliases or dynamic expressions such as `factory(widget_type)`
  are not treated as widget constructors.
- Identical constructor expressions repeated in the same lexical scope are
  distinguished by occurrence order. Inserting another identical expression
  before them can shift identity; this ambiguity must be surfaced rather than
  silently guessed around.
- Runtime monkey-patching has not been attempted and is not assumed safe.

## Requires AI fallback

- Nothing is delegated to AI in Milestones 1–2. Future source edits outside a
  narrow, provably deterministic transformation set must be refused by the
  deterministic engine and may then be proposed for an explicit AI workflow.

## Milestone decision

Milestones 1 and 2 establish a plausible static identity scheme, but they do
not yet answer the primary feasibility question. The capstone recommendation
must wait until shadow instrumentation maps real loop- and helper-created Qt
objects back to these anchors across a process boundary.

## Validation evidence

- `python -m pytest -q -p pytestqt.plugin`: 12 passed.
- `python -m compileall -q src examples tests`: passed.
- Native Windows launch: `MainWindow` shown, loop labels reported as
  `One,Two,Three`, clean exit code 0.
- Static demo scan: 4 Python files, 29 supported source sites (13 widget
  constructors, 15 layout operations, one signal connection).
- A styled offscreen capture was visually inspected after explicitly providing
  the host conda environment's Qt platform and font directories. This is useful
  smoke evidence, not native-platform rendering certification.
