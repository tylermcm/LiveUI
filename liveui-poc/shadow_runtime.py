"""Tiny runtime injected into generated shadow workspaces."""

from __future__ import annotations

import hashlib
import os
import time
import uuid
from dataclasses import dataclass
from typing import Dict, Optional

from PySide6.QtWidgets import QWidget


def _new_epoch() -> str:
    seed = f"{time.time_ns()}:{time.perf_counter_ns()}:{os.getpid()}"
    return uuid.UUID(hashlib.sha256(seed.encode("ascii")).hexdigest()[:32]).hex


@dataclass
class _Record:
    runtime_id: str
    runtime_epoch: str
    widget: QWidget
    source_anchor: str
    source_file: str
    source_line: int
    source_scope: str
    provenance_status: str
    provenance_reason: Optional[str]
    binding: Optional[str] = None
    binding_anchor: Optional[str] = None
    binding_source_file: Optional[str] = None
    binding_source_line: Optional[int] = None
    binding_scope: Optional[str] = None
    binding_status: str = "unresolved"
    binding_reason: Optional[str] = "No supported assignment binding was captured"


_EPOCH = _new_epoch()
_RECORDS: Dict[int, _Record] = {}


def _record_widget(
    widget,
    *,
    anchor: str,
    source_file: str,
    source_line: int,
    source_scope: str,
    provenance_status: str,
    provenance_reason: Optional[str],
) -> Optional[_Record]:
    if not isinstance(widget, QWidget):
        return None
    key = id(widget)
    record = _RECORDS.get(key)
    if record is None:
        runtime_id = f"w_{_EPOCH[:8]}_{len(_RECORDS) + 1:03d}"
        record = _Record(
            runtime_id=runtime_id,
            runtime_epoch=_EPOCH,
            widget=widget,
            source_anchor=anchor,
            source_file=source_file,
            source_line=source_line,
            source_scope=source_scope,
            provenance_status=provenance_status,
            provenance_reason=provenance_reason,
        )
        _RECORDS[key] = record
        widget.setProperty("__liveui_runtime_id", runtime_id)
        widget.setProperty("__liveui_source_anchor", anchor)
    return record


def capture_widget(
    widget,
    *,
    anchor: str,
    source_file: str,
    source_line: int,
    source_scope: str,
):
    _record_widget(
        widget,
        anchor=anchor,
        source_file=source_file,
        source_line=source_line,
        source_scope=source_scope,
        provenance_status="resolved",
        provenance_reason=None,
    )
    return widget


def bind_widget(
    value,
    *,
    binding: str,
    anchor: str,
    source_file: str,
    source_line: int,
    source_scope: str,
):
    existing = _RECORDS.get(id(value)) if isinstance(value, QWidget) else None
    record = _record_widget(
        value,
        anchor=anchor,
        source_file=source_file,
        source_line=source_line,
        source_scope=source_scope,
        provenance_status="binding_only",
        provenance_reason="Constructor expression was not recognized by shadow instrumentation",
    )
    if record is not None:
        record.binding = binding
        record.binding_anchor = anchor
        record.binding_source_file = source_file
        record.binding_source_line = source_line
        record.binding_scope = source_scope
        record.binding_status = "resolved"
        record.binding_reason = None
        if existing is not None:
            record.provenance_status = existing.provenance_status
            record.provenance_reason = existing.provenance_reason
        value.setProperty("__liveui_binding", binding)
    return value


def snapshot() -> dict:
    widgets = []
    for record in _RECORDS.values():
        widget = record.widget
        item = {
            key: value
            for key, value in record.__dict__.items()
            if key != "widget"
        }
        item.update(
            {
                "qt_class": widget.metaObject().className(),
                "object_name": widget.objectName(),
                "text": widget.text() if hasattr(widget, "text") else None,
                "minimum_width": widget.minimumWidth(),
            }
        )
        widgets.append(item)
    return {"runtime_epoch": _EPOCH, "widgets": widgets}
