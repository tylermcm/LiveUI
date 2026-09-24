"""End-to-end proof using generated LibCST shadow instrumentation."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Iterable

from poc import _atomic_write, _sha256
from shadow import generate_shadow
from transform import set_minimum_width


POC_ROOT = Path(__file__).resolve().parent
RESULT_PREFIX = "LIVEUI_SHADOW_RESULT="


def inspect_shadow_process(workspace: Path) -> dict:
    environment = os.environ.copy()
    environment.setdefault("PYTHONHASHSEED", "0")
    environment.setdefault("QT_QPA_PLATFORM", "offscreen")
    environment.setdefault(
        "QT_QPA_FONTDIR", str(Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts")
    )
    process_started = time.perf_counter()
    process = subprocess.Popen(
        [sys.executable, str(POC_ROOT / "shadow_runner.py"), str(workspace.resolve())],
        cwd=str(workspace.resolve()),
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    result_line = None
    assert process.stdout is not None
    for line in process.stdout:
        if line.startswith(RESULT_PREFIX):
            result_line = line.rstrip("\r\n")
            ready_ms = round((time.perf_counter() - process_started) * 1000, 2)
            break
    try:
        returncode = process.wait(timeout=20)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
        raise RuntimeError("Shadow target did not exit after reporting readiness")
    assert process.stderr is not None
    stderr = process.stderr.read().strip()
    if result_line is None:
        raise RuntimeError(f"Shadow target failed ({returncode}): {stderr}")
    result = json.loads(result_line[len(RESULT_PREFIX) :])
    if returncode != 0 or "error" in result:
        raise RuntimeError(result.get("error", stderr))
    result["process_ready_ms"] = ready_ms
    result["process_exit_ms"] = round((time.perf_counter() - process_started) * 1000, 2)
    return result


def _exactly_one(widgets: Iterable[dict], binding: str) -> dict:
    matches = [widget for widget in widgets if widget["binding"] == binding]
    if len(matches) != 1:
        raise RuntimeError(f"Expected one widget for {binding}; found {len(matches)}")
    return matches[0]


def validate_shadow_provenance(snapshot: dict) -> dict:
    widgets = snapshot["widgets"]
    save = _exactly_one(widgets, "self.save")
    cancel = _exactly_one(widgets, "self.cancel")
    inspector = _exactly_one(widgets, "self.inspector")
    heading = _exactly_one(widgets, "self.heading")
    loop = [widget for widget in widgets if widget["binding"] == "button"]

    if save["text"] != "Save" or cancel["text"] != "Cancel":
        raise RuntimeError("Helper-created buttons did not retain their semantic bindings")
    if save["source_file"] != "widgets.py" or cancel["source_file"] != "widgets.py":
        raise RuntimeError("Helper-created buttons did not map to their factory constructor")
    if save["source_anchor"] != cancel["source_anchor"]:
        raise RuntimeError("Helper-created widgets should share the factory creation anchor")
    if save["binding_source_file"] != "main_window.py":
        raise RuntimeError("Save binding did not map back to main_window.py")
    if save["binding_anchor"] == cancel["binding_anchor"]:
        raise RuntimeError("Save and Cancel binding sites were not distinguished")
    if save["provenance_status"] != "resolved" or save["binding_status"] != "resolved":
        raise RuntimeError("Save provenance or binding was not resolved confidently")
    if len(loop) != 3 or len({widget["runtime_id"] for widget in loop}) != 3:
        raise RuntimeError("Loop runtime instances were not distinguished")
    if len({widget["source_anchor"] for widget in loop}) != 1:
        raise RuntimeError("Loop instances do not share one static creation anchor")
    if inspector["qt_class"] != "InspectorPanel":
        raise RuntimeError("Project-local custom QWidget was not captured")
    if heading["qt_class"] != "QLabel" or heading["source_file"] != "widgets.py":
        raise RuntimeError("Nested widget inside custom QWidget was not captured")
    return {
        "save": save,
        "cancel": cancel,
        "loop": loop,
        "inspector": inspector,
        "heading": heading,
    }


def run_shadow_round_trip(
    project_root: Path,
    *,
    width: int = 280,
    restore_after: bool = False,
    emit: bool = True,
) -> dict:
    root = project_root.resolve()
    canonical_file = root / "main_window.py"
    original_bytes = canonical_file.read_bytes()
    base_hash = _sha256(original_bytes)
    source_written = False
    started = time.perf_counter()

    try:
        before_build = generate_shadow(root)
        if canonical_file.read_bytes() != original_bytes:
            raise RuntimeError("Shadow generation changed canonical source")
        before = inspect_shadow_process(before_build.workspace)
        resolved = validate_shadow_provenance(before)

        if emit:
            print("SHADOW GATE 1 PASSED - multi-file runtime provenance")
            print(
                f'Save runtime={resolved["save"]["runtime_id"]}\n'
                f'    created: {resolved["save"]["source_file"]}:'
                f'{resolved["save"]["source_line"]} anchor={resolved["save"]["source_anchor"]}\n'
                f'    bound: {resolved["save"]["binding_source_file"]}:'
                f'{resolved["save"]["binding_source_line"]} binding=self.save'
            )
            print(
                "Helper factory: Save and Cancel share a creation anchor and have distinct bindings"
            )
            print("Custom QWidget: InspectorPanel and its QLabel were both captured")

        transform_started = time.perf_counter()
        transformed = set_minimum_width(
            original_bytes.decode("utf-8"),
            binding=resolved["save"]["binding"],
            width=width,
            qualified_scope=resolved["save"]["binding_scope"],
        )
        if transformed.status != "applied":
            raise RuntimeError(f"UNSUPPORTED: {transformed.reason}")
        compile(transformed.source, str(canonical_file), "exec")
        if canonical_file.read_bytes() != original_bytes or _sha256(
            canonical_file.read_bytes()
        ) != base_hash:
            raise RuntimeError("STALE_SOURCE_HASH")
        _atomic_write(canonical_file, transformed.source.encode("utf-8"))
        source_written = True
        transform_ms = round((time.perf_counter() - transform_started) * 1000, 2)

        if emit:
            print("\nSHADOW GATE 2 PASSED - canonical binding-specific LibCST mutation")
            print(f"self.save.setMinimumWidth({transformed.old_width}) -> {width}")
            print("Generating a fresh shadow workspace and restarting...")

        restart_started = time.perf_counter()
        after_build = generate_shadow(root)
        after = inspect_shadow_process(after_build.workspace)
        after_resolved = validate_shadow_provenance(after)
        after_save = after_resolved["save"]
        after_cancel = after_resolved["cancel"]
        restart_verify_ms = round((time.perf_counter() - restart_started) * 1000, 2)

        if before["runtime_epoch"] == after["runtime_epoch"]:
            raise RuntimeError("Runtime epoch did not change")
        if resolved["save"]["runtime_id"] == after_save["runtime_id"]:
            raise RuntimeError("Runtime ID was reused across shadow launches")
        if after_save["binding"] != "self.save" or after_save["minimum_width"] != width:
            raise RuntimeError("Reacquired Save widget did not expose the requested width")
        if after_cancel["minimum_width"] != 120:
            raise RuntimeError("Cancel changed while Save was edited")
        if after_save["source_anchor"] != resolved["save"]["source_anchor"]:
            raise RuntimeError("Helper creation anchor did not survive the property edit")

        report = {
            "status": "PASS",
            "method": "LibCST shadow instrumentation",
            "multi_file": "PASS",
            "helper_factory": "PASS",
            "custom_qwidget": "PASS",
            "canonical_untouched_by_instrumentation": "PASS",
            "mutation_restart_verification": "PASS",
            "before_workspace": str(before_build.workspace),
            "after_workspace": str(after_build.workspace),
            "before_epoch": before["runtime_epoch"],
            "after_epoch": after["runtime_epoch"],
            "before_runtime_id": resolved["save"]["runtime_id"],
            "after_runtime_id": after_save["runtime_id"],
            "before_generation_ms": before_build.generation_ms,
            "after_generation_ms": after_build.generation_ms,
            "before_process_ready_ms": before["process_ready_ms"],
            "after_process_ready_ms": after["process_ready_ms"],
            "before_in_process_ready_ms": before["in_process_ready_ms"],
            "after_in_process_ready_ms": after["in_process_ready_ms"],
            "transform_ms": transform_ms,
            "restart_verify_ms": restart_verify_ms,
            "total_ms": round((time.perf_counter() - started) * 1000, 2),
            "old_width": transformed.old_width,
            "new_width": after_save["minimum_width"],
            "cancel_width": after_cancel["minimum_width"],
        }
        if restore_after:
            _atomic_write(canonical_file, original_bytes)
            source_written = False
            report["fixture_restored"] = True

        if emit:
            print("\nSHADOW GATE 3 PASSED - fresh shadow restart and verification")
            print(
                f'Reacquired runtime_id={after_save["runtime_id"]}\n'
                f'binding={after_save["binding"]}\n'
                f'minimumWidth={after_save["minimum_width"]}\nPASS'
            )
        return report
    except Exception:
        if source_written:
            _atomic_write(canonical_file, original_bytes)
        raise


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, default=POC_ROOT / "multifile_demo")
    parser.add_argument("--width", type=int, default=280)
    parser.add_argument("--restore-after", action="store_true")
    arguments = parser.parse_args()
    try:
        report = run_shadow_round_trip(
            arguments.project,
            width=arguments.width,
            restore_after=arguments.restore_after,
            emit=True,
        )
    except Exception as error:
        print(f"\nFAIL: {type(error).__name__}: {error}", file=sys.stderr)
        return 1
    print("\nRESULT=" + json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
