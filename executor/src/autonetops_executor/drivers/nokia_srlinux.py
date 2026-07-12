"""Nokia SR Linux driver — integration-tested against containerlab (ADR-0011).

Delivery rides the SSH CLI (transports/srl_ssh.py): rendered artifacts are
``set`` lines, and SR Linux's private candidate gives real transaction
semantics over that format:

- dry_run: source the lines into a private candidate, ``diff``, discard.
  Declared supported - it costs nothing and it is the strongest pre-apply
  evidence a lab driver can produce.
- apply:   checkpoint first (``pre-<change_id>``), then source + commit save.
- rollback: ``tools system configuration checkpoint <name> revert``; accepts
  either a snapshot_id (checkpoint taken by snapshot()) or a change_id
  (checkpoint taken by apply()).
- confirm: still unsupported; SR Linux has commit-confirmed semantics, but
  wiring the timer through the orchestrator is future work. The capability
  matrix says so honestly.

gNMI stays the preferred *telemetry* path (the observability pipeline
subscribes on 57400); pushing full CLI-text artifacts over gNMI Set is not
possible, which is why config delivery declares CLI first (ADR-0012).
"""

from __future__ import annotations

import hashlib
from typing import ClassVar

from ..driver import BaseDriver, register
from ..exceptions import ChangeNotFound
from ..facts import parse_bgp_neighbor_states
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
from ..transports.srl_ssh import SrlSsh


@register
class NokiaSrlinuxDriver(BaseDriver):
    name: ClassVar[str] = "srlinux"
    capabilities: ClassVar[CapabilityMatrix] = CapabilityMatrix(
        transactional=Transactionality.PER_SESSION,
        supports_dry_run=True,
        supports_confirm=False,
        supports_snapshot=True,
        atomicity=Atomicity.PER_DEVICE,
        protocols=[Protocol.CLI, Protocol.GNMI],
    )

    def _session(self) -> SrlSsh:  # pragma: no cover - live device
        return SrlSsh(self.connection)

    @staticmethod
    def _lines(artifact: ArtifactPayload) -> list[str]:
        return [
            line for line in artifact.content.splitlines()
            if line.strip() and not line.startswith("#")
        ]

    def get_facts(self) -> FactsResult:  # pragma: no cover - live device
        started = utc_now_iso()
        with self._session() as ssh:
            version = ssh.run("info from state /system information version")
            sessions = ssh.run(
                "show network-instance default protocols bgp neighbor"
            )
        return FactsResult(
            evidence=self._evidence("get_facts", started, success=True,
                                    protocol=Protocol.CLI),
            facts={"version_raw": version.strip()[:200],
                   "bgp_neighbors": parse_bgp_neighbor_states(sessions)},
        )

    def snapshot(self) -> Snapshot:  # pragma: no cover - live device
        self._require("supports_snapshot")
        started = utc_now_iso()
        with self._session() as ssh:
            config = ssh.running_config_flat()
            checksum = hashlib.sha256(config.encode()).hexdigest()
            name = f"ibn-{checksum[:12]}"
            ssh.generate_checkpoint(name)
        return Snapshot(
            evidence=self._evidence("snapshot", started, success=True,
                                    protocol=Protocol.CLI, checkpoint=name),
            snapshot_id=name,
            checksum=checksum,
        )

    def dry_run(self, artifact: ArtifactPayload) -> DiffResult:  # pragma: no cover - live device
        self._require("supports_dry_run")
        started = utc_now_iso()
        with self._session() as ssh:
            ssh.enter_candidate()
            ssh.source_lines(self._lines(artifact))
            diff = ssh.diff()
            ssh.discard()
        changed = bool(diff.strip())
        return DiffResult(
            evidence=self._evidence("dry_run", started, success=True,
                                    protocol=Protocol.CLI,
                                    artifact_checksum=artifact.checksum),
            changed=changed,
            diff=diff,
        )

    def apply(self, artifact: ArtifactPayload) -> PendingChange:  # pragma: no cover - live device
        started = utc_now_iso()
        change_id = f"chg-{artifact.checksum[:12]}"
        with self._session() as ssh:
            ssh.generate_checkpoint(f"pre-{change_id}")
            ssh.enter_candidate()
            ssh.source_lines(self._lines(artifact))
            commit_output = ssh.commit_save()
        return PendingChange(
            evidence=self._evidence(
                "apply", started, success=True, protocol=Protocol.CLI,
                artifact_checksum=artifact.checksum,
                commit=commit_output.strip()[-200:],
            ),
            change_id=change_id,
            rollback_strategy="snapshot_revert",
            confirm_deadline_seconds=None,  # no confirm semantics wired yet
        )

    def confirm(self, change_id: str) -> Evidence:
        self._require("supports_confirm")  # always raises: declared unsupported
        raise AssertionError("unreachable")

    def rollback(self, reference: str) -> Evidence:  # pragma: no cover - live device
        started = utc_now_iso()
        if reference.startswith("chg-"):
            checkpoint, restored = f"pre-{reference}", "change"
        elif reference.startswith("ibn-") or reference.startswith("pre-"):
            checkpoint, restored = reference, "snapshot"
        else:
            raise ChangeNotFound(f"unknown rollback reference {reference!r}")
        with self._session() as ssh:
            ssh.revert_checkpoint(checkpoint)
        return self._evidence("rollback", started, success=True,
                              protocol=Protocol.CLI,
                              restored=restored, checkpoint=checkpoint)
