"""The dispatch decision: given a Plan and its Timeline, what happens now?

Modes:
  immediate      an eligible window is open; dispatch may proceed
  scheduled      the plan is sound but must wait for its window
  needs_approval the canary strategy demands named approvals first
  blocked        no eligible window exists within the horizon

Emergency is an override with a name on it, not a mode: a critical-priority
intent plus an explicit --emergency flag dispatches immediately and the
override is recorded in the decision (and in evidence).
"""

from __future__ import annotations

import datetime

from pydantic import BaseModel, Field

from .timeline import Timeline

# How long an "open now" verdict stays honest between evaluation and dispatch.
GRACE = datetime.timedelta(minutes=2)

PRIORITY_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3}


class Decision(BaseModel):
    mode: str  # immediate | scheduled | needs_approval | blocked
    reasons: list[str] = Field(default_factory=list)
    approvals_required: list[str] = Field(default_factory=list)
    window: str | None = None
    starts_at: datetime.datetime | None = None
    priority: str = "medium"
    emergency_override: bool = False


def decide(
    plan,
    timeline: Timeline,
    *,
    now: datetime.datetime,
    priority: str = "medium",
    emergency: bool = False,
    strategies=None,
) -> Decision:
    approvals: list[str] = []
    for strategy in strategies or []:
        if strategy.name == plan.policy_evaluation.canary_strategy:
            approvals = list(strategy.requires_approvals)

    # every branch below overwrites mode; "blocked" is the safe default
    decision = Decision(mode="blocked", priority=priority,
                        approvals_required=approvals)

    if not timeline.feasible:
        decision.mode = "blocked"
        decision.reasons.extend(timeline.reasons)
        if emergency and PRIORITY_ORDER.get(priority, 1) >= PRIORITY_ORDER["critical"]:
            decision.mode = "immediate"
            decision.emergency_override = True
            decision.reasons.append(
                "EMERGENCY OVERRIDE: critical-priority intent dispatches "
                "without a window; the override is on the record"
            )
        return decision

    first = timeline.first_start
    decision.window = timeline.entries[0].window if timeline.entries else None
    decision.starts_at = first

    if emergency and PRIORITY_ORDER.get(priority, 1) >= PRIORITY_ORDER["critical"]:
        decision.mode = "immediate"
        decision.emergency_override = True
        decision.reasons.append(
            "EMERGENCY OVERRIDE: dispatching ahead of the scheduled window"
        )
    elif first is not None and first <= now + GRACE:
        decision.mode = "immediate"
        decision.reasons.append(
            f"window {decision.window!r} is open for blast radius "
            f"{plan.blast_radius.classification.value!r}"
        )
    else:
        decision.mode = "scheduled"
        decision.reasons.append(
            f"next eligible window {decision.window!r} opens at "
            f"{first.isoformat() if first else 'unknown'}"
        )

    if approvals and decision.mode in ("immediate", "scheduled"):
        decision.mode = "needs_approval"
        decision.reasons.append(
            "canary strategy requires approvals: " + ", ".join(approvals)
        )

    return decision


def apply_to_plan(plan, decision: Decision) -> None:
    """Record the evaluation inside the Plan's policy_evaluation block."""
    if decision.mode == "blocked":
        summary = "blocked: " + "; ".join(decision.reasons)[:200]
    elif decision.starts_at:
        summary = (f"{decision.mode} {decision.starts_at.isoformat()} "
                   f"via {decision.window}")
    else:
        summary = decision.mode
    plan.policy_evaluation.change_window = summary
