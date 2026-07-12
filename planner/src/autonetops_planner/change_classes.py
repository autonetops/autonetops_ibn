"""Pre-approved change classes (ADR-0014): content-aware classification.

A change class names a kind of diff that rollout approvers have reviewed AS A
CLASS — the policy file is the review surface, owned via CODEOWNERS. A plan
whose every changed artifact falls entirely inside one enabled class carries
no per-plan approval requirement: the review happened earlier, on the class.

Classification is fail-closed. Anything unmatched, added, removed, over the
class's blast ceiling, in a format without a matcher implementation, or whose
bytes cannot be fetched takes the normal approval path. The classifier can
only ever remove a human step from a diff it fully proves; it never adds risk.
"""

from __future__ import annotations

import difflib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import yaml

from .models import BlastRadiusClass, ChangeItem, ChangeSet, ContentFormat

BLAST_ORDER = {
    BlastRadiusClass.LOW: 0,
    BlastRadiusClass.MODERATE: 1,
    BlastRadiusClass.HIGH: 2,
}

# (before_text, after_text) for one changed item; None = bytes unavailable,
# which fails closed.
ContentFor = Callable[[ChangeItem], "tuple[str, str] | None"]


@dataclass
class ChangeClass:
    name: str
    enabled: bool = True
    description: str = ""
    artifact_definitions: list[str] = field(default_factory=list)
    cli_text_allow: list[str] = field(default_factory=list)
    model_paths_allow: list[str] = field(default_factory=list)
    max_blast_radius: BlastRadiusClass = BlastRadiusClass.MODERATE
    canary_strategy: str | None = None
    max_plans_per_hour: int | None = None


@dataclass
class ChangeClassPolicy:
    version: str = "none"
    classes: list[ChangeClass] = field(default_factory=list)


@dataclass(frozen=True)
class Classification:
    change_class: ChangeClass
    policy_version: str


def load_change_classes(policies_dir: str | Path | None) -> ChangeClassPolicy:
    """Load change_classes.yaml. There is deliberately NO builtin default:
    pre-approval only ever comes from reviewed policy data."""
    if policies_dir is None:
        return ChangeClassPolicy()
    path = Path(policies_dir) / "change_classes.yaml"
    if not path.exists():
        return ChangeClassPolicy()
    doc = yaml.safe_load(path.read_text()) or {}
    classes: list[ChangeClass] = []
    for entry in doc.get("classes") or []:
        match = entry.get("match") or {}
        cli_allow = list((match.get("cli-text") or {}).get("changed_lines_allow") or [])
        for pattern in cli_allow:
            re.compile(pattern)  # a broken policy regex must fail at load, loudly
        classes.append(
            ChangeClass(
                name=entry["name"],
                enabled=entry.get("enabled", True),
                description=entry.get("description", ""),
                artifact_definitions=list(
                    (entry.get("applies_to") or {}).get("artifact_definitions") or []
                ),
                cli_text_allow=cli_allow,
                model_paths_allow=list(
                    (match.get("openconfig-json") or {}).get("paths_allow") or []
                ),
                max_blast_radius=BlastRadiusClass(
                    entry.get("max_blast_radius", "moderate")
                ),
                canary_strategy=entry.get("canary_strategy"),
                max_plans_per_hour=(entry.get("rate_limit") or {}).get(
                    "max_plans_per_hour"
                ),
            )
        )
    return ChangeClassPolicy(version=str(doc.get("version", "draft")), classes=classes)


def classify_changes(
    changes: ChangeSet,
    blast: BlastRadiusClass,
    policy: ChangeClassPolicy,
    content_for: ContentFor,
) -> Classification | None:
    """First enabled class whose matchers fully cover EVERY deployable item;
    None = normal approval path. Removals always disqualify the whole
    changeset (decommission is never routine)."""
    if not policy.classes or changes.removed or not changes.deployable:
        return None
    for cls in policy.classes:
        if not cls.enabled:
            continue
        if BLAST_ORDER[blast] > BLAST_ORDER[cls.max_blast_radius]:
            continue
        if all(_item_matches(item, cls, content_for) for item in changes.deployable):
            return Classification(change_class=cls, policy_version=policy.version)
    return None


def _item_matches(item: ChangeItem, cls: ChangeClass, content_for: ContentFor) -> bool:
    if item.change_kind != "changed":
        return False  # brand-new artifacts are never routine
    if cls.artifact_definitions and item.definition not in cls.artifact_definitions:
        return False
    pair = content_for(item)
    if pair is None:
        return False
    before, after = pair
    if item.content_format == ContentFormat.CLI_TEXT:
        if not cls.cli_text_allow:
            return False
        allow = [re.compile(p) for p in cls.cli_text_allow]
        return all(
            not line.strip() or any(rx.search(line) for rx in allow)
            for line in _cli_changed_lines(before, after)
        )
    if item.content_format == ContentFormat.OPENCONFIG_JSON:
        if not cls.model_paths_allow:
            return False
        try:
            before_doc, after_doc = json.loads(before), json.loads(after)
        except ValueError:
            return False
        patterns = [_path_regex(p) for p in cls.model_paths_allow]
        return all(
            any(rx.fullmatch(path) for rx in patterns)
            for path in _json_changed_paths(before_doc, after_doc)
        )
    return False  # no matcher implementation for this format yet: fail closed


def _cli_changed_lines(before: str, after: str) -> list[str]:
    """Added + removed lines of the unified diff, context-free (n=0)."""
    diff = difflib.unified_diff(
        before.splitlines(), after.splitlines(), lineterm="", n=0
    )
    return [
        line[1:]
        for line in diff
        if line[:1] in "+-" and not line.startswith(("+++", "---"))
    ]


def _json_changed_paths(before, after, prefix: str = "") -> list[str]:
    """Paths where two JSON documents differ. Lists whose members all carry a
    'name' key (the OpenConfig convention) are aligned by name and produce
    ``[name=<x>]`` segments; other unequal lists change as one path."""
    if type(before) is not type(after):
        return [prefix or "/"]
    if isinstance(before, dict):
        paths: list[str] = []
        for key in sorted(set(before) | set(after)):
            child = f"{prefix}/{key}"
            if key not in before or key not in after:
                paths.append(child)
            else:
                paths.extend(_json_changed_paths(before[key], after[key], child))
        return paths
    if isinstance(before, list):
        keyed_before, keyed_after = _keyed(before), _keyed(after)
        if keyed_before is not None and keyed_after is not None:
            paths = []
            for name in sorted(set(keyed_before) | set(keyed_after)):
                child = f"{prefix}[name={name}]"
                if name not in keyed_before or name not in keyed_after:
                    paths.append(child)
                else:
                    paths.extend(
                        _json_changed_paths(
                            keyed_before[name], keyed_after[name], child
                        )
                    )
            return paths
        return [] if before == after else [prefix or "/"]
    return [] if before == after else [prefix or "/"]


def _keyed(items: list) -> dict | None:
    if not items or not all(isinstance(e, dict) and "name" in e for e in items):
        return None
    return {e["name"]: e for e in items}


def _path_regex(pattern: str) -> re.Pattern:
    """``[*]`` matches any list key, ``*`` any single path segment."""
    escaped = re.escape(pattern)
    escaped = escaped.replace(re.escape("[*]"), r"\[name=[^\]/]*\]")
    escaped = escaped.replace(re.escape("*"), r"[^/]*")
    return re.compile(escaped)
