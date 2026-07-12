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
"""

from __future__ import annotations

import datetime
import hashlib
from pathlib import Path

import yaml

from autonetops_planner.change_classes import (
    ChangeClassPolicy,
    classify_changes,
)
from autonetops_planner.models import ChangeItem, ChangeSet
from autonetops_planner.policies import CanaryStrategy

from .strategy import Decision

# The name is deliberately un-satisfiable by accident: it surfaces in the
# "missing approvals: ..." abort when a pre-approval claim cannot be checked.
UNVERIFIABLE = "unverifiable-pre-approval"


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


def verify_pre_approval(plan_dir: Path, plan, policy: ChangeClassPolicy) -> bool:
    """Does the frozen bundle still prove the plan's pre-approval claim under
    the current change-class policy?"""
    claimed = plan.policy_evaluation.pre_approved
    if claimed is None:
        return False
    result = classify_changes(
        plan_changeset(plan),
        plan.blast_radius.classification,
        policy,
        _frozen_content_for(plan_dir),
    )
    return result is not None and result.change_class.name == claimed.class_name


def tighten_approvals(
    plan,
    decision: Decision,
    plan_dir: Path,
    policy: ChangeClassPolicy,
    strategies: list[CanaryStrategy],
) -> tuple[list[str], list[str], bool | None]:
    """The dispatch-time approval bar (ADR-0014 §5): the recorded decision can
    only tighten, never loosen. Returns (approvals_required, notes,
    claim_verified) — claim_verified is None when the plan claims nothing;
    False means the caller must not present the plan as pre-approved."""
    required = set(decision.approvals_required)
    notes: list[str] = []
    strategy = next(
        (s for s in strategies if s.name == plan.policy_evaluation.canary_strategy),
        None,
    )
    claimed = plan.policy_evaluation.pre_approved

    if claimed is not None:
        if verify_pre_approval(plan_dir, plan, policy):
            notes.append(
                f"pre-approval re-verified from frozen content: "
                f"class {claimed.class_name!r}"
            )
            return sorted(required), notes, True
        if not policy.classes:
            notes.append(
                "no change-class policy loaded at dispatch time "
                "(set --policies-dir or IBN_POLICIES_DIR); "
                "treating the pre-approval claim as unverified"
            )
        notes.append(
            f"pre-approval claim {claimed.class_name!r} did NOT re-verify "
            f"under the current policy; tightening"
        )
        if strategy is None:
            required.add(UNVERIFIABLE)
            notes.append(
                f"canary strategy {plan.policy_evaluation.canary_strategy!r} "
                f"unknown at dispatch time; refusing the empty approval bar"
            )
        else:
            required.update(strategy.requires_approvals)
            if not strategy.requires_approvals:
                notes.append(
                    "strategy floor requires no approvals; "
                    "proceeding un-pre-approved"
                )
        return sorted(required), notes, False

    # no claim: still enforce the strategy floor - decision.yaml is editable
    if strategy is not None and not set(strategy.requires_approvals) <= required:
        required.update(strategy.requires_approvals)
        notes.append(
            f"decision carried fewer approvals than strategy "
            f"{strategy.name!r} requires; tightened to the floor"
        )
    return sorted(required), notes, None
