"""Stable source anchors for the deliberately supported LiveUI surface.

Positions and whole-file revisions are useful for presentation and concurrency
checks, but deliberately do not participate in identity. See ``_anchor_id`` for
the conservative identity recipe used by this feasibility spike.
"""

from __future__ import annotations

import ast
import hashlib
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Collection, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

import libcst as cst
from libcst.metadata import MetadataWrapper, PositionProvider


ANCHOR_SCHEMA_VERSION = "liveui-anchor-v1"

SUPPORTED_WIDGET_CLASSES = frozenset(
    {
        "QWidget",
        "QLabel",
        "QPushButton",
        "QLineEdit",
        "QTextEdit",
        "QComboBox",
        "QCheckBox",
        "QListWidget",
        "QTreeWidget",
        "QTableWidget",
        "QFrame",
        "QGroupBox",
        "QMainWindow",
    }
)

SUPPORTED_LAYOUT_OPERATIONS = frozenset(
    {"addWidget", "insertWidget", "addLayout", "insertLayout"}
)


@dataclass(frozen=True)
class SourceAnchor:
    """Stable identity plus current-location metadata for one source site."""

    anchor_id: str
    relative_path: str
    qualified_scope: Optional[str]
    node_type: str
    start_line: int
    start_column: int
    end_line: int
    end_column: int
    structural_path: Optional[str]
    normalized_node_hash: str
    source_revision: str

    def equivalent_to(self, other: "SourceAnchor") -> bool:
        """Return whether two observations identify the same logical site."""

        return self.anchor_id == other.anchor_id


@dataclass(frozen=True)
class SourceSite:
    """A supported UI-relevant CST site and its stable anchor."""

    anchor: SourceAnchor
    semantic_kind: str
    symbol: str
    source_text: str


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _normalized_path(relative_path: str) -> str:
    return PurePosixPath(relative_path.replace("\\", "/")).as_posix()


def _dotted_name(expression: cst.BaseExpression) -> Optional[str]:
    if isinstance(expression, cst.Name):
        return expression.value
    if isinstance(expression, cst.Attribute):
        left = _dotted_name(expression.value)
        return f"{left}.{expression.attr.value}" if left else expression.attr.value
    return None


def _terminal_name(expression: cst.BaseExpression) -> Optional[str]:
    dotted = _dotted_name(expression)
    return dotted.rsplit(".", 1)[-1] if dotted else None


def _normalized_syntax_hash(source_text: str) -> str:
    """Hash Python semantics while ignoring trivia such as whitespace."""

    parsed = ast.parse(source_text, mode="eval")
    normalized = ast.dump(parsed.body, annotate_fields=True, include_attributes=False)
    return _sha256(normalized.encode("utf-8"))


def _anchor_id(
    *,
    relative_path: str,
    qualified_scope: Optional[str],
    semantic_kind: str,
    symbol: str,
    normalized_node_hash: str,
    occurrence: int,
) -> str:
    identity = "\x1f".join(
        (
            ANCHOR_SCHEMA_VERSION,
            relative_path,
            qualified_scope or "<module>",
            semantic_kind,
            symbol,
            normalized_node_hash,
            str(occurrence),
        )
    )
    return _sha256(identity.encode("utf-8"))[:24]


class _ClassCollector(cst.CSTVisitor):
    def __init__(self) -> None:
        self.classes: Dict[str, Set[str]] = {}

    def visit_ClassDef(self, node: cst.ClassDef) -> None:
        bases = {
            name
            for argument in node.bases
            for name in [_terminal_name(argument.value)]
            if name is not None
        }
        self.classes[node.name.value] = bases


def discover_custom_widget_classes(sources: Iterable[str]) -> Set[str]:
    """Find project classes transitively derived from a supported QWidget."""

    definitions: Dict[str, Set[str]] = {}
    for source in sources:
        collector = _ClassCollector()
        cst.parse_module(source).visit(collector)
        definitions.update(collector.classes)

    discovered: Set[str] = set()
    changed = True
    while changed:
        changed = False
        accepted_bases = SUPPORTED_WIDGET_CLASSES | discovered
        for class_name, bases in definitions.items():
            if class_name not in discovered and bases & accepted_bases:
                discovered.add(class_name)
                changed = True
    return discovered


