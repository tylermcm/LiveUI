# LiveUI feasibility evidence

Measured on Windows with Python 3.9.13, PySide6 6.10.2, and LibCST
1.9.0.

## Current verdict

**Core Runtime/Source Round Trip: VALIDATED**

**Five-gate rapid-spike verdict: STRONG GO for the proposal.**

All scoped feasibility gates now pass. This validates the proposed core
control loop; it does not claim production completeness or erase the explicit
limitations below.

- Gate 1 — runtime provenance: PASS
- Gate 2 — deterministic LibCST mutation: PASS
- Gate 3 — restart, reacquisition, and runtime verification: PASS
- Gate 4 — Claude tool use: PASS
- Gate 5 — stale revision rejection: PASS

No implementation-duration claim is used as evidence. The evidence is the
behavior, assertions, refusal cases, and measured process boundaries below.

## Gates 1–3 — core round trip

The narrow proof maps the running Save button to `self.save`, changes only
`self.save.setMinimumWidth(120)` to `280`, starts a new runtime epoch,
reacquires the new runtime widget through `self.save`, and reads back
`minimumWidth() == 280`. Cancel remains `120`.

The original constructor-interception experiment passed, but it can affect
subclassing and `isinstance` checks. That is direct evidence for using shadow
instrumentation as the continuing architecture rather than constructor
replacement.

## Shadow instrumentation follow-up

Status: **PASS**

- Multi-file project: PASS
- Helper factory provenance: PASS
- Project-local custom QWidget provenance: PASS
- Loop runtime identity versus shared source identity: PASS
- Canonical source untouched by instrumentation: PASS
- Binding-specific canonical edit: PASS
- Fresh shadow regeneration, restart, reacquisition, and runtime verification:
  PASS

Save and Cancel share the constructor anchor at `widgets.py:5`, because the
same helper creates both, while their binding anchors distinguish `self.save`
from `self.cancel` in `main_window.py`. A custom `InspectorPanel` and the QLabel
inside it are both captured. Generated instrumentation exists only beneath
`multifile_demo/.liveui/runtime_workspace/<generation>/`.

Two implementation hazards were found and fixed:

1. Double-leading-underscore injected names are class-name-mangled inside
   methods, so generated runtime aliases use one leading underscore.
2. Recursive dataclass conversion attempts to copy non-pickleable Shiboken
   widgets, so snapshots serialize scalar metadata explicitly.

## Adversarial provenance audit

Status: **PASS — exact mapping or explicit unresolved state**

The hostile fixture covers:

- near collisions: `self.save`, `self.save_as`, and `self.cancel`;
- helper factories and a factory returning a custom `FancyButton` subclass;
- aliased and module-qualified constructors;
- annotated and conditional assignments;
- a dynamic factory variable;
- a list comprehension creating three buttons;
- runtime-import placement after a module docstring and `__future__` import.

Assertions verify exact text, binding, source file, source scope, creation
anchor, binding anchor, Qt class, and runtime identity—not merely that a result
exists. Aliased and dynamic constructors are currently reported as
`binding_only`; comprehension instances have resolved creation provenance but
explicitly unresolved assignment binding. They are never reported as fully
resolved.

## Gate 5 — stale revision rejection

Status: **PASS**

Evidence scenario:

1. Two agent transactions begin at revision 12: a width change and a text
   change.
2. A human width change commits through the existing shadow mutation/restart/
   verification path and creates revision 13.
3. Both revision-12 agent transactions return `REJECTED_STALE_REVISION` before
   operation dispatch.
4. Canonical source remains at width `280`.
5. A fresh shadow runtime reports width `280`.

A separate test modifies canonical source outside the controller without
changing the revision. The transaction returns `REJECTED_STALE_SOURCE_HASH`
and does not overwrite the external change.

This gate intentionally rejects all stale operations, even when the human and
agent touched different semantic properties. Automatic merge is not claimed.

## Gate 4 — Claude tool-use path

Status: **PASS**

The model-facing path is implemented without MCP. Claude Code is launched in
safe, non-persistent mode with only Bash enabled and only these two command
patterns allow-listed:

- `get_selected_component` returns the exact selected runtime ID, binding,
  Qt class, text, width, binding source, source scope, and revision.
- `set_minimum_width` requires that exact runtime ID and base revision, checks
  the canonical source hash, and delegates to `RevisionController`. A success
  therefore uses the same LibCST mutation, fresh shadow generation, process
  restart, binding reacquisition, and runtime verification as Gates 1–3 and 5.

Four local interface tests pass. They assert the complete selected context,
the `280 -> 340` verified commit, rejection of a wrong runtime ID, and
rejection of a stale revision without a source write.

An authenticated Claude Code 2.1.212 run using `claude-sonnet-5` produced two
direct model `tool_use` events:

```text
get_selected_component(runtime state)
  -> self.save, QPushButton, "Save", width 280, revision 1,
     runtime_id w_54e88f64_001

set_minimum_width(runtime_id w_54e88f64_001, width 340, base_revision 1)
  -> COMMITTED, revision 2, reacquired runtime_id w_7cc04fd2_001
```

The harness observed exactly one call to each allowed operation. After Claude's
setter returned, the controller independently generated another shadow and
started another target process. That fresh runtime reported Save `340` and
Cancel `120`. The committed revision was `2`, and the runtime ID changed across
restart. The complete stream-JSON audit is retained under
`.gate4_workspace/run_1789940919706903400_77204/claude_stream.jsonl`.

## Restart timing audit

The old ~40–80 ms values measured only target work after Python and PySide6 had
already been imported. They are not process-startup measurements and must not
be used as such.

The corrected controller measurement starts immediately before
`subprocess.Popen()` and stops when the flushed runtime READY snapshot reaches
the controller. Twenty fresh shadow generations and target processes produced:

| Interval | Median | p95 | Min–max |
| --- | ---: | ---: | ---: |
| Full shadow regeneration + process spawn to READY | 280.06 ms | 300.10 ms | 273.24–300.40 ms |
| Controller process spawn to READY | 236.71 ms | 247.47 ms | 230.19–249.59 ms |
| Shadow generation only | 30.27 ms | 43.45 ms | 25.45–47.82 ms |
| Target internal post-import work to snapshot | 59.25 ms | 65.39 ms | 56.36–65.41 ms |

The first observed full restart was 281.11 ms. It is not labeled a true cold
OS start because filesystem and DLL caches were not cleared.

## Resulting viability claim

The spike now demonstrates the complete scoped human/live-UI/source/AI loop:
exact-or-explicitly-partial runtime provenance, deterministic canonical
mutation, restart and binding reacquisition, an authenticated Claude making
constrained tool calls, and rejection of stale revisions/source hashes. This
earns a **Strong GO for the capstone proposal**, subject to the current
limitations rather than a claim that the production system is already solved.

## Current limitations

- Aliased constructor creation provenance is binding-only rather than fully
  resolved.
- Comprehension-created widgets do not resolve to an editable container binding.
- Custom-class discovery is project-wide and name-based; duplicate class names
  and import aliases are not yet fully resolved.
- Runtime application state is not restored across restart.
- Only one deterministic setter operation is implemented.
- Generated evidence workspaces are retained for inspection rather than
  garbage-collected.

See `PROVENANCE_RESULTS.md` for the strategy comparison and adversarial matrix,
and `NOTES.md` for implementation details and support boundaries.
