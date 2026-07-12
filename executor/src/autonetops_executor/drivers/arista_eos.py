"""Arista EOS driver — SSH CLI via netmiko (ADR-0011).

EOS gives real transaction primitives over the CLI:

- dry_run: load the artifact into a named *config session* and read
  ``show session-config diffs``, then abort the session. Nothing touches
  the running config.
- snapshot/rollback: ``configure checkpoint save <name>`` and
  ``configure replace checkpoint:<name>`` - a true full-state revert.
- apply: checkpoint first (``pre-<change_id>``), then merge the artifact
  and ``write memory``.
- confirm: EOS sessions support ``commit timer`` (auto-revert), but wiring
  the timer through the orchestrator is future work; declared unsupported.

eAPI/gNMI are better transports for structured pushes; the rendered
artifact is CLI text, so CLI leads the declared protocol order (ADR-0012).
"""

from __future__ import annotations

import hashlib
import re
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

ERROR_PATTERN = re.compile(r"^% |% Invalid|% Error", re.MULTILINE)


@register
class AristaEosDriver(BaseDriver):
    name: ClassVar[str] = "eos"
    capabilities: ClassVar[CapabilityMatrix] = CapabilityMatrix(
        transactional=Transactionality.PER_SESSION,
        supports_dry_run=True,
        supports_confirm=False,
        supports_snapshot=True,
        atomicity=Atomicity.PER_DEVICE,
        protocols=[Protocol.CLI, Protocol.EAPI, Protocol.GNMI],
    )

    def _connect(self) -> Any:  # pragma: no cover - live device
        try:
            from netmiko import ConnectHandler
        except ImportError as exc:
            raise ExecutorError(
                "netmiko not installed; use `pip install autonetops-executor[cli]`"
            ) from exc
        return ConnectHandler(
            device_type="arista_eos",
            host=self.connection["host"],
            username=self.connection.get("username", "admin"),
            password=self.connection.get("password", "admin"),
            secret=self.connection.get("password", "admin"),
            port=self.connection.get("port", 22),
        )

    @staticmethod
    def _lines(artifact: ArtifactPayload) -> list[str]:
        return [
            line for line in artifact.content.splitlines()
            if line.strip() and not line.lstrip().startswith(("!", "#"))
        ]

    @staticmethod
    def _check(output: str, action: str) -> None:
        if ERROR_PATTERN.search(output):
            raise ExecutorError(f"{action} rejected:\n{output.strip()[-800:]}")

    def get_facts(self) -> FactsResult:  # pragma: no cover - live device
        started = utc_now_iso()
        conn = self._connect()
        try:
            conn.enable()
            version = conn.send_command("show version")
        finally:
            conn.disconnect()
        return FactsResult(
            evidence=self._evidence("get_facts", started, success=True,
                                    protocol=Protocol.CLI),
            facts={"version_raw": version.strip()[:400]},
        )

    def snapshot(self) -> Snapshot:  # pragma: no cover - live device
        self._require("supports_snapshot")
        started = utc_now_iso()
        conn = self._connect()
        try:
            conn.enable()
            config = conn.send_command("show running-config", read_timeout=60)
            checksum = hashlib.sha256(config.encode()).hexdigest()
            name = f"ibn-{checksum[:12]}"
            out = conn.send_command_timing(f"configure checkpoint save {name}")
            self._check(out, "checkpoint")
        finally:
            conn.disconnect()
        return Snapshot(
            evidence=self._evidence("snapshot", started, success=True,
                                    protocol=Protocol.CLI, checkpoint=name),
            snapshot_id=name,
            checksum=checksum,
        )

    def dry_run(self, artifact: ArtifactPayload) -> DiffResult:  # pragma: no cover - live device
        self._require("supports_dry_run")
        started = utc_now_iso()
        session = f"ibn-dry-{artifact.checksum[:8]}"
        conn = self._connect()
        try:
            conn.enable()
            output = conn.send_config_set(
                self._lines(artifact),
                config_mode_command=f"configure session {session}",
                cmd_verify=False,
            )
            self._check(output, "dry_run")
            diff = conn.send_command(f"show session-config named {session} diffs",
                                     read_timeout=60)
            conn.send_command_timing(f"configure session {session}")
            conn.send_command_timing("abort")
        finally:
            conn.disconnect()
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
        conn = self._connect()
        try:
            conn.enable()
            out = conn.send_command_timing(f"configure checkpoint save pre-{change_id}")
            self._check(out, "checkpoint")
            output = conn.send_config_set(self._lines(artifact), cmd_verify=False)
            self._check(output, "apply")
            conn.send_command("write memory", read_timeout=60)
        finally:
            conn.disconnect()
        return PendingChange(
            evidence=self._evidence("apply", started, success=True,
                                    protocol=Protocol.CLI,
                                    artifact_checksum=artifact.checksum),
            change_id=change_id,
            rollback_strategy="snapshot_revert",
            confirm_deadline_seconds=None,
        )

    def confirm(self, change_id: str) -> Evidence:
        self._require("supports_confirm")  # always raises: declared unsupported
        raise AssertionError("unreachable")

    def rollback(self, reference: str) -> Evidence:  # pragma: no cover - live device
        started = utc_now_iso()
        if reference.startswith("chg-"):
            checkpoint, restored = f"pre-{reference}", "change"
        elif reference.startswith(("ibn-", "pre-")):
            checkpoint, restored = reference, "snapshot"
        else:
            raise ChangeNotFound(f"unknown rollback reference {reference!r}")
        conn = self._connect()
        try:
            conn.enable()
            out = conn.send_command(f"configure replace checkpoint:{checkpoint}",
                                    read_timeout=120)
            self._check(out, "rollback")
            conn.send_command("write memory", read_timeout=60)
        finally:
            conn.disconnect()
        return self._evidence("rollback", started, success=True,
                              protocol=Protocol.CLI,
                              restored=restored, checkpoint=checkpoint)
