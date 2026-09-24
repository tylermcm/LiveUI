import shutil
import sys
from pathlib import Path


POC_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(POC_ROOT))

from revisions import RevisionController
from shadow import generate_shadow
from shadow_poc import inspect_shadow_process, validate_shadow_provenance


def _project(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    shutil.copytree(
        POC_ROOT / "multifile_demo",
        project,
        ignore=shutil.ignore_patterns(".liveui", "__pycache__"),
    )
    return project


def _runtime_save_width(project: Path) -> int:
    build = generate_shadow(project)
    resolved = validate_shadow_provenance(inspect_shadow_process(build.workspace))
    return resolved["save"]["minimum_width"]


def test_stale_agent_width_cannot_overwrite_human_edit(tmp_path: Path):
    project = _project(tmp_path)
    controller = RevisionController(project, initial_revision=12)
    agent = controller.begin(
        actor="CLAUDE",
        binding="self.save",
        operation="set_minimum_width",
        desired_value=320,
    )
    human = controller.begin(
        actor="HUMAN",
        binding="self.save",
        operation="set_minimum_width",
        desired_value=280,
    )

    human_result = controller.commit(human)
    after_human = (project / "main_window.py").read_bytes()
    agent_result = controller.commit(agent)

    assert human_result.status == "COMMITTED"
    assert human_result.committed_revision == 13
    assert agent_result.status == "REJECTED_STALE_REVISION"
    assert agent_result.received_revision == 12
    assert agent_result.expected_revision == 13
    assert (project / "main_window.py").read_bytes() == after_human
    assert _runtime_save_width(project) == 280


def test_stale_different_property_is_still_rejected_before_dispatch(tmp_path: Path):
    project = _project(tmp_path)
    controller = RevisionController(project, initial_revision=12)
    agent = controller.begin(
        actor="CLAUDE",
        binding="self.save",
        operation="set_text",
        desired_value="Save Project",
    )
    human = controller.begin(
        actor="HUMAN",
        binding="self.save",
        operation="set_minimum_width",
        desired_value=280,
    )

    assert controller.commit(human).status == "COMMITTED"
    source_after_human = (project / "main_window.py").read_bytes()
    result = controller.commit(agent)

    assert result.status == "REJECTED_STALE_REVISION"
    assert (project / "main_window.py").read_bytes() == source_after_human
    assert _runtime_save_width(project) == 280


def test_external_source_change_rejects_current_revision_transaction(tmp_path: Path):
    project = _project(tmp_path)
    controller = RevisionController(project, initial_revision=12)
    transaction = controller.begin(
        actor="CLAUDE",
        binding="self.save",
        operation="set_minimum_width",
        desired_value=320,
    )
    canonical = project / "main_window.py"
    externally_changed = canonical.read_text(encoding="utf-8") + "\n# external change\n"
    canonical.write_text(externally_changed, encoding="utf-8")

    result = controller.commit(transaction)

    assert result.status == "REJECTED_STALE_SOURCE_HASH"
    assert canonical.read_text(encoding="utf-8") == externally_changed
    assert controller.current_revision == 12

