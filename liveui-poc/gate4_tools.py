"""Constrained command surface for the Gate 4 Claude tool-use proof."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Any, Optional

from revisions import RevisionController
from shadow import generate_shadow
from shadow_poc import inspect_shadow_process, validate_shadow_provenance
from transform import set_minimum_width


POC_ROOT = Path(__file__).resolve().parent
DEFAULT_FIXTURE = POC_ROOT / "multifile_demo"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _nonce() -> str:
    seed = f"{time.time_ns()}:{time.perf_counter_ns()}:{os.getpid()}"
    return hashlib.sha256(seed.encode("ascii")).hexdigest()[:16]


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{_nonce()}.tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    os.replace(temporary, path)


def _load_state(state_path: Path) -> dict[str, Any]:
    state = json.loads(state_path.resolve().read_text(encoding="utf-8"))
    if state.get("schema_version") != 1:
        raise RuntimeError("Unsupported Gate 4 state schema")
    return state


def _canonical_path(state: dict[str, Any]) -> Path:
    return Path(state["project_root"]).resolve() / "main_window.py"


def _fresh_save(project_root: Path) -> dict[str, Any]:
    build = generate_shadow(project_root)
    snapshot = inspect_shadow_process(build.workspace)
    return validate_shadow_provenance(snapshot)["save"]


def prepare_workspace(
    workspace_root: Path,
    *,
    fixture_root: Path = DEFAULT_FIXTURE,
    initial_width: int = 280,
) -> Path:
    """Create an isolated revision-1 project with a verified selected width."""

    run_id = f"run_{time.time_ns()}_{os.getpid()}"
    run_root = workspace_root.resolve() / run_id
    project_root = run_root / "project"
    shutil.copytree(
        fixture_root.resolve(),
        project_root,
        ignore=shutil.ignore_patterns(".liveui", "__pycache__"),
    )

    canonical = project_root / "main_window.py"
    original = canonical.read_text(encoding="utf-8")
    transformed = set_minimum_width(
        original,
        binding="self.save",
        width=initial_width,
        qualified_scope="MainWindow.__init__",
    )
    if transformed.status != "applied":
        raise RuntimeError(f"Could not prepare Gate 4 fixture: {transformed.reason}")
    compile(transformed.source, str(canonical), "exec")
    canonical.write_text(transformed.source, encoding="utf-8")

    observed = _fresh_save(project_root)
    if observed["minimum_width"] != initial_width:
        raise RuntimeError("Prepared Gate 4 fixture did not verify in a fresh runtime")

    state_path = run_root / "state.json"
    _atomic_json(
        state_path,
        {
            "schema_version": 1,
            "project_root": str(project_root),
            "revision": 1,
            "canonical_hash": _sha256(canonical.read_bytes()),
            "selection": None,
            "last_commit": None,
        },
    )
    return state_path


def get_selected_component(state_path: Path) -> dict[str, Any]:
    state_path = state_path.resolve()
    state = _load_state(state_path)
    canonical = _canonical_path(state)
    current_hash = _sha256(canonical.read_bytes())
    if current_hash != state["canonical_hash"]:
        return {
            "ok": False,
            "tool": "get_selected_component",
            "status": "REJECTED_STALE_SOURCE_HASH",
            "reason": "Canonical source changed outside the revision controller",
        }

    save = _fresh_save(Path(state["project_root"]))
    if save["provenance_status"] != "resolved" or save["binding_status"] != "resolved":
        return {
            "ok": False,
            "tool": "get_selected_component",
            "status": "UNRESOLVED_SELECTION",
            "reason": "Selected component does not have exact creation and binding provenance",
        }

    component = {
        "runtime_id": save["runtime_id"],
        "binding": save["binding"],
        "qt_class": save["qt_class"],
        "text": save["text"],
        "minimum_width": save["minimum_width"],
        "source_file": save["binding_source_file"],
        "source_line": save["binding_source_line"],
        "source_scope": save["binding_scope"],
        "creation_source_file": save["source_file"],
        "creation_anchor": save["source_anchor"],
        "revision": state["revision"],
    }
    state["selection"] = {
        "component": component,
        "canonical_hash": current_hash,
    }
    _atomic_json(state_path, state)
    return {
        "ok": True,
        "tool": "get_selected_component",
        "component": component,
    }


def set_selected_minimum_width(
    state_path: Path,
    *,
    runtime_id: str,
    width: int,
    base_revision: int,
) -> dict[str, Any]:
    state_path = state_path.resolve()
    state = _load_state(state_path)
    selection = state.get("selection")
    if selection is None:
        return {
            "ok": False,
            "tool": "set_minimum_width",
            "status": "REJECTED_NO_SELECTION",
        }

    component = selection["component"]
    if runtime_id != component["runtime_id"]:
        return {
            "ok": False,
            "tool": "set_minimum_width",
            "status": "REJECTED_RUNTIME_ID",
            "expected_runtime_id": component["runtime_id"],
            "received_runtime_id": runtime_id,
        }
    if base_revision != state["revision"]:
        return {
            "ok": False,
            "tool": "set_minimum_width",
            "status": "REJECTED_STALE_REVISION",
            "expected_revision": state["revision"],
            "received_revision": base_revision,
        }
    if not isinstance(width, int) or isinstance(width, bool) or not 1 <= width <= 4096:
        return {
            "ok": False,
            "tool": "set_minimum_width",
            "status": "REJECTED_INVALID_WIDTH",
        }

    canonical = _canonical_path(state)
    current_hash = _sha256(canonical.read_bytes())
    if (
        current_hash != state["canonical_hash"]
        or current_hash != selection["canonical_hash"]
    ):
        return {
            "ok": False,
            "tool": "set_minimum_width",
            "status": "REJECTED_STALE_SOURCE_HASH",
        }

    controller = RevisionController(
        Path(state["project_root"]), initial_revision=state["revision"]
    )
    transaction = controller.begin(
        actor="CLAUDE",
        binding=component["binding"],
        operation="set_minimum_width",
        desired_value=width,
        base_revision=base_revision,
    )
    result = controller.commit(transaction)
    response: dict[str, Any] = {
        "ok": result.status == "COMMITTED",
        "tool": "set_minimum_width",
        "status": result.status,
        "transaction_id": result.transaction_id,
        "expected_revision": result.expected_revision,
        "received_revision": result.received_revision,
        "committed_revision": result.committed_revision,
        "reason": result.reason,
    }
    if result.status != "COMMITTED":
        return response

    verification = result.verification or {}
    response["verification"] = {
        "binding": component["binding"],
        "minimum_width": verification.get("new_width"),
        "cancel_width": verification.get("cancel_width"),
        "reacquired_runtime_id": verification.get("after_runtime_id"),
        "fresh_runtime_epoch": verification.get("after_epoch"),
    }
    state["revision"] = result.committed_revision
    state["canonical_hash"] = _sha256(canonical.read_bytes())
    state["selection"] = None
    state["last_commit"] = response
    _atomic_json(state_path, state)
    return response


def _emit(value: dict[str, Any]) -> int:
    print(json.dumps(value, sort_keys=True), flush=True)
    return 0 if value.get("ok") else 2


def main(arguments: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="tool", required=True)

    get_parser = subparsers.add_parser("get_selected_component")
    get_parser.add_argument("--state", type=Path, required=True)

    set_parser = subparsers.add_parser("set_minimum_width")
    set_parser.add_argument("--state", type=Path, required=True)
    set_parser.add_argument("--runtime-id", required=True)
    set_parser.add_argument("--width", type=int, required=True)
    set_parser.add_argument("--base-revision", type=int, required=True)

    parsed = parser.parse_args(arguments)
    try:
        if parsed.tool == "get_selected_component":
            return _emit(get_selected_component(parsed.state))
        return _emit(
            set_selected_minimum_width(
                parsed.state,
                runtime_id=parsed.runtime_id,
                width=parsed.width,
                base_revision=parsed.base_revision,
            )
        )
    except Exception as error:
        print(
            json.dumps(
                {
                    "ok": False,
                    "tool": parsed.tool,
                    "status": "TOOL_ERROR",
                    "reason": f"{type(error).__name__}: {error}",
                },
                sort_keys=True,
            ),
            flush=True,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
