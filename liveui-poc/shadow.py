"""Small LibCST shadow-workspace generator for the next feasibility risk."""

from __future__ import annotations

import ast
import hashlib
import os
import shutil
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Set

import libcst as cst
from libcst.metadata import MetadataWrapper, PositionProvider


RUNTIME_IMPORT = (
    "from __liveui_runtime import capture_widget as _liveui_capture_widget, "
    "bind_widget as _liveui_bind_widget\n"
)
SUPPORTED_WIDGETS = {
    "QWidget",
    "QLabel",
    "QPushButton",
    "QLineEdit",
    "QTextEdit",
    "QComboBox",
    "QCheckBox",
    "QFrame",
    "QGroupBox",
    "QMainWindow",
}


@dataclass(frozen=True)
class ShadowBuild:
    workspace: Path
    generation: str
    instrumented_files: Sequence[str]
    generation_ms: float


def _terminal_name(expression: cst.BaseExpression) -> Optional[str]:
    if isinstance(expression, cst.Name):
        return expression.value
    if isinstance(expression, cst.Attribute):
        return expression.attr.value
    return None


class _ClassCollector(cst.CSTVisitor):
    def __init__(self) -> None:
        self.definitions: Dict[str, Set[str]] = {}

    def visit_ClassDef(self, node: cst.ClassDef) -> None:
        bases = {
            name
            for base in node.bases
            for name in [_terminal_name(base.value)]
            if name is not None
        }
        self.definitions[node.name.value] = bases


def discover_custom_widgets(sources: Iterable[str]) -> Set[str]:
    definitions: Dict[str, Set[str]] = {}
    for source in sources:
        collector = _ClassCollector()
        cst.parse_module(source).visit(collector)
        definitions.update(collector.definitions)
    custom: Set[str] = set()
    changed = True
    while changed:
        changed = False
        accepted = SUPPORTED_WIDGETS | custom
        for name, bases in definitions.items():
            if name not in custom and bases & accepted:
                custom.add(name)
                changed = True
    return custom


def _normalized_hash(module: cst.Module, node: cst.CSTNode) -> str:
    source = module.code_for_node(node)
    try:
        parsed = ast.parse(source, mode="eval")
        normalized = ast.dump(parsed.body, annotate_fields=True, include_attributes=False)
    except SyntaxError:
        normalized = source.strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _anchor(
    relative_path: str,
    scope: str,
    kind: str,
    semantic_name: str,
    normalized_hash: str,
) -> str:
    identity = "\x1f".join(
        ("shadow-v1", relative_path, scope or "<module>", kind, semantic_name, normalized_hash)
    )
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]


def _string(value: str) -> cst.SimpleString:
    return cst.SimpleString(repr(value))


def _keyword(name: str, value: cst.BaseExpression) -> cst.Arg:
    return cst.Arg(keyword=cst.Name(name), value=value)


class _Instrumenter(cst.CSTTransformer):
    METADATA_DEPENDENCIES = (PositionProvider,)

    def __init__(
        self,
        module: cst.Module,
        relative_path: str,
        widget_classes: Set[str],
    ) -> None:
        self.module = module
        self.relative_path = relative_path
        self.widget_classes = widget_classes
        self.scope: List[str] = []
        self.changes = 0

    def visit_ClassDef(self, node: cst.ClassDef) -> None:
        self.scope.append(node.name.value)

    def leave_ClassDef(
        self, original_node: cst.ClassDef, updated_node: cst.ClassDef
    ) -> cst.ClassDef:
        self.scope.pop()
        return updated_node

    def visit_FunctionDef(self, node: cst.FunctionDef) -> None:
        self.scope.append(node.name.value)

    def leave_FunctionDef(
        self, original_node: cst.FunctionDef, updated_node: cst.FunctionDef
    ) -> cst.FunctionDef:
        self.scope.pop()
        return updated_node

    def leave_Call(self, original_node: cst.Call, updated_node: cst.Call) -> cst.Call:
        constructor = _terminal_name(original_node.func)
        if constructor not in self.widget_classes:
            return updated_node
        position = self.get_metadata(PositionProvider, original_node)
        scope = ".".join(self.scope)
        anchor = _anchor(
            self.relative_path,
            scope,
            "creation",
            constructor,
            _normalized_hash(self.module, original_node),
        )
        self.changes += 1
        return cst.Call(
            func=cst.Name("_liveui_capture_widget"),
            args=[
                cst.Arg(updated_node),
                _keyword("anchor", _string(anchor)),
                _keyword("source_file", _string(self.relative_path)),
                _keyword("source_line", cst.Integer(str(position.start.line))),
                _keyword("source_scope", _string(scope)),
            ],
        )

    def leave_Assign(self, original_node: cst.Assign, updated_node: cst.Assign) -> cst.Assign:
        if len(original_node.targets) != 1 or not isinstance(original_node.value, cst.Call):
            return updated_node
        target = original_node.targets[0].target
        if not isinstance(target, (cst.Name, cst.Attribute)):
            return updated_node
        return updated_node.with_changes(value=self._bind(target, original_node.value, updated_node.value))

    def leave_AnnAssign(
        self, original_node: cst.AnnAssign, updated_node: cst.AnnAssign
    ) -> cst.AnnAssign:
        if not isinstance(original_node.value, cst.Call):
            return updated_node
        if not isinstance(original_node.target, (cst.Name, cst.Attribute)):
            return updated_node
        return updated_node.with_changes(
            value=self._bind(original_node.target, original_node.value, updated_node.value)
        )

    def _bind(
        self,
        target: cst.BaseExpression,
        original_value: cst.Call,
        updated_value: cst.BaseExpression,
    ) -> cst.Call:
        binding = self.module.code_for_node(target)
        position = self.get_metadata(PositionProvider, original_value)
        scope = ".".join(self.scope)
        anchor = _anchor(
            self.relative_path,
            scope,
            "binding",
            binding,
            _normalized_hash(self.module, original_value),
        )
        self.changes += 1
        return cst.Call(
            func=cst.Name("_liveui_bind_widget"),
            args=[
                cst.Arg(updated_value),
                _keyword("binding", _string(binding)),
                _keyword("anchor", _string(anchor)),
                _keyword("source_file", _string(self.relative_path)),
                _keyword("source_line", cst.Integer(str(position.start.line))),
                _keyword("source_scope", _string(scope)),
            ],
        )


