import shutil
import sys
from pathlib import Path


POC_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(POC_ROOT))

from shadow import generate_shadow
from shadow_poc import (
    inspect_shadow_process,
    run_shadow_round_trip,
    validate_shadow_provenance,
)


DEMO_ROOT = POC_ROOT / "multifile_demo"


def _copy_demo(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    shutil.copytree(DEMO_ROOT, project, ignore=shutil.ignore_patterns(".liveui", "__pycache__"))
    return project


def test_shadow_generation_never_changes_canonical_source(tmp_path: Path):
    project = _copy_demo(tmp_path)
    canonical = {path.relative_to(project): path.read_bytes() for path in project.rglob("*.py")}

    build = generate_shadow(project)

    assert canonical == {
        path.relative_to(project): path.read_bytes()
        for path in project.rglob("*.py")
        if ".liveui" not in path.parts
    }
    assert set(build.instrumented_files) == {"main.py", "main_window.py", "widgets.py"}
    instrumented = (build.workspace / "main_window.py").read_text(encoding="utf-8")
    assert "_liveui_capture_widget" in instrumented
    assert "_liveui_bind_widget" in instrumented
    assert "__liveui" not in (project / "main_window.py").read_text(encoding="utf-8")
    for source_file in build.workspace.glob("*.py"):
        compile(source_file.read_bytes(), str(source_file), "exec")


def test_shadow_provenance_handles_helpers_loops_and_custom_widgets(tmp_path: Path):
    project = _copy_demo(tmp_path)
    build = generate_shadow(project)
    snapshot = inspect_shadow_process(build.workspace)

    resolved = validate_shadow_provenance(snapshot)

    assert resolved["save"]["source_anchor"] == resolved["cancel"]["source_anchor"]
    assert resolved["save"]["binding"] == "self.save"
    assert resolved["cancel"]["binding"] == "self.cancel"
    assert len({widget["runtime_id"] for widget in resolved["loop"]}) == 3
    assert resolved["inspector"]["qt_class"] == "InspectorPanel"
    assert resolved["heading"]["qt_class"] == "QLabel"
    assert snapshot["process_ready_ms"] > snapshot["in_process_ready_ms"]


def test_shadow_round_trip_restarts_and_reacquires_binding(tmp_path: Path):
    project = _copy_demo(tmp_path)

    report = run_shadow_round_trip(project, width=280, emit=False)
    source = (project / "main_window.py").read_text(encoding="utf-8")

    assert report["status"] == "PASS"
    assert report["method"] == "LibCST shadow instrumentation"
    assert report["before_epoch"] != report["after_epoch"]
    assert report["before_runtime_id"] != report["after_runtime_id"]
    assert report["new_width"] == 280
    assert report["cancel_width"] == 120
    assert "self.save.setMinimumWidth(280)" in source
    assert "self.cancel.setMinimumWidth(120)" in source
