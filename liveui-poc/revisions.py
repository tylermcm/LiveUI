"""Minimal optimistic-revision gate for deterministic LiveUI edits."""

from __future__ import annotations

import hashlib
import os
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from shadow_poc import run_shadow_round_trip


@dataclass(frozen=True)
class EditTransaction:
    transaction_id: str
    base_revision: int
    actor: str
    binding: str
    operation: str
    desired_value: Any


@dataclass(frozen=True)
class CommitResult:
    status: str
    transaction_id: str
    expected_revision: int
    received_revision: int
    committed_revision: Optional[int] = None
    reason: Optional[str] = None
    verification: Optional[dict] = None


def _transaction_id() -> str:
    seed = f"{time.time_ns()}:{time.perf_counter_ns()}:{os.getpid()}"
    value = uuid.UUID(hashlib.sha256(seed.encode("ascii")).hexdigest()[:32]).hex
    return f"tx_{value[:12]}"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class RevisionController:
    """Reject stale actors before they can produce or write a source patch."""

    def __init__(self, project_root: Path, *, initial_revision: int = 12) -> None:
        self.project_root = project_root.resolve()
        self.canonical_file = self.project_root / "main_window.py"
        self.current_revision = initial_revision
        self._canonical_hash = _sha256(self.canonical_file.read_bytes())

    def begin(
        self,
        *,
        actor: str,
        binding: str,
        operation: str,
        desired_value: Any,
        base_revision: Optional[int] = None,
    ) -> EditTransaction:
        return EditTransaction(
            transaction_id=_transaction_id(),
            base_revision=self.current_revision if base_revision is None else base_revision,
            actor=actor,
            binding=binding,
            operation=operation,
            desired_value=desired_value,
        )

    def commit(self, transaction: EditTransaction) -> CommitResult:
        if transaction.base_revision != self.current_revision:
            return CommitResult(
                status="REJECTED_STALE_REVISION",
                transaction_id=transaction.transaction_id,
                expected_revision=self.current_revision,
                received_revision=transaction.base_revision,
                reason="Transaction was created from an older project revision",
            )

        current_hash = _sha256(self.canonical_file.read_bytes())
        if current_hash != self._canonical_hash:
            return CommitResult(
                status="REJECTED_STALE_SOURCE_HASH",
                transaction_id=transaction.transaction_id,
                expected_revision=self.current_revision,
                received_revision=transaction.base_revision,
                reason="Canonical source changed outside the revision controller",
            )

        if transaction.binding != "self.save" or transaction.operation != "set_minimum_width":
            return CommitResult(
                status="UNSUPPORTED",
                transaction_id=transaction.transaction_id,
                expected_revision=self.current_revision,
                received_revision=transaction.base_revision,
                reason="Only self.save set_minimum_width is supported by this gate proof",
            )
        if not isinstance(transaction.desired_value, int) or isinstance(
            transaction.desired_value, bool
        ):
            return CommitResult(
                status="UNSUPPORTED",
                transaction_id=transaction.transaction_id,
                expected_revision=self.current_revision,
                received_revision=transaction.base_revision,
                reason="Width must be an integer",
            )

        verification = run_shadow_round_trip(
            self.project_root,
            width=transaction.desired_value,
            restore_after=False,
            emit=False,
        )
        self.current_revision += 1
        self._canonical_hash = _sha256(self.canonical_file.read_bytes())
        return CommitResult(
            status="COMMITTED",
            transaction_id=transaction.transaction_id,
            expected_revision=transaction.base_revision,
            received_revision=transaction.base_revision,
            committed_revision=self.current_revision,
            verification=verification,
        )

