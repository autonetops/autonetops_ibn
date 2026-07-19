"""Pre-approval glue (ADR-0014): rate limit at plan time, re-verify at dispatch.

The planner owns the classifier (autonetops_planner.change_classes); this
module owns the orchestrator-side duties around it:

- plan time: enforce the per-class rate limit by scanning the plan bundles
  already on disk — stateless, inspectable, no counter service.
- dispatch time: re-derive the classification from the frozen bundle bytes
  (content_base/ + content/, integrity-anchored by the steps' checksums) and
  tighten the decision. decision.yaml carries no integrity protection of its
  own, so an empty approvals list is honored only when the bytes still prove
  the claimed class under the CURRENT policy — which also makes the per-class
  kill switch (enabled: false) effective for already-planned bundles.

ADR-0016 extends the same discipline to the whole profile: the frozen
bundle is testimony, the CURRENT pack is judge, and verdicts only tighten —
approval floors union in, and the blast classification is re-derived under
the current thresholds with the pinned class as a floor, never a ceiling.
"""

from __future__ import annotations

import datetime
import hashlib
from pathlib import Path

import yaml

from autonetops_planner.change_classes import classify_changes
from autonetops_planner.models import BlastRadiusClass, ChangeItem, ChangeSet
from autonetops_planner.profile import ResolvedProfile

from .strategy import Decision

# The name is deliberately un-satisfiable by accident: it surfaces in the
# "missing approvals: ..." abort when a pre-approval claim cannot be checked.
UNVERIFIABLE = "unverifiable-pre-approval"

BLAST_ORDER = {
    BlastRadiusClass.LOW: 0,
    BlastRadiusClass.MODERATE: 1,
    BlastRadiusClass.HIGH: 2,
}


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def recent_pre_approved(
    plans_dir: Path,
    class_name: str,
    now: datetime.datetime,
    window: datetime.timedelta = datetime.timedelta(hours=1),
) -> int:
    """How many plans this class auto-approved recently (rate-limit input)."""
    count = 0
    for plan_file in plans_dir.glob("*/plan.yaml"):
        try:
            doc = yaml.safe_load(plan_file.read_text()) or {}
        except Exception:  # noqa: BLE001 - a broken bundle never blocks counting
            continue
        pre = (doc.get("policy_evaluation") or {}).get("pre_approved") or {}
        if pre.get("class") != class_name:
            continue
        created = doc.get("created_at")
        if not created:
            continue
        try:
            stamp = datetime.datetime.fromisoformat(created)
        except ValueError:
            continue
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=datetime.timezone.utc)
        if datetime.timedelta(0) <= now - stamp <= window:
            count += 1
    return count


def plan_changeset(plan) -> ChangeSet:
    """Reconstruct the ChangeSet a plan's stages encode, for re-classification.
    removed_targets come back as removal items so classification refuses them
    exactly as it would have at plan time."""
    items = [
        ChangeItem(
            target=step.target.control_point,
            kind=step.target.kind,
            definition=step.artifact_definition,
            checksum_before=step.checksum_before,
            checksum_after=step.checksum_after,
            content_format=step.content_format,
            affected_devices=step.target.affected_devices,
        )
        for stage in plan.stages
        for step in stage.steps
    ]
    items += [
        ChangeItem(target=target, definition="removed",
                   checksum_before="gone", checksum_after=None)
        for target in plan.removed_targets
    ]
    return ChangeSet(
        base_branch=plan.source.base_branch,
        candidate_branch=plan.source.candidate_branch,
        items=items,
    )


def _frozen_content_for(plan_dir: Path):
    def content_for(item: ChangeItem):
        name = f"{item.target}__{item.definition}.cfg"
        base_path = plan_dir / "content_base" / name
        after_path = plan_dir / "content" / name
        if not base_path.exists() or not after_path.exists():
            return None
        before_text, after_text = base_path.read_text(), after_path.read_text()
        # content_base/ has no other anchor in the plan: the steps' checksums
        # are the integrity check. Tampered bytes fail closed.
        if item.checksum_before and _sha256(before_text) != item.checksum_before:
            return None
        if _sha256(after_text) != item.checksum_after:
            return None
        return before_text, after_text

    return content_for