class _SiteVisitor(cst.CSTVisitor):
    METADATA_DEPENDENCIES = (PositionProvider,)

    def __init__(
        self,
        *,
        module: cst.Module,
        relative_path: str,
        source_revision: str,
        custom_widget_classes: Collection[str],
    ) -> None:
        self.module = module
        self.relative_path = relative_path
        self.source_revision = source_revision
        self.widget_classes = SUPPORTED_WIDGET_CLASSES | frozenset(custom_widget_classes)
        self.scope: List[str] = []
        self.occurrences: Dict[Tuple[str, str, str, str], int] = {}
        self.sites: List[SourceSite] = []

    def visit_ClassDef(self, node: cst.ClassDef) -> None:
        self.scope.append(node.name.value)

    def leave_ClassDef(self, original_node: cst.ClassDef) -> None:
        self.scope.pop()

    def visit_FunctionDef(self, node: cst.FunctionDef) -> None:
        self.scope.append(node.name.value)

    def leave_FunctionDef(self, original_node: cst.FunctionDef) -> None:
        self.scope.pop()

    def visit_Call(self, node: cst.Call) -> None:
        symbol = _terminal_name(node.func)
        if symbol is None:
            return

        semantic_kind: Optional[str] = None
        if symbol in self.widget_classes:
            semantic_kind = "widget_constructor"
        elif symbol in SUPPORTED_LAYOUT_OPERATIONS and isinstance(node.func, cst.Attribute):
            semantic_kind = "layout_operation"
        elif symbol == "connect" and isinstance(node.func, cst.Attribute):
            semantic_kind = "signal_connection"

        if semantic_kind is not None:
            self._record(node, semantic_kind=semantic_kind, symbol=symbol)

    def _record(self, node: cst.Call, *, semantic_kind: str, symbol: str) -> None:
        source_text = self.module.code_for_node(node)
        normalized_hash = _normalized_syntax_hash(source_text)
        scope_name = ".".join(self.scope) or None
        occurrence_key = (scope_name or "<module>", semantic_kind, symbol, normalized_hash)
        occurrence = self.occurrences.get(occurrence_key, 0)
        self.occurrences[occurrence_key] = occurrence + 1
        structural_path = (
            f"{scope_name or '<module>'}/{semantic_kind}:{symbol}/"
            f"{normalized_hash[:12]}[{occurrence}]"
        )
        position = self.get_metadata(PositionProvider, node)
        anchor = SourceAnchor(
            anchor_id=_anchor_id(
                relative_path=self.relative_path,
                qualified_scope=scope_name,
                semantic_kind=semantic_kind,
                symbol=symbol,
                normalized_node_hash=normalized_hash,
                occurrence=occurrence,
            ),
            relative_path=self.relative_path,
            qualified_scope=scope_name,
            node_type=type(node).__name__,
            start_line=position.start.line,
            start_column=position.start.column,
            end_line=position.end.line,
            end_column=position.end.column,
            structural_path=structural_path,
            normalized_node_hash=normalized_hash,
            source_revision=self.source_revision,
        )
        self.sites.append(
            SourceSite(
                anchor=anchor,
                semantic_kind=semantic_kind,
                symbol=symbol,
                source_text=source_text,
            )
        )


def analyze_source(
    source: str,
    *,
    relative_path: str,
    custom_widget_classes: Collection[str] = (),
    source_revision: Optional[str] = None,
) -> List[SourceSite]:
    """Return supported UI source sites in deterministic source order."""

    module = cst.parse_module(source)
    normalized_path = _normalized_path(relative_path)
    wrapper = MetadataWrapper(module)
    visitor = _SiteVisitor(
        module=wrapper.module,
        relative_path=normalized_path,
        source_revision=source_revision or _sha256(source.encode("utf-8")),
        custom_widget_classes=custom_widget_classes,
    )
    wrapper.visit(visitor)
    return visitor.sites


def analyze_project(project_root: Path) -> Mapping[str, Sequence[SourceSite]]:
    """Analyze Python files below ``project_root`` using a two-pass scan."""

    root = Path(project_root).resolve()
    files = sorted(
        path
        for path in root.rglob("*.py")
        if not any(part in {".liveui", ".venv", "__pycache__"} for part in path.parts)
    )
    raw_sources = {path: path.read_bytes() for path in files}
    sources = {path: raw.decode("utf-8") for path, raw in raw_sources.items()}
    custom_classes = discover_custom_widget_classes(sources.values())
    return {
        path.relative_to(root).as_posix(): tuple(
            analyze_source(
                source,
                relative_path=path.relative_to(root).as_posix(),
                custom_widget_classes=custom_classes,
                source_revision=_sha256(raw_sources[path]),
            )
        )
        for path, source in sources.items()
    }
