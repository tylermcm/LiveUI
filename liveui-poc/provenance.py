"""Minimal runtime-constructor interception for the rapid LiveUI proof.

This intentionally supports only QPushButton and QLabel. The target imports a
temporary Python wrapper from ``PySide6.QtWidgets``; the wrapper creates the
real Shiboken widget, records its caller frame, and returns it unchanged.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import sys
import time
import types
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

# This host's conda Qt metadata can point one directory above the package's
# actual plugins. Set the package-owned path before QApplication is imported.
import PySide6


_PLATFORM_DIR = Path(PySide6.__file__).parent / "plugins" / "platforms"
if _PLATFORM_DIR.is_dir():
    os.environ.setdefault("QT_QPA_PLATFORM_PLUGIN_PATH", str(_PLATFORM_DIR))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import libcst as cst
from libcst.metadata import MetadataWrapper, PositionProvider
from PySide6 import QtWidgets


INTERCEPTED_CLASSES = ("QPushButton", "QLabel")
RESULT_PREFIX = "LIVEUI_RESULT="


@dataclass(frozen=True)
class CreationSite:
    line: int
    function: str
    constructor: str
    binding: str
    anchor: str


@dataclass(frozen=True)
class RuntimeWidget:
    runtime_id: str
    runtime_epoch: str
    qt_class: str
    text: Optional[str]
    object_name: str
    minimum_width: int
    source_file: str
    source_line: int
    source_function: str
    binding: Optional[str]
    source_anchor: Optional[str]


def _terminal_name(expression: cst.BaseExpression) -> Optional[str]:
    if isinstance(expression, cst.Name):
        return expression.value
    if isinstance(expression, cst.Attribute):
        return expression.attr.value
    return None


def _normalized_call_hash(module: cst.Module, node: cst.Call) -> str:
    source = module.code_for_node(node)
    parsed = ast.parse(source, mode="eval")
    normalized = ast.dump(parsed.body, annotate_fields=True, include_attributes=False)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _runtime_epoch() -> str:
    """Create a UUID-shaped epoch without depending on host entropy services."""

    seed = f"{time.time_ns()}:{time.perf_counter_ns()}:{os.getpid()}"
    return uuid.UUID(hashlib.sha256(seed.encode("ascii")).hexdigest()[:32]).hex


class _BindingVisitor(cst.CSTVisitor):
    METADATA_DEPENDENCIES = (PositionProvider,)

    def __init__(self, module: cst.Module, source_file: str) -> None:
        self.module = module
        self.source_file = source_file
        self.scope: List[str] = []
        self.sites: List[CreationSite] = []

    def visit_ClassDef(self, node: cst.ClassDef) -> None:
        self.scope.append(node.name.value)

    def leave_ClassDef(self, original_node: cst.ClassDef) -> None:
        self.scope.pop()

    def visit_FunctionDef(self, node: cst.FunctionDef) -> None:
        self.scope.append(node.name.value)

    def leave_FunctionDef(self, original_node: cst.FunctionDef) -> None:
        self.scope.pop()

    def visit_Assign(self, node: cst.Assign) -> None:
        if len(node.targets) != 1 or not isinstance(node.value, cst.Call):
            return
        self._record(node.targets[0].target, node.value)

    def visit_AnnAssign(self, node: cst.AnnAssign) -> None:
        if isinstance(node.value, cst.Call):
            self._record(node.target, node.value)

    def _record(self, target: cst.BaseAssignTargetExpression, call: cst.Call) -> None:
        constructor = _terminal_name(call.func)
        if constructor not in INTERCEPTED_CLASSES:
            return
        binding = self.module.code_for_node(target)
        function = ".".join(self.scope)
        position = self.get_metadata(PositionProvider, call)
        normalized_hash = _normalized_call_hash(self.module, call)
        identity = "\x1f".join(
            (self.source_file, function, constructor, binding, normalized_hash)
        )
        anchor = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]
        self.sites.append(
            CreationSite(
                line=position.start.line,
                function=function,
                constructor=constructor,
                binding=binding,
                anchor=anchor,
            )
        )


def creation_sites(target: Path) -> Sequence[CreationSite]:
    source = target.read_text(encoding="utf-8")
    wrapper = MetadataWrapper(cst.parse_module(source))
    visitor = _BindingVisitor(wrapper.module, target.name)
    wrapper.visit(visitor)
    return tuple(visitor.sites)


def _resolve_site(
    sites: Sequence[CreationSite], *, line: int, constructor: str
) -> Optional[CreationSite]:
    matches = [site for site in sites if site.line == line and site.constructor == constructor]
    return matches[0] if len(matches) == 1 else None


def inspect_target(target: Path) -> dict:
    """Instantiate ``MainWindow`` and return a JSON-compatible runtime snapshot."""

    target = target.resolve()
    sites = creation_sites(target)
    epoch = _runtime_epoch()
    captured: List[Tuple[object, str, str, int, str]] = []
    originals = {name: getattr(QtWidgets, name) for name in INTERCEPTED_CLASSES}

    def wrapper_for(constructor_name: str):
        original = originals[constructor_name]

        def construct(*args, **kwargs):
            caller = sys._getframe(1)
            widget = original(*args, **kwargs)
            captured.append(
                (
                    widget,
                    constructor_name,
                    caller.f_code.co_filename,
                    caller.f_lineno,
                    caller.f_code.co_name,
                )
            )
            return widget

        construct.__name__ = constructor_name
        return construct

    started = time.perf_counter()
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    module_name = f"liveui_target_{epoch}"
    module = types.ModuleType(module_name)
    module.__file__ = str(target)
    module.__package__ = ""

    try:
        for name in INTERCEPTED_CLASSES:
            setattr(QtWidgets, name, wrapper_for(name))
        # Always compile canonical bytes. Timestamp-and-size pyc validation can
        # reuse stale bytecode after a rapid same-length edit (120 -> 280).
        code = compile(target.read_bytes(), str(target), "exec")
        exec(code, module.__dict__)
        window = module.MainWindow()
        window.show()
        app.processEvents()
    finally:
        for name, original in originals.items():
            setattr(QtWidgets, name, original)

    widgets: List[RuntimeWidget] = []
    for index, (widget, constructor, filename, line, function) in enumerate(captured, 1):
        site = _resolve_site(sites, line=line, constructor=constructor)
        runtime_id = f"w_{epoch[:8]}_{index:03d}"
        widget.setProperty("__liveui_runtime_id", runtime_id)
        widget.setProperty("__liveui_source_anchor", site.anchor if site else None)
        widgets.append(
            RuntimeWidget(
                runtime_id=runtime_id,
                runtime_epoch=epoch,
                qt_class=widget.metaObject().className(),
                text=widget.text() if hasattr(widget, "text") else None,
                object_name=widget.objectName(),
                minimum_width=widget.minimumWidth(),
                source_file=Path(filename).name,
                source_line=line,
                source_function=site.function if site else function,
                binding=site.binding if site else None,
                source_anchor=site.anchor if site else None,
            )
        )

    window.close()
    app.processEvents()
    return {
        "runtime_epoch": epoch,
        "in_process_ready_ms": round((time.perf_counter() - started) * 1000, 2),
        "widgets": [asdict(widget) for widget in widgets],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("target", type=Path)
    arguments = parser.parse_args()
    try:
        result = inspect_target(arguments.target)
    except Exception as error:
        result = {"error": f"{type(error).__name__}: {error}"}
        print(RESULT_PREFIX + json.dumps(result, sort_keys=True), flush=True)
        return 1
    print(RESULT_PREFIX + json.dumps(result, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
