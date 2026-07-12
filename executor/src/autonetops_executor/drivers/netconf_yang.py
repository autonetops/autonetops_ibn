"""Generic NETCONF driver (ncclient) for MODEL-BASED artifacts (ADR-0012).

This is the preferred delivery path the moment a compiler emits ietf-xml
(or openconfig-json translated to XML) artifacts: any platform whose SoT
record claims the ``netconf`` capability can ride it, vendor-neutrally.

Transaction semantics are the best in the fleet:
- apply: lock candidate -> edit-config -> commit *confirmed* with a
  timeout; the device auto-reverts unless confirm() lands in time. This is
  the one driver where supports_confirm=True today.
- dry_run: edit-config into candidate + :validate, then discard-changes.
  No diff text (NETCONF has no standard diff), but validation evidence.
- snapshot/rollback: get-config running (full XML) / edit-config replace.

STATUS: verb bodies are `pragma: no cover - live device` until a lab
platform exposes NETCONF with model-based artifacts (SR Linux and cEOS can;
the current compilers emit CLI text, so the CLI drivers carry delivery for
now). The capability matrix and format gating are live and tested.
"""

from __future__ import annotations

import hashlib
from typing import Any, ClassVar

from ..driver import BaseDriver, register
from ..exceptions import ChangeNotFound, ExecutorError
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

CONFIRM_TIMEOUT_SECONDS = 600


@register
class NetconfYangDriver(BaseDriver):
    name: ClassVar[str] = "netconf"
    capabilities: ClassVar[CapabilityMatrix] = CapabilityMatrix(
        transactional=Transactionality.PER_SESSION,
        supports_dry_run=True,
        supports_confirm=True,
        supports_snapshot=True,
        atomicity=Atomicity.PER_DEVICE,
        protocols=[Protocol.NETCONF],
    )

    def _manager(self):  # pragma: no cover - requires ncclient + live device
        try:
            from ncclient import manager
        except ImportError as exc:
            raise ExecutorError(
                "ncclient not installed; use `pip install autonetops-executor[netconf]`"
            ) from exc
        return manager.connect(
            host=self.connection["host"],
            port=self.connection.get("port", 830),
            username=self.connection.get("username", "admin"),
            password=self.connection.get("password", "admin"),
            hostkey_verify=False,
            timeout=60,
        )

    @staticmethod
    def _payload_xml(artifact: ArtifactPayload) -> str:
        if artifact.content.lstrip().startswith("<"):
            return artifact.content
        raise ExecutorError(
            "netconf driver requires an ietf-xml artifact; got non-XML content "
            "(CLI-text artifacts must ride a CLI driver - check the plan's "
            "content_format)"
        )

    def get_facts(self) -> FactsResult:  # pragma: no cover - live device
        started = utc_now_iso()
        with self._manager() as mgr:
            capabilities = list(mgr.server_capabilities)
        return FactsResult(
            evidence=self._evidence("get_facts", started, success=True),
            facts={"server_capabilities": len(capabilities)},
        )

    def snapshot(self) -> Snapshot:  # pragma: no cover - live device
        self._require("supports_snapshot")
        started = utc_now_iso()
        with self._manager() as mgr:
            config = str(mgr.get_config(source="running"))
        checksum = hashlib.sha256(config.encode()).hexdigest()
        self._snapshots = getattr(self, "_snapshots", {})
        self._snapshots[f"snap-{checksum[:12]}"] = config
        return Snapshot(
            evidence=self._evidence("snapshot", started, success=True),
            snapshot_id=f"snap-{checksum[:12]}",
            checksum=checksum,
        )

    def dry_run(self, artifact: ArtifactPayload) -> DiffResult:  # pragma: no cover - live device
        self._require("supports_dry_run")
        started = utc_now_iso()
        payload = self._payload_xml(artifact)
        with self._manager() as mgr:
            with mgr.locked(target="candidate"):
                mgr.discard_changes()
                mgr.edit_config(target="candidate", config=payload)
                mgr.validate(source="candidate")
                mgr.discard_changes()
        return DiffResult(
            evidence=self._evidence("dry_run", started, success=True,
                                    artifact_checksum=artifact.checksum,
                                    validated=True),
            changed=True,  # NETCONF has no standard diff; validation only
            diff="(netconf: candidate validated; no standard diff available)",
        )

    def apply(self, artifact: ArtifactPayload) -> PendingChange:  # pragma: no cover - live device
        started = utc_now_iso()
        payload = self._payload_xml(artifact)
        change_id = f"chg-{artifact.checksum[:12]}"
        with self._manager() as mgr:
            with mgr.locked(target="candidate"):
                mgr.discard_changes()
                mgr.edit_config(target="candidate", config=payload)
                mgr.commit(confirmed=True, timeout=str(CONFIRM_TIMEOUT_SECONDS))
        return PendingChange(
            evidence=self._evidence("apply", started, success=True,
                                    artifact_checksum=artifact.checksum,
                                    commit="confirmed-commit"),
            change_id=change_id,
            rollback_strategy="commit_confirmed",
            confirm_deadline_seconds=CONFIRM_TIMEOUT_SECONDS,
        )

    def confirm(self, change_id: str) -> Evidence:  # pragma: no cover - live device
        self._require("supports_confirm")
        started = utc_now_iso()
        with self._manager() as mgr:
            mgr.commit()  # a plain commit inside the window makes it permanent
        return self._evidence("confirm", started, success=True, change_id=change_id)

    def rollback(self, reference: str) -> Evidence:  # pragma: no cover - live device
        started = utc_now_iso()
        if reference.startswith("chg-"):
            # inside the confirm window doing nothing reverts; cancel eagerly
            with self._manager() as mgr:
                mgr.cancel_commit()
            return self._evidence("rollback", started, success=True,
                                  restored="change", via="cancel-commit")
        snapshots = getattr(self, "_snapshots", {})
        if reference not in snapshots:
            raise ChangeNotFound(f"unknown rollback reference {reference!r}")
        with self._manager() as mgr:
            with mgr.locked(target="candidate"):
                mgr.discard_changes()
                mgr.edit_config(target="candidate", config=snapshots[reference],
                                default_operation="replace")
                mgr.commit()
        return self._evidence("rollback", started, success=True, restored="snapshot")
