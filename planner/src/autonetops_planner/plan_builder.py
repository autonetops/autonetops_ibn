"""Assemble a Plan from a ChangeSet + policies."""

from __future__ import annotations

from .blast_radius import compute_blast_radius
from .models import (
    ChangeItem,
    ChangeSet,
    ControlPointKind,
    Gate,
    Plan,
    PlanSource,
    PolicyEvaluation,
    RollbackSpec,
    Stage,
    Step,
    StepTarget,
)
from .policies import CanaryStrategy, DEFAULT_DELIVERY_PREFERENCES, select_protocol

# Interim mapping until drivers declare capabilities in SoT (ADR-0011);
# vendor transactional semantics themselves live in executor/drivers/.
PLATFORM_ROLLBACK: dict[str, str] = {
    "junos": "commit_confirmed",
    "iosxr": "commit_confirm",
    "eos": "checkpoint",
}

DEFAULT_ABORT_CRITERIA = [
    "validator gate fails on any canary stage",
    "any step rollback is triggered",
    "manual abort via ibnctl",
]


def _rollback_for(item: ChangeItem) -> str:
    if item.kind == ControlPointKind.CONTROLLER:
        return "controller_revision"
    strategy = PLATFORM_ROLLBACK.get((item.platform or "").lower())
    if strategy:
        return strategy
    # No transaction support known: snapshot-revert if the driver can, else manual.
    return "snapshot_revert" if item.kind == ControlPointKind.API else "manual"


def _step_for(item: ChangeItem, delivery_prefs: dict) -> Step:
    assert item.checksum_after is not None  # removals never become steps
    return Step(
        target=StepTarget(
            control_point=item.target,
            kind=item.kind,
            affected_devices=item.effective_devices,
        ),
        driver=(item.platform or "").lower() or None,
        protocol=select_protocol(item.platform, delivery_prefs),
        platform=item.platform,
        artifact_definition=item.definition,
        checksum_before=item.checksum_before,
        checksum_after=item.checksum_after,
        storage_id=item.storage_id_after,
        rollback=RollbackSpec(strategy=_rollback_for(item)),
    )


def _partition(
    items: list[ChangeItem], strategy: CanaryStrategy
) -> list[tuple[str, list[ChangeItem], int, str]]:
    """Split deployable items into (stage_name, items, soak, gate) groups.

    Selectors operate on control points. A controller target is one selectable
    unit: canarying *within* its domain requires intent-scope slicing in the
    compiler, not device picking here (ADR-0011).
    """
    by_target: dict[str, list[ChangeItem]] = {}
    for item in items:
        by_target.setdefault(item.target, []).append(item)
    remaining = sorted(by_target.keys())

    groups: list[tuple[str, list[ChangeItem], int, str]] = []
    for index, stage in enumerate(strategy.stages, start=1):
        if not remaining:
            break
        if stage.select == "one_target":
            picked = [remaining[0]]
        elif stage.select == "one_per_role":
            seen_roles: set[str | None] = set()
            picked = []
            for target in remaining:
                role = by_target[target][0].role
                if role not in seen_roles:
                    seen_roles.add(role)
                    picked.append(target)
        elif stage.select == "remainder":
            picked = list(remaining)
        else:
            raise ValueError(f"unknown stage selector {stage.select!r}")
        remaining = [t for t in remaining if t not in picked]
        stage_items = [i for t in picked for i in by_target[t]]
        groups.append(
            (f"stage-{index}-{stage.select}", stage_items, stage.soak_minutes, stage.gate)
        )

    if remaining:
        # Strategy without a trailing "remainder" stage — never drop targets silently.
        stage_items = [i for t in remaining for i in by_target[t]]
        groups.append(
            (f"stage-{len(groups) + 1}-remainder", stage_items, 0, "validator.expectations_pass")
        )
    return groups


def build_plan(
    changes: ChangeSet,
    strategy: CanaryStrategy,
    delivery_prefs: dict | None = None,
) -> Plan:
    delivery_prefs = delivery_prefs or DEFAULT_DELIVERY_PREFERENCES
    blast = compute_blast_radius(changes)
    source = PlanSource(
        base_branch=changes.base_branch, candidate_branch=changes.candidate_branch
    )

    stages = [
        Stage(
            name=name,
            steps=[_step_for(i, delivery_prefs) for i in items],
            gate=Gate(kind=gate, soak_minutes=soak),  # type: ignore[arg-type]
        )
        for name, items, soak, gate in _partition(changes.deployable, strategy)
    ]

    return Plan(
        id=Plan.deterministic_id(source, stages),
        source=source,
        blast_radius=blast,
        policy_evaluation=PolicyEvaluation(canary_strategy=strategy.name),
        stages=stages,
        removed_targets=sorted({i.target for i in changes.removed}),
        abort_criteria=list(DEFAULT_ABORT_CRITERIA),
    )
