"""Mechanical stale-revision rejection proof."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
import uuid
from pathlib import Path

from revisions import RevisionController
from shadow import generate_shadow
from shadow_poc import inspect_shadow_process, validate_shadow_provenance


POC_ROOT = Path(__file__).resolve().parent


def _workspace_id() -> str:
    seed = f"{time.time_ns()}:{time.perf_counter_ns()}:{os.getpid()}"
    return uuid.UUID(hashlib.sha256(seed.encode("ascii")).hexdigest()[:32]).hex[:12]


def run_gate_5() -> dict:
    workspace = POC_ROOT / ".gate5_workspace" / _workspace_id()
    shutil.copytree(
        POC_ROOT / "multifile_demo",
        workspace,
        ignore=shutil.ignore_patterns(".liveui", "__pycache__"),
    )
    controller = RevisionController(workspace, initial_revision=12)

    stale_width = controller.begin(
        actor="CLAUDE",
        binding="self.save",
        operation="set_minimum_width",
        desired_value=320,
    )
    stale_text = controller.begin(
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
    human_result = controller.commit(human)
    source_after_human = controller.canonical_file.read_bytes()
    stale_width_result = controller.commit(stale_width)
    stale_text_result = controller.commit(stale_text)

    if human_result.status != "COMMITTED" or controller.current_revision != 13:
        raise RuntimeError("Human revision did not commit as revision 13")
    if stale_width_result.status != "REJECTED_STALE_REVISION":
        raise RuntimeError("Stale width transaction was not rejected")
    if stale_text_result.status != "REJECTED_STALE_REVISION":
        raise RuntimeError("Stale text transaction was not rejected before dispatch")
    if controller.canonical_file.read_bytes() != source_after_human:
        raise RuntimeError("Stale transaction changed canonical source")

    build = generate_shadow(workspace)
    runtime = validate_shadow_provenance(inspect_shadow_process(build.workspace))
    if runtime["save"]["minimum_width"] != 280:
        raise RuntimeError("Runtime state did not preserve the human width")

    return {
        "status": "PASS",
        "initial_revision": 12,
        "current_revision": controller.current_revision,
        "human_transaction": human_result.status,
        "stale_width_transaction": stale_width_result.status,
        "stale_text_transaction": stale_text_result.status,
        "agent_base_revision": stale_width_result.received_revision,
        "expected_revision": stale_width_result.expected_revision,
        "canonical_width": 280,
        "runtime_width": runtime["save"]["minimum_width"],
        "workspace": str(workspace),
    }


def main() -> int:
    try:
        report = run_gate_5()
    except Exception as error:
        print(f"GATE 5 FAIL: {type(error).__name__}: {error}")
        return 1
    print("GATE 5 PASSED - stale actors cannot overwrite canonical source")
    print(
        f'agent_base_revision={report["agent_base_revision"]}\n'
        f'current_revision={report["expected_revision"]}\n'
        f'stale_width={report["stale_width_transaction"]}\n'
        f'stale_text={report["stale_text_transaction"]}\n'
        f'canonical_width={report["canonical_width"]}\n'
        f'runtime_width={report["runtime_width"]}'
    )
    print("RESULT=" + json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

