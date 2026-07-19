"""Assemble a Plan from a ChangeSet + policies.

Two modes (ADR-0016):

- legacy/builtin (``profile=None``): the module-level constant maps below
  apply, with kind-based fallbacks for unknown platforms — bit-identical to
  the pre-profile engine.
- profile mode: every binding comes from the resolved intent profile; in a
  strict pack an unbound platform or artifact definition is a
  :class:`PlanBuildError`, never a guess.
"""

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
    PreApproval,
    RollbackSpec,
    Stage,
    Step,
    StepTarget,
)
from .policies import CanaryStrategy, DEFAULT_DELIVERY_PREFERENCES, select_protocol
from .profile import PlatformBinding, ResolvedProfile

# Interim mapping until drivers declare capabilities in SoT (ADR-0011);
# vendor transactional semantics themselves live in executor/drivers/.
# packs/baseline/profile.yaml mirrors these (pinned equal by test_profile).
PLATFORM_ROLLBACK: dict[str, str] = {
    "junos": "commit_confirmed",
    "iosxr": "commit_confirm",
    "eos": "checkpoint",
    "arista_eos": "snapshot_revert",  # eos driver: checkpoint + configure replace
    "srlinux": "snapshot_revert",  # srlinux driver: checkpoint revert
    "nokia_srlinux": "snapshot_revert",  # srlinux driver: checkpoint revert
}

# Platform (as named in the SoT) -> executor driver registry name. Platforms
# not listed have no driver yet; the runner must refuse those steps loudly.
PLATFORM_DRIVERS: dict[str, str] = {
    "nokia_srlinux": "srlinux",
    "srlinux": "srlinux",
    "arista_eos": "eos",
    "eos": "eos",
}

DEFAULT_ABORT_CRITERIA = [
    "validator gate fails on any canary stage",
    "any step rollback is triggered",
    "manual abort via ibnctl",
]


class PlanBuildError(Exception):
    """A strict profile refused to guess. Carries every unbound platform /
    definition found, so the pack author fixes one run, not ten."""

    def __init__(self, violations: list[str]):
        self.violations = violations
        lines = "\n".join(f"  - {v}" for v in violations)
        super().__init__(f"cannot build plan under strict profile:\n{lines}")


def _binding_for(
    item: ChangeItem, profile: ResolvedProfile | None
) -> PlatformBinding | None:
    """The profile's platform binding for an item. Strict packs match the
    SoT spelling exactly; builtin/legacy also accept a lowercase match
    (their keys are lowercase, preserving the historic behavior)."""
    if profile is None or not item.platform:
        return None
    binding = profile.platforms.get(item.platform)
    if binding is None and not profile.strict:
        binding = profile.platforms.get(item.platform.lower())
    return binding


def _rollback_for(item: ChangeItem, profile: ResolvedProfile | None = None) -> str:
    if item.kind == ControlPointKind.CONTROLLER:
        return "controller_revision"
    binding = _binding_for(item, profile)
    if binding is not None and binding.rollback:
        return binding.rollback
    if profile is None or not profile.strict:
        strategy = PLATFORM_ROLLBACK.get((item.platform or "").lower())
        if strategy:
            return strategy
    # No transaction support known: snapshot-revert if the driver can, else manual.
    return "snapshot_revert" if item.kind == ControlPointKind.API else "manual"


def _driver_for(item: ChangeItem, profile: ResolvedProfile | None = None) -> str | None:
    binding = _binding_for(item, profile)
    if binding is not None and binding.driver:
        return binding.driver
    return PLATFORM_DRIVERS.get(
        (item.platform or "").lower(), (item.platform or "").lower() or None
    )


