"""Assemble a Plan from a ChangeSet + policies."""

from __future__ import annotations

from .blast_radius import compute_blast_radius
from .models import (
    ChangeItem,
    ChangeSet,
    Gate,
    Plan,
    PlanSource,
    PolicyEvaluation,
    RollbackSpec,
    Stage,
    Step,
)
from .policies import CanaryStrategy

# Vendor transactional semantics live in the deployer; the planner only
# selects the strategy name (see deployer/rollback and ADR-0005).
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


def _step_for(item: ChangeItem) -> Step:
    platform = (item.platform or "").lower()
    strategy = PLATFORM_ROLLBACK.get(platform, "manual")
    assert item.checksum_after is not None  # removals never become steps
    return Step(
        device=item.device,
        platform=item.platform,
        artifact_definition=item.definition,
        checksum_before=item.checksum_before,
        checksum_after=item.checksum_after,
        storage_id=item.storage_id_after,
        rollback=RollbackSpec(strategy=strategy),  # type: ignore[arg-type]
    )


def _partition(items: list[ChangeItem], strategy: CanaryStrategy) -> list[tuple[str, list[ChangeItem], int, str]]:
    """Split deployable items into (stage_name, items, soak, gate) groups."""
    by_device: dict[str, list[ChangeItem]] = {}
    for item in items:
        by_device.setdefault(item.device, []).append(item)
    remaining = sorted(by_device.keys())

    groups: list[tuple[str, list[ChangeItem], int, str]] = []
    for index, stage in enumerate(strategy.stages, start=1):
        if not remaining:
            break
        if stage.select == "one_device":
            picked = [remaining[0]]
        elif stage.select == "one_per_role":
            seen_roles: set[str | None] = set()
            picked = []
            for device in remaining:
                role = by_device[device][0].role
                if role not in seen_roles:
                    seen_roles.add(role)
                    picked.append(device)
        elif stage.select == "remainder":
            picked = list(remaining)
        else:
            raise ValueError(f"unknown stage selector {stage.select!r}")
        remaining = [d for d in remaining if d not in picked]
        stage_items = [i for d in picked for i in by_device[d]]
        groups.append((f"stage-{index}-{stage.select}", stage_items, stage.soak_minutes, stage.gate))

    if remaining:
        # Strategy without a trailing "remainder" stage — never drop devices silently.
        stage_items = [i for d in remaining for i in by_device[d]]
        groups.append((f"stage-{len(groups) + 1}-remainder", stage_items, 0, "validator.expectations_pass"))
    return groups


def build_plan(changes: ChangeSet, strategy: CanaryStrategy) -> Plan:
    blast = compute_blast_radius(changes)
    source = PlanSource(
        base_branch=changes.base_branch, candidate_branch=changes.candidate_branch
    )

    stages = [
        Stage(
            name=name,
            steps=[_step_for(i) for i in items],
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
        removed_devices=sorted({i.device for i in changes.removed}),
        abort_criteria=list(DEFAULT_ABORT_CRITERIA),
    )
