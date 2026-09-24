import shutil
import sys
from pathlib import Path


POC_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(POC_ROOT))

from shadow import generate_shadow
from shadow_poc import inspect_shadow_process


FIXTURE = POC_ROOT / "hostile_fixture"


def _snapshot(tmp_path: Path) -> tuple[dict, Path]:
    project = tmp_path / "hostile"
    shutil.copytree(FIXTURE, project, ignore=shutil.ignore_patterns(".liveui", "__pycache__"))
    build = generate_shadow(project)
    return inspect_shadow_process(build.workspace), build.workspace


def test_near_collision_bindings_never_resolve_to_the_wrong_widget(tmp_path: Path):
    snapshot, _ = _snapshot(tmp_path)
    by_text = {widget["text"]: widget for widget in snapshot["widgets"] if widget["text"]}
    expected = {
        "Save": "self.save",
        "Save As": "self.save_as",
        "Cancel": "self.cancel",
        "Fancy": "self.fancy",
        "Alias": "self.alias",
        "Qualified": "self.qualified",
        "Annotated": "self.annotated",
        "Conditional": "self.conditional",
        "Dynamic": "self.dynamic",
    }

    assert {text: by_text[text]["binding"] for text in expected} == expected
    assert len({by_text[text]["runtime_id"] for text in expected}) == len(expected)
    assert by_text["Save"]["binding_anchor"] != by_text["Save As"]["binding_anchor"]
    assert by_text["Save"]["runtime_id"] != by_text["Cancel"]["runtime_id"]


def test_helper_and_custom_subclass_have_exact_creation_provenance(tmp_path: Path):
    snapshot, _ = _snapshot(tmp_path)
    by_text = {widget["text"]: widget for widget in snapshot["widgets"] if widget["text"]}
    helper_widgets = [by_text[text] for text in ("Save", "Save As", "Cancel")]

    assert len({widget["source_anchor"] for widget in helper_widgets}) == 1
    assert all(widget["source_file"] == "helpers.py" for widget in helper_widgets)
    assert all(widget["source_scope"] == "make_button" for widget in helper_widgets)
    assert all(widget["provenance_status"] == "resolved" for widget in helper_widgets)

    fancy = by_text["Fancy"]
    assert fancy["qt_class"] == "FancyButton"
    assert fancy["binding"] == "self.fancy"
    assert fancy["source_file"] == "helpers.py"
    assert fancy["source_scope"] == "build_fancy_button"
    assert fancy["provenance_status"] == "resolved"


def test_alias_and_dynamic_factory_are_explicitly_binding_only(tmp_path: Path):
    snapshot, _ = _snapshot(tmp_path)
    by_text = {widget["text"]: widget for widget in snapshot["widgets"] if widget["text"]}

    for text, binding in (("Alias", "self.alias"), ("Dynamic", "self.dynamic")):
        widget = by_text[text]
        assert widget["binding"] == binding
        assert widget["binding_status"] == "resolved"
        assert widget["provenance_status"] == "binding_only"
        assert "not recognized" in widget["provenance_reason"]


def test_module_qualified_annotated_and_conditional_patterns_resolve(tmp_path: Path):
    snapshot, _ = _snapshot(tmp_path)
    by_text = {widget["text"]: widget for widget in snapshot["widgets"] if widget["text"]}

    for text in ("Qualified", "Annotated", "Conditional"):
        assert by_text[text]["provenance_status"] == "resolved"
        assert by_text[text]["binding_status"] == "resolved"
        assert by_text[text]["source_file"] == "main_window.py"


def test_comprehension_instances_are_unique_but_binding_is_explicitly_unresolved(
    tmp_path: Path,
):
    snapshot, _ = _snapshot(tmp_path)
    buttons = [widget for widget in snapshot["widgets"] if widget["text"] in {"One", "Two", "Three"}]

    assert len(buttons) == 3
    assert len({widget["runtime_id"] for widget in buttons}) == 3
    assert len({widget["source_anchor"] for widget in buttons}) == 1
    assert all(widget["provenance_status"] == "resolved" for widget in buttons)
    assert all(widget["binding"] is None for widget in buttons)
    assert all(widget["binding_status"] == "unresolved" for widget in buttons)


def test_runtime_import_is_after_docstring_and_future_import(tmp_path: Path):
    _, workspace = _snapshot(tmp_path)
    instrumented = (workspace / "main_window.py").read_text(encoding="utf-8")

    assert instrumented.index('"""Adversarial source patterns') < instrumented.index(
        "from __future__ import annotations"
    )
    assert instrumented.index("from __future__ import annotations") < instrumented.index(
        "from __liveui_runtime import"
    )
    compile(instrumented, str(workspace / "main_window.py"), "exec")

