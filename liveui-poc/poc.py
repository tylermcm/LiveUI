"""Run the three-gate LiveUI feasibility round trip."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Iterable, Optional

from provenance import RESULT_PREFIX
from transform import set_minimum_width


POC_ROOT = Path(__file__).resolve().parent


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _atomic_write(path: Path, data: bytes) -> None:
    seed = f"{time.time_ns()}:{time.perf_counter_ns()}:{os.getpid()}"
    suffix = uuid.UUID(hashlib.sha256(seed.encode("ascii")).hexdigest()[:32]).hex
    temporary = path.with_name(f".{path.name}.{suffix}.tmp")
    try:
        temporary.write_bytes(data)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def inspect_in_target_process(target: Path) -> dict:
    environment = os.environ.copy()
    environment.setdefault("PYTHONHASHSEED", "0")
    environment.setdefault("QT_QPA_PLATFORM", "offscreen")
    environment.setdefault("QT_QPA_FONTDIR", str(Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"))
    process_started = time.perf_counter()
    process = subprocess.Popen(
        [sys.executable, str(POC_ROOT / "provenance.py"), str(target.resolve())],
        cwd=str(target.resolve().parent),
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
        raise RuntimeError("Target did not exit after reporting readiness")
    assert process.stderr is not None
    stderr = process.stderr.read().strip()
    if result_line is None:
        raise RuntimeError(f"Target inspection failed ({returncode}): {stderr}")
    result = json.loads(result_line[len(RESULT_PREFIX) :])
    if returncode != 0 or "error" in result:
        raise RuntimeError(result.get("error", stderr))
    result["process_ready_ms"] = ready_ms
    result["process_exit_ms"] = round((time.perf_counter() - process_started) * 1000, 2)
    return result


def _exactly_one(widgets: Iterable[dict], *, binding: str) -> dict:
    matches = [widget for widget in widgets if widget["binding"] == binding]
    if len(matches) != 1:
        raise RuntimeError(f"Expected one runtime widget for {binding}; found {len(matches)}")
    return matches[0]


def _validate_gate_1(snapshot: dict) -> dict:
    widgets = snapshot["widgets"]
    save = _exactly_one(widgets, binding="self.save")
    cancel = _exactly_one(widgets, binding="self.cancel")
    loop = [widget for widget in widgets if widget["binding"] == "button"]

    if save["qt_class"] != "QPushButton" or save["text"] != "Save":
        raise RuntimeError("self.save did not resolve to the Save QPushButton")
    if cancel["qt_class"] != "QPushButton" or cancel["text"] != "Cancel":
        raise RuntimeError("self.cancel did not resolve to the Cancel QPushButton")
    if sorted(widget["text"] for widget in loop) != ["One", "Three", "Two"]:
        raise RuntimeError("Loop-created buttons were not all captured")
    if len({widget["runtime_id"] for widget in loop}) != 3:
        raise RuntimeError("Loop-created widgets do not have unique runtime IDs")
    if len({widget["source_anchor"] for widget in loop}) != 1:
        raise RuntimeError("Loop-created widgets do not share one static creation anchor")
    if any(widget["source_anchor"] is None for widget in widgets):
        raise RuntimeError("At least one intercepted runtime widget has no source anchor")
    return {"save": save, "cancel": cancel, "loop": loop}


def run_round_trip(
    target: Path,
    *,
    width: int = 280,
    restore_after: bool = False,
    emit: bool = True,
) -> dict:
    target = target.resolve()
    original_bytes = target.read_bytes()
    base_hash = _sha256(original_bytes)
    source_written = False
    overall_started = time.perf_counter()

    try:
        before = inspect_in_target_process(target)
        resolved = _validate_gate_1(before)
        if emit:
            print("GATE 1 PASSED - runtime constructor interception")
            for widget in before["widgets"]:
                print(
                    f'{widget["runtime_id"]} {widget["qt_class"]} {widget["text"]!r}\n'
                    f'    source: {widget["source_file"]}:{widget["source_line"]}\n'
                    f'    binding: {widget["binding"]}'
                )

        transform_started = time.perf_counter()
        transformed = set_minimum_width(
            original_bytes.decode("utf-8"),
            binding=resolved["save"]["binding"],
            width=width,
            qualified_scope="MainWindow.__init__",
        )
        if transformed.status != "applied":
            raise RuntimeError(f"UNSUPPORTED: {transformed.reason}")
        compile(transformed.source, str(target), "exec")
        if target.read_bytes() != original_bytes or _sha256(target.read_bytes()) != base_hash:
            raise RuntimeError("STALE_SOURCE_HASH")
        _atomic_write(target, transformed.source.encode("utf-8"))
        source_written = True
        transform_ms = round((time.perf_counter() - transform_started) * 1000, 2)

        if emit:
            print("\nGATE 2 PASSED - deterministic LibCST mutation")
            print(
                f"SOURCE CHANGE:\nself.save.setMinimumWidth({transformed.old_width})\n"
                f"->\nself.save.setMinimumWidth({width})"
            )
            print("self.cancel remains independently bound and unmodified")
            print("\nRestarting...")

        restart_started = time.perf_counter()
        after = inspect_in_target_process(target)
        after_save = _exactly_one(after["widgets"], binding="self.save")
        after_cancel = _exactly_one(after["widgets"], binding="self.cancel")
        restart_verify_ms = round((time.perf_counter() - restart_started) * 1000, 2)

        if after["runtime_epoch"] == before["runtime_epoch"]:
            raise RuntimeError("Runtime epoch did not change after restart")
        if after_save["runtime_id"] == resolved["save"]["runtime_id"]:
            raise RuntimeError("Runtime ID was incorrectly reused across epochs")
        if after_save["binding"] != "self.save" or after_save["minimum_width"] != width:
            raise RuntimeError("Restarted Save widget did not expose the requested width")
        if after_cancel["minimum_width"] != 120:
            raise RuntimeError("Cancel width changed while mutating Save")

        if emit:
            print("\nGATE 3 PASSED - restart, reacquire, runtime verification")
            print(
                f'Reacquired:\nruntime_id={after_save["runtime_id"]}\n'
                f'binding={after_save["binding"]}\n\n'
                f'Expected minimumWidth:\n{width}\n\n'
                f'Runtime minimumWidth:\n{after_save["minimum_width"]}\n\nPASS'
            )

        report = {
            "status": "PASS",
            "gate_1": "PASS",
            "gate_1_method": "runtime interception",
            "gate_2": "PASS",
            "gate_3": "PASS",
            "gate_4": "NOT ATTEMPTED",
            "gate_5": "NOT ATTEMPTED",
            "before_epoch": before["runtime_epoch"],
            "after_epoch": after["runtime_epoch"],
            "before_runtime_id": resolved["save"]["runtime_id"],
            "after_runtime_id": after_save["runtime_id"],
            "before_process_ready_ms": before["process_ready_ms"],
            "after_process_ready_ms": after["process_ready_ms"],
            "before_in_process_ready_ms": before["in_process_ready_ms"],
            "after_in_process_ready_ms": after["in_process_ready_ms"],
            "transform_ms": transform_ms,
            "restart_verify_ms": restart_verify_ms,
            "total_ms": round((time.perf_counter() - overall_started) * 1000, 2),
            "binding": "self.save",
            "old_width": transformed.old_width,
            "new_width": after_save["minimum_width"],
            "cancel_width": after_cancel["minimum_width"],
        }
        if restore_after:
            _atomic_write(target, original_bytes)
            source_written = False
            report["fixture_restored"] = True
        return report
    except Exception:
        if source_written:
            _atomic_write(target, original_bytes)
        raise


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", type=Path, default=POC_ROOT / "demo_app.py")
    parser.add_argument("--width", type=int, default=280)
    parser.add_argument("--restore-after", action="store_true")
    arguments = parser.parse_args()
    try:
        report = run_round_trip(
            arguments.target,
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