def _runtime_import_index(body: Sequence[cst.BaseStatement]) -> int:
    index = 0
    if body and isinstance(body[0], cst.SimpleStatementLine):
        first = body[0].body
        if len(first) == 1 and isinstance(first[0], cst.Expr) and isinstance(
            first[0].value, (cst.SimpleString, cst.ConcatenatedString)
        ):
            index = 1
    while index < len(body):
        statement = body[index]
        if not isinstance(statement, cst.SimpleStatementLine) or len(statement.body) != 1:
            break
        item = statement.body[0]
        if not (
            isinstance(item, cst.ImportFrom)
            and isinstance(item.module, cst.Name)
            and item.module.value == "__future__"
        ):
            break
        index += 1
    return index


def instrument_source(
    source: str,
    *,
    relative_path: str,
    custom_widgets: Set[str],
) -> tuple[str, int]:
    wrapper = MetadataWrapper(cst.parse_module(source))
    transformer = _Instrumenter(
        wrapper.module,
        relative_path,
        SUPPORTED_WIDGETS | custom_widgets,
    )
    updated = wrapper.visit(transformer)
    if transformer.changes == 0:
        return source, 0
    body = list(updated.body)
    body.insert(_runtime_import_index(body), cst.parse_statement(RUNTIME_IMPORT))
    return updated.with_changes(body=body).code, transformer.changes


def _generation_id() -> str:
    seed = f"{time.time_ns()}:{time.perf_counter_ns()}:{os.getpid()}"
    return uuid.UUID(hashlib.sha256(seed.encode("ascii")).hexdigest()[:32]).hex[:12]


def generate_shadow(project_root: Path) -> ShadowBuild:
    started = time.perf_counter()
    root = project_root.resolve()
    python_files = sorted(
        path
        for path in root.rglob("*.py")
        if ".liveui" not in path.parts and "__pycache__" not in path.parts
    )
    sources = {path: path.read_text(encoding="utf-8") for path in python_files}
    custom_widgets = discover_custom_widgets(sources.values())
    generation = _generation_id()
    workspace = root / ".liveui" / "runtime_workspace" / generation
    workspace.mkdir(parents=True, exist_ok=False)
    instrumented: List[str] = []

    for path, source in sources.items():
        relative = path.relative_to(root).as_posix()
        output = workspace / path.relative_to(root)
        output.parent.mkdir(parents=True, exist_ok=True)
        transformed, changes = instrument_source(
            source,
            relative_path=relative,
            custom_widgets=custom_widgets,
        )
        output.write_text(transformed, encoding="utf-8")
        if changes:
            instrumented.append(relative)

    runtime_source = Path(__file__).with_name("shadow_runtime.py")
    shutil.copy2(runtime_source, workspace / "__liveui_runtime.py")
    return ShadowBuild(
        workspace=workspace,
        generation=generation,
        instrumented_files=tuple(instrumented),
        generation_ms=round((time.perf_counter() - started) * 1000, 2),
    )
