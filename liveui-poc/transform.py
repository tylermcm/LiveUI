"""One conservative LibCST transform: a bound widget's minimum width."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

import libcst as cst


@dataclass(frozen=True)
class TransformResult:
    status: str
    reason: Optional[str]
    source: str
    binding: str
    old_width: Optional[int]
    new_width: Optional[int]


class _MinimumWidthTransformer(cst.CSTTransformer):
    def __init__(self, binding: cst.BaseExpression, qualified_scope: str, width: int) -> None:
        self.binding = binding
        self.qualified_scope = qualified_scope
        self.width = width
        self.scope: List[str] = []
        self.matches = 0
        self.old_width: Optional[int] = None
        self.invalid_reason: Optional[str] = None

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
        if ".".join(self.scope) != self.qualified_scope:
            return updated_node
        if not isinstance(original_node.func, cst.Attribute):
            return updated_node
        if original_node.func.attr.value != "setMinimumWidth":
            return updated_node
        if not original_node.func.value.deep_equals(self.binding):
            return updated_node

        self.matches += 1
        if (
            len(original_node.args) != 1
            or original_node.args[0].keyword is not None
            or not isinstance(original_node.args[0].value, cst.Integer)
        ):
            self.invalid_reason = "Supported setter must have one literal integer argument"
            return updated_node

        self.old_width = int(original_node.args[0].value.value, 0)
        replacement_argument = updated_node.args[0].with_changes(
            value=cst.Integer(str(self.width))
        )
        return updated_node.with_changes(args=[replacement_argument])


def set_minimum_width(
    source: str,
    *,
    binding: str,
    width: int,
    qualified_scope: str = "MainWindow.__init__",
) -> TransformResult:
    if not isinstance(width, int) or isinstance(width, bool) or width < 0:
        return TransformResult(
            "unsupported", "Width must be a non-negative integer", source, binding, None, None
        )
    try:
        binding_expression = cst.parse_expression(binding)
        module = cst.parse_module(source)
    except (cst.ParserSyntaxError, cst.PartialParserSyntaxError) as error:
        return TransformResult(
            "unsupported", f"Cannot parse target or binding: {error}", source, binding, None, None
        )

    transformer = _MinimumWidthTransformer(binding_expression, qualified_scope, width)
    updated = module.visit(transformer)
    if transformer.matches == 0:
        reason = "No supported setMinimumWidth setter for binding in source scope"
    elif transformer.matches > 1:
        reason = "Binding has multiple setMinimumWidth setters in source scope"
    else:
        reason = transformer.invalid_reason
    if reason is not None:
        return TransformResult("unsupported", reason, source, binding, None, None)

    return TransformResult(
        "applied", None, updated.code, binding, transformer.old_width, width
    )

