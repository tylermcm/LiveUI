"""Execute one generated shadow workspace and emit its runtime snapshot."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import types
import uuid
from pathlib import Path

import PySide6


_PLATFORM_DIR = Path(PySide6.__file__).parent / "plugins" / "platforms"
if _PLATFORM_DIR.is_dir():
    os.environ.setdefault("QT_QPA_PLATFORM_PLUGIN_PATH", str(_PLATFORM_DIR))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication


RESULT_PREFIX = "LIVEUI_SHADOW_RESULT="


def _module_name() -> str:
    seed = f"{time.time_ns()}:{time.perf_counter_ns()}:{os.getpid()}"
    value = uuid.UUID(hashlib.sha256(seed.encode("ascii")).hexdigest()[:32]).hex
    return f"liveui_shadow_target_{value}"


def inspect_shadow(workspace: Path) -> dict:
    workspace = workspace.resolve()
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(workspace))
    started = time.perf_counter()
    app = QApplication.instance() or QApplication([])

    import __liveui_runtime as runtime

    target = workspace / "main_window.py"
    module = types.ModuleType(_module_name())
    module.__file__ = str(target)
    module.__package__ = ""
    exec(compile(target.read_bytes(), str(target), "exec"), module.__dict__)
    window = module.MainWindow()
    window.show()
    app.processEvents()
    result = runtime.snapshot()
    result["in_process_ready_ms"] = round((time.perf_counter() - started) * 1000, 2)
    window.close()
    app.processEvents()
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("workspace", type=Path)
    arguments = parser.parse_args()
    try:
        result = inspect_shadow(arguments.workspace)
    except Exception as error:
        result = {"error": f"{type(error).__name__}: {error}"}
        print(RESULT_PREFIX + json.dumps(result, sort_keys=True), flush=True)
        return 1
    print(RESULT_PREFIX + json.dumps(result, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
