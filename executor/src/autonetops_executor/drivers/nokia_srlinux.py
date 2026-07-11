"""Nokia SR Linux driver — Phase 1 (ADR-0011), gNMI via pygnmi.

STATUS: structural skeleton with honest capability declaration; NOT yet
integration-tested against containerlab. The first containerlab milestone
(simulations/) turns every `pragma: no cover` block into tested code.

Capability notes:
- Pure gNMI SetRequest is atomic per request (per_change) but has no
  confirm/auto-revert; rollback is snapshot_revert (Get full config before,
  Set replace to restore on failure).
- dry_run is not available over plain gNMI; declared False so the planner
  selects a simulation gate + snapshot strategy (ADR-0011/0012).
"""

from __future__ import annotations

import hashlib
from typing import Any, ClassVar

from ..driver import BaseDriver, register
from ..exceptions import ExecutorError
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
class NokiaSrlinuxDriver(BaseDriver):
    name: ClassVar[str] = "srlinux"
    capabilities: ClassVar[CapabilityMatrix] = CapabilityMatrix(
        transactional=Transactionality.PER_CHANGE,
        supports_dry_run=False,
        supports_confirm=False,
        supports_snapshot=True,
        atomicity=Atomicity.PER_DEVICE,
        protocols=[Protocol.GNMI, Protocol.JSON_RPC],
    )

    def _client(self):  # pragma: no cover - requires pygnmi + live device
        try:
            from pygnmi.client import gNMIclient
        except ImportError as exc:
            raise ExecutorError(
                "pygnmi not installed; use `pip install autonetops-executor[gnmi]`"
            ) from exc
        return gNMIclient(
            target=(self.connection["host"], self.connection.get("port", 57400)),
            username=self.connection["username"],
            password=self.connection["password"],
            skip_verify=self.connection.get("skip_verify", False),
        )

    def get_facts(self) -> FactsResult:  # pragma: no cover - live device
        started = utc_now_iso()
        with self._client() as client:
            caps: dict[str, Any] = client.capabilities()
        return FactsResult(
            evidence=self._evidence("get_facts", started, success=True),
            facts={"gnmi_version": caps.get("gnmi_version"), "models": len(caps.get("supported_models", []))},
        )

    def snapshot(self) -> Snapshot:  # pragma: no cover - live device
        self._require("supports_snapshot")
        started = utc_now_iso()
        with self._client() as client:
            config = str(client.get(path=["/"], datatype="config"))
        checksum = hashlib.sha256(config.encode()).hexdigest()
        # TODO(integration): persist snapshot content to evidence storage;
        # in-memory reference is a placeholder until the storage decision.
        self._last_snapshot = config
        return Snapshot(
            evidence=self._evidence("snapshot", started, success=True),
            snapshot_id=f"snap-{checksum[:12]}",
            checksum=checksum,
        )

    def dry_run(self, artifact: ArtifactPayload) -> DiffResult:
        self._require("supports_dry_run")  # always raises: declared unsupported
        raise AssertionError("unreachable")

    def apply(self, artifact: ArtifactPayload) -> PendingChange:  # pragma: no cover - live device
        started = utc_now_iso()
        with self._client() as client:
            result = client.set(replace=[("/", artifact.content)], encoding="json_ietf")
        return PendingChange(
            evidence=self._evidence(
                "apply", started, success=True,
                artifact_checksum=artifact.checksum, gnmi_response=str(result),
            ),
            change_id=f"chg-{artifact.checksum[:12]}",
            rollback_strategy="snapshot_revert",
            confirm_deadline_seconds=None,  # no confirm semantics over plain gNMI
        )

    def confirm(self, change_id: str) -> Evidence:
        self._require("supports_confirm")  # always raises: declared unsupported
        raise AssertionError("unreachable")

    def rollback(self, reference: str) -> Evidence:  # pragma: no cover - live device
        started = utc_now_iso()
        snapshot = getattr(self, "_last_snapshot", None)
        if snapshot is None:
            raise ExecutorError("no snapshot available to revert to")
        with self._client() as client:
            client.set(replace=[("/", snapshot)], encoding="json_ietf")
        return self._evidence("rollback", started, success=True, restored="snapshot")
