# Provenance strategy results

## Conclusion

LibCST shadow instrumentation is the supported direction for LiveUI.

Runtime constructor interception passed the original direct-constructor demo,
including loop identity and QLabel/QPushButton capture. It is not a sound
general product mechanism because temporarily replacing a Qt class name with a
Python callable can change subclassing behavior and make
`isinstance(widget, QPushButton)` invalid. Custom QWidget subclasses are a core
LiveUI use case, so this limitation is architectural rather than cosmetic.

Shadow instrumentation avoids that problem. Canonical imports and Qt classes
remain ordinary. Only generated source calls the runtime capture/binding
helpers, and the values returned to application code are the original Qt
objects.

## Validated shadow cases

- Direct constructors and simple assignments.
- Three loop-created widgets with unique runtime IDs and one static anchor.
- Multi-file helper factory: Save and Cancel share the factory constructor
  anchor while resolving to `self.save` and `self.cancel` separately.
- Project-local `InspectorPanel(QWidget)` and nested QLabel.
- Factory returning `FancyButton(QPushButton)`.
- Module-qualified `QtWidgets.QPushButton`.
- Annotated and conditional assignments.
- Near-collision bindings `self.save`, `self.save_as`, and `self.cancel`.
- Runtime import placement after a docstring and `__future__` imports.

## Explicitly partial or unsupported cases

| Pattern | Current result | Safety behavior |
| --- | --- | --- |
| `QPushButton as Btn` alias | Binding resolved; creation is `binding_only` | Never reported as exact constructor provenance |
| Dynamic `factory(...)` call | Binding resolved; creation is `binding_only` | Never reported as exact constructor provenance |
| List comprehension constructors | Creation anchor resolved; assignment binding unresolved | Not eligible for deterministic per-widget editing |
| Duplicate class names across modules | Unsupported by name-based custom-class discovery | Must be resolved before broad project support |

The governing invariant is:

> Return an exact answer or an explicit partial/unsupported result—never a
> confident wrong source identity.

## Test strength

The adversarial tests assert exact text-to-binding mappings, source files,
source scopes, shared and distinct anchors, Qt class names, runtime-ID
uniqueness, and confidence statuses. They would fail if Save resolved to Save
As or Cancel, if a helper instance acquired the wrong binding, if a custom
subclass were recorded as a base QPushButton, or if a partial pattern were
reported as fully resolved.

Two representative executable assertion blocks are reproduced here rather
than leaving the evidence only in a prose table:

```python
expected = {
    "Save": "self.save",
    "Save As": "self.save_as",
    "Cancel": "self.cancel",
}
assert {text: by_text[text]["binding"] for text in expected} == expected
assert by_text["Save"]["binding_anchor"] != by_text["Save As"]["binding_anchor"]
assert by_text["Save"]["runtime_id"] != by_text["Cancel"]["runtime_id"]
```

```python
assert fancy["qt_class"] == "FancyButton"
assert fancy["binding"] == "self.fancy"
assert fancy["source_file"] == "helpers.py"
assert fancy["source_scope"] == "make_fancy"
assert fancy["provenance_status"] == "resolved"
assert fancy["binding_status"] == "resolved"
```

The complete functions, including fixture setup and additional assertions, are
in `test_adversarial_provenance.py`.
