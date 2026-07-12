"""Step runner - the one verb sequence every consumer shares.

snapshot -> dry_run -> apply -> confirm, with rollback-on-failure. ibnctl
(manual, break-glass) and the orchestrator flows both call run_step(), so
the sequence can never drift between them. The ADR-0005 boundary holds:
this module performs device-level operations for ONE step; which step runs
when - stages, gates, soak, windows - stays with the caller.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Callable

from .driver import available_drivers, get_driver_class
from .models import ArtifactPayload

EvidenceSink = Callable[[Any], None]


@dataclass
class StepOutcome:
    """What happened to one step. ``ok`` covers every outcome where the
    network is in a state the plan allows; a skip is NOT ok - nothing was
    attempted, and silence would read as success."""

    target: str
    status: str  # applied | converged | checked | skipped | failed | rolled_back
    detail: str = ""
    diff: str = ""
    change_id: str | None = None
    snapshot_id: str | None = None

    @property
    def ok(self) -> bool:
        return self.status in ("applied", "converged", "checked")


def verify_checksum(content: str, expected: str) -> bool:
    digest = hashlib.md5 if len(expected) == 32 else hashlib.sha256
    return digest(content.encode()).hexdigest() == expected


def run_step(
    step: Any,
    connection: dict[str, Any],
    content: str,
    *,
    check: bool = False,
    emit: EvidenceSink | None = None,
) -> StepOutcome:
    """Drive one Plan step through the full verb sequence.

    ``step`` is a planner ``Step`` (duck-typed to avoid a package cycle);
    ``emit`` receives every Evidence record as it is produced.
    """
    emit = emit or (lambda record: None)
    target = step.target.control_point

    if step.driver not in available_drivers():
        emit({"operation": "skip", "target": target,
              "reason": f"no driver {step.driver!r}", "success": False})
        return StepOutcome(
            target, "skipped",
            f"no executor driver {step.driver!r} for platform {step.platform!r}",
        )

    if not verify_checksum(content, step.checksum_after):
        return StepOutcome(target, "failed", "content checksum does not match the plan")

    artifact = ArtifactPayload(
        definition=step.artifact_definition,
        checksum=step.checksum_after,
        content=content,
    )
    driver = get_driver_class(step.driver)(target, connection)

    snap = driver.snapshot()
    emit(snap.evidence)

    diff_text = ""
    if driver.capabilities.supports_dry_run:
        diff = driver.dry_run(artifact)
        emit(diff.evidence)
        if not diff.changed:
            return StepOutcome(target, "converged", "no diff - already converged",
                               snapshot_id=snap.snapshot_id)
        diff_text = diff.diff
        if check:
            return StepOutcome(target, "checked", diff=diff_text,
                               snapshot_id=snap.snapshot_id)
    elif check:
        return StepOutcome(target, "checked",
                           "driver has no dry_run; nothing verified",
                           snapshot_id=snap.snapshot_id)

    try:
        pending = driver.apply(artifact)
        emit(pending.evidence)
        if pending.confirm_deadline_seconds:
            confirmation = driver.confirm(pending.change_id)
            emit(confirmation)
        return StepOutcome(target, "applied", diff=diff_text,
                           change_id=pending.change_id,
                           snapshot_id=snap.snapshot_id)
    except Exception as exc:  # noqa: BLE001 - roll back, report, let caller abort
        rollback = driver.rollback(snap.snapshot_id)
        emit(rollback)
        return StepOutcome(target, "rolled_back", str(exc),
                           snapshot_id=snap.snapshot_id)
