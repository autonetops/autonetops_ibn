"""Load and evaluate planner policies (planner/policies/*.yaml).

Policies are data under review, never hardcoded. While the policy files are
still drafts (empty lists), built-in conservative defaults apply and are
reported as such in the Plan's policy_evaluation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .models import BlastRadiusClass


@dataclass
class CanaryStage:
    select: str  # "one_target" | "one_per_role" | "remainder" (targets = control points)
    soak_minutes: int = 0
    gate: str = "validator.expectations_pass"


@dataclass
class CanaryStrategy:
    name: str
    applies_to: list[BlastRadiusClass]
    stages: list[CanaryStage] = field(default_factory=list)
    requires_approvals: list[str] = field(default_factory=list)


DEFAULT_STRATEGIES = [
    CanaryStrategy(
        name="builtin-single-target-canary",
        applies_to=[BlastRadiusClass.LOW, BlastRadiusClass.MODERATE],
        stages=[
            CanaryStage(select="one_target", soak_minutes=30),
            CanaryStage(select="remainder", soak_minutes=0),
        ],
    ),
    CanaryStrategy(
        name="builtin-high-blast-radius",
        applies_to=[BlastRadiusClass.HIGH],
        stages=[
            CanaryStage(select="one_target", soak_minutes=60),
            CanaryStage(select="one_per_role", soak_minutes=60),
            CanaryStage(select="remainder", soak_minutes=0),
        ],
        requires_approvals=["platform-lead", "domain-owner"],
    ),
]


def load_canary_strategies(policies_dir: str | Path | None) -> list[CanaryStrategy]:
    """Load strategies from canary_strategies.yaml; fall back to builtins."""
    if policies_dir is None:
        return DEFAULT_STRATEGIES
    path = Path(policies_dir) / "canary_strategies.yaml"
    if not path.exists():
        return DEFAULT_STRATEGIES
    doc = yaml.safe_load(path.read_text()) or {}
    raw = doc.get("strategies") or []
    if not raw:
        return DEFAULT_STRATEGIES
    strategies = []
    for entry in raw:
        strategies.append(
            CanaryStrategy(
                name=entry["name"],
                applies_to=[
                    BlastRadiusClass(c) for c in entry.get("applies_to_blast_radius", [])
                ],
                stages=[
                    CanaryStage(
                        select=s["select"],
                        soak_minutes=s.get("soak_minutes", 0),
                        gate=s.get("gate", "validator.expectations_pass"),
                    )
                    for s in entry.get("stages", [])
                ],
                requires_approvals=entry.get("requires_approvals", []),
            )
        )
    return strategies


def select_strategy(
    strategies: list[CanaryStrategy], classification: BlastRadiusClass
) -> CanaryStrategy:
    for strategy in strategies:
        if classification in strategy.applies_to:
            return strategy
    raise LookupError(f"no canary strategy applies to blast radius {classification.value!r}")


# -- delivery preferences (ADR-0012) -----------------------------------------

DEFAULT_DELIVERY_PREFERENCES: dict = {
    "default_order": ["gnmi", "netconf", "http_api"],
    "platforms": {
        "junos": ["netconf", "gnmi"],
        "iosxr": ["netconf", "gnmi"],
        "eos": ["eapi", "gnmi"],
        "srlinux": ["gnmi", "json_rpc"],
        "cloudvision": ["http_api"],
    },
}


def load_delivery_preferences(policies_dir: str | Path | None) -> dict:
    """Load delivery_preferences.yaml; fall back to builtin defaults."""
    if policies_dir is None:
        return DEFAULT_DELIVERY_PREFERENCES
    path = Path(policies_dir) / "delivery_preferences.yaml"
    if not path.exists():
        return DEFAULT_DELIVERY_PREFERENCES
    doc = yaml.safe_load(path.read_text()) or {}
    return {
        "default_order": doc.get("default_order")
        or DEFAULT_DELIVERY_PREFERENCES["default_order"],
        "platforms": doc.get("platforms")
        or DEFAULT_DELIVERY_PREFERENCES["platforms"],
    }


def select_protocol(platform: str | None, preferences: dict) -> str | None:
    """First protocol in the platform's preference list; None = unknown
    platform, the driver's own declared order applies (ADR-0012)."""
    if not platform:
        return None
    order = preferences["platforms"].get(platform.lower())
    return order[0] if order else None