def _step_for(
    item: ChangeItem,
    delivery_prefs: dict,
    profile: ResolvedProfile | None = None,
    confirm_timeout_minutes: int = 10,
) -> Step:
    assert item.checksum_after is not None  # removals never become steps
    return Step(
        target=StepTarget(
            control_point=item.target,
            kind=item.kind,
            affected_devices=item.effective_devices,
        ),
        driver=_driver_for(item, profile),
        protocol=select_protocol(item.platform, delivery_prefs, item.content_format),
        platform=item.platform,
        artifact_definition=item.definition,
        content_format=item.content_format,
        checksum_before=item.checksum_before,
        checksum_after=item.checksum_after,
        storage_id=item.storage_id_after,
        rollback=RollbackSpec(
            strategy=_rollback_for(item, profile),
            confirm_timeout_minutes=confirm_timeout_minutes,
        ),
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


def _strict_violations(changes: ChangeSet, profile: ResolvedProfile) -> list[str]:
    """A strict pack never guesses: every platform and artifact definition
    in the diff must be bound (controllers excepted — their rollback is
    kind-derived and their driver is the control-point integration)."""
    violations: list[str] = []
    unbound_platforms: set[str] = set()
    unbound_definitions: set[str] = set()
    for item in changes.deployable:
        if item.definition not in profile.definition_formats:
            unbound_definitions.add(item.definition)
        if item.kind == ControlPointKind.CONTROLLER:
            continue
        if not item.platform:
            violations.append(
                f"control point {item.target!r} carries no platform; a strict "
                f"profile cannot choose a driver for it"
            )
        elif profile.platforms.get(item.platform) is None:
            unbound_platforms.add(item.platform)
    violations.extend(
        f"platform {platform!r} is not bound in the profile's platforms section"
        for platform in sorted(unbound_platforms)
    )
    violations.extend(
        f"artifact definition {definition!r} is not bound in the profile's "
        f"artifacts section"
        for definition in sorted(unbound_definitions)
    )
    return violations


def _fallback_assumptions(changes: ChangeSet, profile: ResolvedProfile) -> list[str]:
    """Non-strict modes keep the historic guesses — recorded, never silent."""
    assumptions: list[str] = []
    for platform in sorted(
        {
            i.platform
            for i in changes.deployable
            if i.platform and i.kind != ControlPointKind.CONTROLLER
        }
    ):
        probe = ChangeItem(target="_", definition="_", platform=platform)
        if _binding_for(probe, profile) is None:
            if PLATFORM_DRIVERS.get(platform.lower()) is None:
                assumptions.append(
                    f"platform {platform!r} unbound: driver guessed as "
                    f"{platform.lower()!r}"
                )
            if PLATFORM_ROLLBACK.get(platform.lower()) is None:
                assumptions.append(
                    f"platform {platform!r} unbound: kind-based rollback in effect"
                )
    for definition in sorted(
        {
            i.definition
            for i in changes.deployable
            if i.definition not in profile.definition_formats
        }
    ):
        assumptions.append(
            f"artifact definition {definition!r} unbound: content format taken "
            f"from the artifact listing"
        )
    return assumptions


def build_plan(
    changes: ChangeSet,
    strategy: CanaryStrategy,
    delivery_prefs: dict | None = None,
    pre_approved: PreApproval | None = None,
    *,
    profile: ResolvedProfile | None = None,
) -> Plan:
    if profile is not None:
        delivery_prefs = profile.delivery_preferences
        thresholds = profile.thresholds
        confirm_timeout = profile.rollback_defaults.confirm_timeout_minutes
        abort_criteria = list(profile.abort_criteria)
        if profile.strict:
            violations = _strict_violations(changes, profile)
            if violations:
                raise PlanBuildError(violations)
            assumptions = list(profile.load_assumptions)
        else:
            assumptions = list(profile.load_assumptions) + _fallback_assumptions(
                changes, profile
            )
        blast = compute_blast_radius(changes, thresholds)
        approvals_required = sorted(
            set(strategy.requires_approvals)
            | set(profile.floors.for_class(blast.classification))
        )
        profile_ref = profile.ref
    else:
        delivery_prefs = delivery_prefs or DEFAULT_DELIVERY_PREFERENCES
        confirm_timeout = 10
        abort_criteria = list(DEFAULT_ABORT_CRITERIA)
        assumptions = []
        blast = compute_blast_radius(changes)
        approvals_required = sorted(set(strategy.requires_approvals))
        profile_ref = None

    source = PlanSource(
        base_branch=changes.base_branch, candidate_branch=changes.candidate_branch
    )
    stages = [
        Stage(
            name=name,
            steps=[
                _step_for(i, delivery_prefs, profile, confirm_timeout) for i in items
            ],
            gate=Gate(kind=gate, soak_minutes=soak),  # type: ignore[arg-type]
        )
        for name, items, soak, gate in _partition(changes.deployable, strategy)
    ]

    return Plan(
        # pre_approved and profile are metadata, not rollout content: the id
        # hashes only source + stages, so the same diff keeps the same id
        id=Plan.deterministic_id(source, stages),
        source=source,
        blast_radius=blast,
        policy_evaluation=PolicyEvaluation(
            canary_strategy=strategy.name,
            pre_approved=pre_approved,
            profile=profile_ref,
            approvals_required=approvals_required,
            assumptions=assumptions,
        ),
        stages=stages,
        removed_targets=sorted({i.target for i in changes.removed}),
        abort_criteria=abort_criteria,
    )
