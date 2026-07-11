"""Reference driver: a full transactional lifecycle against an in-memory
device. This is the executable specification of the verb contract — every
real driver must behave observably like this one. Also the workhorse for
orchestrator-flow tests and simulations without a lab.
"""

from __future__ import annotations

import difflib
import hashlib
from typing import ClassVar

from ..driver import BaseDriver, register
from ..exceptions import ChangeNotFound
from ..models import (
    ArtifactPayload,
    Atomicity,
    CapabilityMatrix,
    DiffResult,
    Evidence,
    FactsResult,
    PendingChange,
    Protocol,
    Snapshot,
    Transactionality,
    utc_now_iso,
)


@register
class MockDriver(BaseDriver):
    name: ClassVar[str] = "mock"
    capabilities: ClassVar[CapabilityMatrix] = CapabilityMatrix(
        transactional=Transactionality.PER_SESSION,
        supports_dry_run=True,
        supports_confirm=True,
        supports_snapshot=True,
        atomicity=Atomicity.PER_DEVICE,
        protocols=[Protocol.GNMI],
    )

    CONFIRM_WINDOW_SECONDS = 600

    def __init__(self, target: str, connection: dict | None = None):
        super().__init__(target, connection)
        self._running: str = (connection or {}).get("initial_config", "")
        self._snapshots: dict[str, str] = {}
        # change_id -> (previous_config, confirmed)
        self._changes: dict[str, tuple[str, bool]] = {}

    # -- verbs ----------------------------------------------------------------

    def get_facts(self) -> FactsResult:
        started = utc_now_iso()
        return FactsResult(
            evidence=self._evidence("get_facts", started, success=True),
            facts={
                "platform": "mock",
                "running_checksum": self._checksum(self._running),
            },
        )

    def snapshot(self) -> Snapshot:
        self._require("supports_snapshot")
        started = utc_now_iso()
        checksum = self._checksum(self._running)
        snapshot_id = f"snap-{checksum[:12]}"
        self._snapshots[snapshot_id] = self._running
        return Snapshot(
            evidence=self._evidence("snapshot", started, success=True),
            snapshot_id=snapshot_id,
            checksum=checksum,
        )

    def dry_run(self, artifact: ArtifactPayload) -> DiffResult:
        self._require("supports_dry_run")
        started = utc_now_iso()
        diff = self._diff(self._running, artifact.content)
        return DiffResult(
            evidence=self._evidence(
                "dry_run", started, success=True, artifact_checksum=artifact.checksum
            ),
            changed=bool(diff),
            diff=diff,
        )

    def apply(self, artifact: ArtifactPayload) -> PendingChange:
        started = utc_now_iso()
        previous = self._running
        self._running = artifact.content
        change_id = f"chg-{artifact.checksum[:12]}"
        self._changes[change_id] = (previous, False)
        return PendingChange(
            evidence=self._evidence(
                "apply",
                started,
                success=True,
                artifact_checksum=artifact.checksum,
                diff=self._diff(previous, artifact.content),
            ),
            change_id=change_id,
            rollback_strategy="commit_confirmed",
            confirm_deadline_seconds=self.CONFIRM_WINDOW_SECONDS,
        )

    def confirm(self, change_id: str) -> Evidence:
        self._require("supports_confirm")
        started = utc_now_iso()
        if change_id not in self._changes:
            raise ChangeNotFound(change_id)
        previous, _ = self._changes[change_id]
        self._changes[change_id] = (previous, True)
        return self._evidence("confirm", started, success=True, change_id=change_id)

    def rollback(self, reference: str) -> Evidence:
        started = utc_now_iso()
        if reference in self._changes:
            previous, _ = self._changes.pop(reference)
            self._running = previous
            return self._evidence("rollback", started, success=True, restored="change")
        if reference in self._snapshots:
            self._running = self._snapshots[reference]
            return self._evidence("rollback", started, success=True, restored="snapshot")
        raise ChangeNotFound(reference)

    # -- test hooks ------------------------------------------------------------

    @property
    def running_config(self) -> str:
        return self._running

    def is_confirmed(self, change_id: str) -> bool:
        return self._changes.get(change_id, ("", False))[1]

    # -- internals ---------------------------------------------------------------

    @staticmethod
    def _checksum(content: str) -> str:
        return hashlib.sha256(content.encode()).hexdigest()

    @staticmethod
    def _diff(before: str, after: str) -> str:
        return "".join(
            difflib.unified_diff(
                before.splitlines(keepends=True),
                after.splitlines(keepends=True),
                fromfile="running",
                tofile="candidate",
            )
        )
