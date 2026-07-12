"""The expectations gate: the runtime half of `validator.expectations_pass`.

Given an ExpectationSet and per-device facts (from executor get_facts),
produce a GateResult. Devices whose facts are missing - no driver, device
unreachable - yield ``unverifiable`` checks: reported, never silently
counted as passing.

A rollout gate blocks on REGRESSIONS, not on history: an expectation that
already failed before the change (the ``baseline``) is reported as
``pre_existing`` - drift for the reconcile loop to chase, not a reason to
abort a rollout that did not cause it.
"""

from __future__ import annotations

from typing import Any

from .models import CheckResult, ExpectationSet, GateResult


def failing_keys(result: GateResult) -> set[tuple[str, str, str]]:
    """Identity of every failed check - the baseline for regression gating."""
    return {
        (c.contract, c.device, c.neighbor_ip)
        for c in result.checks if c.status == "fail"
    }


def evaluate_sessions(
    expectations: ExpectationSet,
    facts_by_device: dict[str, dict[str, Any]],
    baseline: set[tuple[str, str, str]] | None = None,
) -> GateResult:
    checks: list[CheckResult] = []
    for exp in expectations.sessions:
        facts = facts_by_device.get(exp.device)
        neighbors = (facts or {}).get("bgp_neighbors") or {}
        if facts is None:
            status, actual = "unverifiable", None
        elif exp.neighbor_ip not in neighbors:
            # a session the device does not even list is not established
            status, actual = "fail", "absent"
        else:
            actual = neighbors[exp.neighbor_ip]
            status = "pass" if actual == exp.must_state else "fail"
        if (status == "fail" and baseline
                and (exp.contract, exp.device, exp.neighbor_ip) in baseline):
            status = "pre_existing"
        checks.append(CheckResult(
            contract=exp.contract,
            device=exp.device,
            neighbor_ip=exp.neighbor_ip,
            expected=exp.must_state,
            actual=actual,
            status=status,
        ))
    return GateResult(checks=checks)
