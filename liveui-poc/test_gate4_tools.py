import json
import sys
from pathlib import Path


POC_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(POC_ROOT))

from gate4_tools import (
    get_selected_component,
    prepare_workspace,
    set_selected_minimum_width,
)
from shadow import generate_shadow
from shadow_poc import inspect_shadow_process, validate_shadow_provenance


def _prepared(tmp_path: Path):
    state_path = prepare_workspace(tmp_path / "gate4")
    selected = get_selected_component(state_path)
    return state_path, selected


def test_gate4_selection_exposes_exact_required_context(tmp_path: Path):
    _, selected = _prepared(tmp_path)

    assert selected["ok"] is True
    assert selected["tool"] == "get_selected_component"
    assert selected["component"]["binding"] == "self.save"
    assert selected["component"]["qt_class"] == "QPushButton"
    assert selected["component"]["text"] == "Save"
    assert selected["component"]["minimum_width"] == 280
    assert selected["component"]["source_file"] == "main_window.py"
    assert selected["component"]["revision"] == 1
    assert selected["component"]["runtime_id"].startswith("w_")


def test_gate4_setter_commits_through_restart_and_reacquisition(tmp_path: Path):
    state_path, selected = _prepared(tmp_path)
    component = selected["component"]

    result = set_selected_minimum_width(
        state_path,
        runtime_id=component["runtime_id"],
        width=340,
        base_revision=component["revision"],
    )

    assert result["ok"] is True
    assert result["status"] == "COMMITTED"
    assert result["committed_revision"] == 2
    assert result["verification"]["binding"] == "self.save"
    assert result["verification"]["minimum_width"] == 340
    assert result["verification"]["cancel_width"] == 120
    assert result["verification"]["reacquired_runtime_id"] != component["runtime_id"]

    state = json.loads(state_path.read_text(encoding="utf-8"))
    build = generate_shadow(Path(state["project_root"]))
    resolved = validate_shadow_provenance(inspect_shadow_process(build.workspace))
    assert state["revision"] == 2
    assert state["selection"] is None
    assert resolved["save"]["minimum_width"] == 340
    assert resolved["cancel"]["minimum_width"] == 120


def test_gate4_setter_rejects_wrong_runtime_id_without_writing(tmp_path: Path):
    state_path, selected = _prepared(tmp_path)
    state = json.loads(state_path.read_text(encoding="utf-8"))
    canonical = Path(state["project_root"]) / "main_window.py"
    before = canonical.read_bytes()

    result = set_selected_minimum_width(
        state_path,
        runtime_id="w_wrong_widget",
        width=340,
        base_revision=selected["component"]["revision"],
    )

    assert result["ok"] is False
    assert result["status"] == "REJECTED_RUNTIME_ID"
    assert canonical.read_bytes() == before


def test_gate4_setter_rejects_stale_revision_without_writing(tmp_path: Path):
    state_path, selected = _prepared(tmp_path)
    state = json.loads(state_path.read_text(encoding="utf-8"))
    canonical = Path(state["project_root"]) / "main_window.py"
    before = canonical.read_bytes()

    result = set_selected_minimum_width(
        state_path,
        runtime_id=selected["component"]["runtime_id"],
        width=340,
        base_revision=0,
    )

    assert result["ok"] is False
    assert result["status"] == "REJECTED_STALE_REVISION"
    assert result["expected_revision"] == 1
    assert result["received_revision"] == 0
    assert canonical.read_bytes() == before