def effective_blast(plan, profile: ResolvedProfile) -> BlastRadiusClass:
    """The blast class dispatch must honor: max(pinned, recomputed-under-
    current-thresholds). The pinned class is a floor, never a ceiling — a
    customer that tightens thresholds after planning bites already-planned
    bundles, symmetric with the change-class kill switch (ADR-0016).

    Recomputation is a pure function over the frozen plan's own recorded
    device/region lists; no ChangeSet rebuild, no SoT round trip."""
    recorded = plan.blast_radius
    thresholds = profile.thresholds
    devices, regions = recorded.device_count, len(recorded.regions)
    if devices >= thresholds.high_min_devices or regions >= thresholds.high_min_regions:
        recomputed = BlastRadiusClass.HIGH
    elif devices <= thresholds.low_max_devices:
        recomputed = BlastRadiusClass.LOW
    else:
        recomputed = BlastRadiusClass.MODERATE
    return max(recorded.classification, recomputed, key=BLAST_ORDER.__getitem__)


def verify_pre_approval(plan_dir: Path, plan, profile: ResolvedProfile) -> bool:
    """Does the frozen bundle still prove the plan's pre-approval claim under
    the current profile's change classes (and current thresholds)?"""
    claimed = plan.policy_evaluation.pre_approved
    if claimed is None:
        return False
    result = classify_changes(
        plan_changeset(plan),
        effective_blast(plan, profile),
        profile.change_classes,
        _frozen_content_for(plan_dir),
    )
    return result is not None and result.change_class.name == claimed.class_name


def tighten_approvals(
    plan,
    decision: Decision,
    plan_dir: Path,
    profile: ResolvedProfile,
) -> tuple[list[str], list[str], bool | None]:
    """The dispatch-time approval bar (ADR-0014 §5, extended by ADR-0016):
    the recorded decision can only tighten, never loosen. Returns
    (approvals_required, notes, claim_verified) — claim_verified is None
    when the plan claims nothing; False means the caller must not present
    the plan as pre-approved.

    Three floors union into the bar, whatever the claim's fate:
    the frozen decision's own list, the plan's recorded plan-time bar
    (policy_evaluation.approvals_required), and — for unverified/unclaimed
    plans — the CURRENT pack's strategy approvals + blast-class floor,
    under the re-tightened blast class."""
    required = set(decision.approvals_required)
    notes: list[str] = []
    blast = effective_blast(plan, profile)
    if blast != plan.blast_radius.classification:
        notes.append(
            f"blast radius re-tightened under current thresholds: "
            f"{plan.blast_radius.classification.value} -> {blast.value}"
        )
    strategy = next(
        (s for s in profile.strategies
         if s.name == plan.policy_evaluation.canary_strategy),
        None,
    )
    recorded_bar = set(getattr(plan.policy_evaluation, "approvals_required", []) or [])
    current_floor = set(profile.floors.for_class(blast))
    claimed = plan.policy_evaluation.pre_approved

    if claimed is not None:
        if verify_pre_approval(plan_dir, plan, profile):
            notes.append(
                f"pre-approval re-verified from frozen content: "
                f"class {claimed.class_name!r}"
            )
            return sorted(required), notes, True
        if not profile.change_classes.classes:
            notes.append(
                "no change classes in the current profile "
                "(set --policies-dir or IBN_POLICIES_DIR); "
                "treating the pre-approval claim as unverified"
            )
        notes.append(
            f"pre-approval claim {claimed.class_name!r} did NOT re-verify "
            f"under the current policy; tightening"
        )
        required |= recorded_bar | current_floor
        if strategy is None:
            required.add(UNVERIFIABLE)
            notes.append(
                f"canary strategy {plan.policy_evaluation.canary_strategy!r} "
                f"unknown at dispatch time; refusing the empty approval bar"
            )
        else:
            required.update(strategy.requires_approvals)
            if not required:
                notes.append(
                    "strategy floor requires no approvals; "
                    "proceeding un-pre-approved"
                )
        return sorted(required), notes, False

    # no claim: still enforce the floors - decision.yaml is editable
    floor = recorded_bar | current_floor
    if strategy is not None:
        floor |= set(strategy.requires_approvals)
    if not floor <= required:
        required |= floor
        notes.append(
            "decision carried fewer approvals than the current floor "
            "(strategy + blast-class floor + plan-time bar); tightened"
        )
    return sorted(required), notes, None
