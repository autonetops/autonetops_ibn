"""Load and evaluate planner policies (planner/policies/*.yaml).

Policies are data under review, never hardcoded. While the policy files are
still drafts (empty lists), built-in conservative defaults apply and are
reported as such in the Plan's policy_evaluation.

The lenient loaders in this module implement LEGACY MODE (a policies dir
without profile.yaml) and the builtin defaults. Packs with a profile.yaml
go through autonetops_planner.profile.load_profile instead, which is strict
(ADR-0016). The DEFAULT_* constants below are mirrored by the shipped
packs/baseline/ pack — pinned equal by planner/tests/test_profile.py.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .models import BlastRadiusClass, ContentFormat, MODEL_BASED_FORMATS


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


def strategy_by_name(strategies: list[CanaryStrategy], name: str) -> CanaryStrategy:
    """A change class naming a missing strategy is a policy bug: fail loudly
    (ADR-0014), never fall back silently to a different rollout shape."""
    for strategy in strategies:
        if strategy.name == name:
            return strategy
    raise LookupError(f"no canary strategy named {name!r}")


# -- delivery preferences (ADR-0012) -----------------------------------------
#
# Two axes decide the protocol:
#   1. what the platform speaks (per-platform preference order below)
#   2. what the artifact IS (content_format): a model-based payload
#      (openconfig-json / ietf-xml) prefers NETCONF then gNMI; CLI text can
#      only ride a CLI-shaped transport (cli / eapi).
# The intersection is taken in platform-preference order, so a platform that
# ranks netconf first gets netconf the moment its artifacts turn model-based.

FORMAT_PROTOCOLS: dict[str, list[str]] = {
    # protocols able to carry each artifact format
    "model-based": ["netconf", "gnmi", "json_rpc", "http_api"],
    # eAPI/REST/JSON-RPC all wrap CLI text; NETCONF and gNMI cannot carry it
    "cli-text": ["cli", "eapi", "http_api", "json_rpc"],
}

DEFAULT_DELIVERY_PREFERENCES: dict = {
    "default_order": ["netconf", "gnmi", "http_api", "cli"],
    "platforms": {
        "junos": ["netconf", "gnmi", "cli"],
        "iosxr": ["netconf", "gnmi", "cli"],
        "eos": ["netconf", "eapi", "gnmi", "cli"],
        "arista_eos": ["netconf", "eapi", "gnmi", "cli"],
        "srlinux": ["gnmi", "netconf", "cli", "json_rpc"],
        "nokia_srlinux": ["gnmi", "netconf", "cli", "json_rpc"],
        "cisco_iosxe": ["netconf", "cli"],
        "frr": ["cli"],
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


def select_protocol(
    platform: str | None,
    preferences: dict,
    content_format: ContentFormat = ContentFormat.CLI_TEXT,
) -> str | None:
    """First platform-preferred protocol that can carry the artifact's
    format; None = unknown platform, the driver's own declared order
    applies (ADR-0012). NETCONF/gNMI are only eligible for model-based
    payloads - CLI text cannot ride them.

    Keys are matched exactly as the SoT spells the platform first (pack
    keys, ADR-0016), then lowercased (the builtin/legacy key style)."""
    if not platform:
        return None
    platforms = preferences.get("platforms") or {}
    order = platforms.get(platform) or platforms.get(platform.lower())
    if not order:
        return None
    format_key = "model-based" if content_format in MODEL_BASED_FORMATS else "cli-text"
    eligible = FORMAT_PROTOCOLS[format_key]
    for protocol in order:
        if protocol in eligible:
            return protocol
    return None
