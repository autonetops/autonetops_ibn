"""Intent profiles (ADR-0016): the per-customer policy-pack contract.

A *pack* is any directory containing ``profile.yaml``; ``--policies-dir`` /
``IBN_POLICIES_DIR`` points at a pack root. The pack declares how a
customer's intent layer binds to the one engine: blast thresholds, approval
floors, platform/artifact bindings, SoT query paths, and which sibling
policy files (canary strategies, change classes, delivery preferences,
rate limits) it provides. ``builtin:baseline`` — shipped inside this wheel
under ``packs/baseline/`` — is the engine's conservative default pack and
the only permitted ``extends`` target (exactly two layers, ADR-0016).

Three load modes, one return type:

- ``load_profile(None)``        -> ``builtin:baseline`` (strict=False)
- dir **with** ``profile.yaml`` -> full contract, strict; any violation
  raises :class:`ProfileError` listing every finding — never a partial or
  fallback profile (safety floor F14)
- dir **without** it            -> legacy mode: today's lenient per-file
  semantics, with every fallback recorded as an assumption

Validation is fail-closed and collected: the loader gathers *all*
violations before raising, so a pack author fixes one CI run, not ten.
"""

from __future__ import annotations

import hashlib
import json
import re
import typing
from pathlib import Path
from typing import Literal

import yaml
from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import Version
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from . import __version__
from .blast_radius import Thresholds
from .change_classes import ChangeClass, ChangeClassPolicy, load_change_classes
from .models import (
    ROLLBACK_STRATEGIES,
    BlastRadiusClass,
    ContentFormat,
    Gate,
    ProfileRef,
)
from .policies import (
    FORMAT_PROTOCOLS,
    CanaryStage,
    CanaryStrategy,
    load_canary_strategies,
    load_delivery_preferences,
)

PROFILE_CONTRACT_VERSION = 1

#: Closed engine vocabularies (safety floor F13): packs select among these,
#: never define new entries. Membership is checked at pack load, which turns
#: yesterday's plan-build crashes into load-time findings.
SELECTORS = {"one_target", "one_per_role", "remainder"}
GATE_KINDS = set(typing.get_args(Gate.model_fields["kind"].annotation))
PROTOCOLS = {p for protocols in FORMAT_PROTOCOLS.values() for p in protocols}
BLAST_CLASSES = {c.value for c in BlastRadiusClass}

_BASELINE_DIR = Path(__file__).parent / "packs" / "baseline"

#: Reserved tenants: exempt from the IBN_TENANT guard, refused in real packs.
RESERVED_TENANTS = {"_platform", "_legacy"}


class ProfileError(Exception):
    """A pack failed validation. Carries every violation found, not just the
    first — and is never downgraded to a fallback profile (F14)."""

    def __init__(self, source: str, violations: list[str]):
        self.source = source
        self.violations = violations
        lines = "\n".join(f"  - {v}" for v in violations)
        super().__init__(f"invalid intent profile ({source}):\n{lines}")


# --------------------------------------------------------------------------
# profile.yaml document models (contracts/profile/v1; pydantic-canonical,
# extra="forbid" everywhere — an unknown key is a finding, never a shrug)
# --------------------------------------------------------------------------


class ProfileMeta(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant: str
    name: str
    version: str
    conformance: Literal["baseline", "tuned", "full"] = "tuned"
    owner: str = ""
    description: str = ""


class BlastThresholdsModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    low_max_devices: int = Field(default=2, ge=0)
    high_min_devices: int = Field(default=10, ge=1)
    high_min_regions: int = Field(default=2, ge=1)

    @model_validator(mode="after")
    def _ladder(self) -> "BlastThresholdsModel":
        # The low < moderate < high ladder is engine-fixed (F13); a profile
        # moves the thresholds, never inverts or collapses the ladder.
        if not self.low_max_devices < self.high_min_devices:
            raise ValueError(
                "threshold ladder inverted: low_max_devices must be < high_min_devices"
            )
        return self


class BlastRadiusSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    thresholds: BlastThresholdsModel = BlastThresholdsModel()


class ApprovalFloors(BaseModel):
    model_config = ConfigDict(extra="forbid")

    low: list[str] = Field(default_factory=list)
    moderate: list[str] = Field(default_factory=list)
    high: list[str] = Field(default_factory=list)

    def for_class(self, classification: BlastRadiusClass) -> list[str]:
        return {
            BlastRadiusClass.LOW: self.low,
            BlastRadiusClass.MODERATE: self.moderate,
            BlastRadiusClass.HIGH: self.high,
        }[classification]


class ApprovalsSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    floors: ApprovalFloors = ApprovalFloors()


class PlatformBinding(BaseModel):
    """Executor driver + rollback strategy for one platform, keyed exactly
    as the customer's SoT spells it. Partial entries are legal only in
    builtin/legacy modes (the engine's kind-based fallbacks apply); strict
    packs must bind both fields — a guessed driver or a silent 'manual'
    rollback is never reviewed data (F10)."""

    model_config = ConfigDict(extra="forbid")

    driver: str | None = None
    rollback: str | None = None


class ArtifactBinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content_format: ContentFormat


class ArtifactsSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    definitions: dict[str, ArtifactBinding] = Field(default_factory=dict)


class RollbackDefaults(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirm_timeout_minutes: int = Field(default=10, ge=1)


class SotBinding(BaseModel):
    """How the engine queries the customer's Infrahub schema (ADR-0016).

    Exactly two path shapes are supported, validated at load:
    ``attr__value`` (attribute) and ``rel__node__attr__value`` (relationship
    traversal). Full query templating stays deferred to the ADR-0011 seam.
    """

    model_config = ConfigDict(extra="forbid")

    intent_model_version: str = "1.0"
    default_base_branch: str = "main"
    device_kind: str = "DcimGenericDevice"
    role_path: str = "role__value"
    platform_path: str = "platform__node__name__value"
    region_path: str | None = None

    @model_validator(mode="after")
    def _paths(self) -> "SotBinding":
        for field in ("role_path", "platform_path", "region_path"):
            value = getattr(self, field)
            if value is not None and not _valid_sot_path(value):
                raise ValueError(
                    f"{field} {value!r} is not attr__value or rel__node__attr__value"
                )
        return self


def _valid_sot_path(path: str) -> bool:
    parts = path.split("__")
    if len(parts) == 2:
        return bool(parts[0]) and parts[1] == "value"
    if len(parts) == 4:
        return bool(parts[0]) and parts[1] == "node" and bool(parts[2]) and parts[3] == "value"
    return False


class FilesSection(BaseModel):
    """Which sibling files this pack provides. Listed => MUST exist and
    validate; a declared-but-broken file is a load error, never a builtin
    fallback (kills hardcoded-assumption #9)."""

    model_config = ConfigDict(extra="forbid")

    canary_strategies: str | None = None
    change_classes: str | None = None
    delivery_preferences: str | None = None
    rate_limits: str | None = None


class IntentProfileDoc(BaseModel):
    """One profile.yaml, pre-resolution (a single layer)."""

    model_config = ConfigDict(extra="forbid")

    profile_version: Literal[1] = PROFILE_CONTRACT_VERSION
    meta: ProfileMeta
    extends: Literal["builtin:baseline"] | None = "builtin:baseline"
    requires_planner: str | None = None
    sot: SotBinding | None = None
    blast_radius: BlastRadiusSection | None = None
    approvals: ApprovalsSection | None = None
    platforms: dict[str, PlatformBinding] = Field(default_factory=dict)
    artifacts: ArtifactsSection | None = None
    rollback: RollbackDefaults | None = None
    abort_criteria: list[str] | None = None
    files: FilesSection = FilesSection()


# --------------------------------------------------------------------------
# Section-file models (strict mirrors of the YAML policy files)
# --------------------------------------------------------------------------


class CanaryStageModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    select: str
    soak_minutes: int = Field(default=0, ge=0)
    gate: str = "validator.expectations_pass"


class CanaryStrategyModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    enabled: bool = True
    applies_to_blast_radius: list[str] = Field(default_factory=list)
    requires_approvals: list[str] = Field(default_factory=list)
    stages: list[CanaryStageModel] = Field(default_factory=list)


class CanaryStrategiesFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str | int = "draft"
    strategies: list[CanaryStrategyModel] = Field(default_factory=list)


class DeliveryPreferencesFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str | int = "draft"
    # Deprecated and unused (ADR-0016): accepted so existing files validate;
    # the engine never reads it.
    default_order: list[str] | None = None
    platforms: dict[str, list[str]] = Field(default_factory=dict)


class ChangeClassMatchCli(BaseModel):
    model_config = ConfigDict(extra="forbid")

    changed_lines_allow: list[str] = Field(default_factory=list)


class ChangeClassMatchPaths(BaseModel):
    model_config = ConfigDict(extra="forbid")

    paths_allow: list[str] = Field(default_factory=list)


class ChangeClassMatch(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    cli_text: ChangeClassMatchCli | None = Field(default=None, alias="cli-text")
    openconfig_json: ChangeClassMatchPaths | None = Field(
        default=None, alias="openconfig-json"
    )
    ietf_xml: ChangeClassMatchPaths | None = Field(default=None, alias="ietf-xml")


class ChangeClassAppliesTo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_definitions: list[str] = Field(default_factory=list)


class ChangeClassRateLimit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_plans_per_hour: int = Field(ge=1)


class ChangeClassModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    enabled: bool = True
    description: str = ""
    applies_to: ChangeClassAppliesTo = ChangeClassAppliesTo()
    match: ChangeClassMatch = ChangeClassMatch()
    max_blast_radius: str = "moderate"
    canary_strategy: str | None = None
    rate_limit: ChangeClassRateLimit | None = None


class ChangeClassesFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str | int = "draft"
    classes: list[ChangeClassModel] = Field(default_factory=list)


class RateLimitModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scope: str
    max_concurrent_devices: int | None = Field(default=None, ge=1)
    max_devices_per_hour: int | None = Field(default=None, ge=1)
    max_concurrent_plans: int | None = Field(default=None, ge=1)


class RateLimitsFile(BaseModel):
    """Validated so packs can author it under review; the engine still does
    not evaluate it — Plans keep reporting ``rate_limits: not_evaluated``
    (ADR-0016 deferral, honest by construction)."""

    model_config = ConfigDict(extra="forbid")

    version: str | int = "draft"
    limits: list[RateLimitModel] = Field(default_factory=list)


# --------------------------------------------------------------------------
# The resolved profile — ONE object the whole engine consumes
# --------------------------------------------------------------------------


class ResolvedProfile(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    ref: ProfileRef
    strict: bool
    sot: SotBinding
    thresholds: Thresholds
    floors: ApprovalFloors
    strategies: list[CanaryStrategy]  # enabled entries, resolved order
    delivery_preferences: dict  # {"platforms": {...}} — select_protocol shape
    change_classes: ChangeClassPolicy
    platforms: dict[str, PlatformBinding]
    definition_formats: dict[str, ContentFormat]
    rollback_defaults: RollbackDefaults
    abort_criteria: list[str]
    load_assumptions: list[str] = Field(default_factory=list)
    resolved_doc: dict = Field(default_factory=dict)  # the checksummed document


# --------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------


def load_profile(
    policies_dir: str | Path | None, *, tenant: str | None = None
) -> ResolvedProfile:
    """Resolve the intent profile for a policies dir (see module docstring).

    ``tenant`` is the deployment's tenant guard (env ``IBN_TENANT``): when
    set, a real pack whose ``meta.tenant`` differs is refused loudly —
    cross-tenant pack (or bundle) reuse must never be quiet. Builtin and
    legacy profiles are exempt (reserved ``_platform`` / ``_legacy``
    tenants)."""
    if policies_dir is None:
        return _load_builtin_baseline()
    directory = Path(policies_dir)
    if (directory / "profile.yaml").exists():
        profile = _load_pack(directory)
        if tenant and profile.ref.tenant != tenant:
            raise ProfileError(
                str(directory),
                [
                    f"tenant guard: pack tenant {profile.ref.tenant!r} does not "
                    f"match deployment tenant {tenant!r} (IBN_TENANT)"
                ],
            )
        return profile
    return _load_legacy_dir(directory)


def _read_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text()) or {}


def _baseline_doc() -> IntentProfileDoc:
    return IntentProfileDoc.model_validate(_read_yaml(_BASELINE_DIR / "profile.yaml"))


def _load_builtin_baseline() -> ResolvedProfile:
    doc = _baseline_doc()
    violations: list[str] = []
    strategies = _canary_models(_BASELINE_DIR, doc.files.canary_strategies, violations)
    delivery = _delivery_platforms(
        _BASELINE_DIR, doc.files.delivery_preferences, violations
    )
    if violations:  # pragma: no cover - a broken wheel, not a broken pack
        raise ProfileError("builtin:baseline", violations)
    return _resolve(
        doc,
        source_dir=_BASELINE_DIR,
        strategy_models=strategies,
        delivery_platforms=delivery,
        classes_file=None,
        strict=False,
        source="builtin",
    )


def _load_pack(directory: Path) -> ResolvedProfile:
    violations: list[str] = []
    try:
        child = IntentProfileDoc.model_validate(_read_yaml(directory / "profile.yaml"))
    except (ValidationError, yaml.YAMLError) as exc:
        raise ProfileError(str(directory), [f"profile.yaml: {exc}"]) from exc

    if child.meta.tenant in RESERVED_TENANTS:
        violations.append(
            f"meta.tenant {child.meta.tenant!r} is reserved for the engine"
        )
    _check_requires_planner(child, violations)
    _check_conformance(child, violations)

    if child.extends == "builtin:baseline":
        base = _baseline_doc()
        doc = _merge(base, child)
        base_strategies = _canary_models(
            _BASELINE_DIR, base.files.canary_strategies, violations
        )
        base_delivery = _delivery_platforms(
            _BASELINE_DIR, base.files.delivery_preferences, violations
        )
    else:
        _check_from_scratch_mandatory(child, violations)
        doc = child
        base_strategies, base_delivery = [], {}

    child_strategies = _canary_models(
        directory, child.files.canary_strategies, violations
    )
    child_delivery = _delivery_platforms(
        directory, child.files.delivery_preferences, violations
    )
    strategy_models = _merge_strategies(base_strategies, child_strategies)
    delivery_platforms = {**base_delivery, **child_delivery}  # per-key, child wins

    classes_file = None
    if child.files.change_classes:
        classes_file = _load_model_file(
            directory / child.files.change_classes,
            ChangeClassesFile,
            violations,
            "change_classes",
        )
    if child.files.rate_limits:
        _load_model_file(
            directory / child.files.rate_limits, RateLimitsFile, violations, "rate_limits"
        )

    if violations:
        raise ProfileError(str(directory), violations)
    return _resolve(
        doc,
        source_dir=directory,
        strategy_models=strategy_models,
        delivery_platforms=delivery_platforms,
        classes_file=classes_file,
        strict=True,
        source="pack",
    )


def _check_requires_planner(doc: IntentProfileDoc, violations: list[str]) -> None:
    if doc.requires_planner is None:
        return
    try:
        spec = SpecifierSet(doc.requires_planner)
    except InvalidSpecifier:
        violations.append(f"requires_planner {doc.requires_planner!r} is not PEP 440")
        return
    if Version(__version__) not in spec:
        violations.append(
            f"requires_planner {doc.requires_planner!r} is not satisfied by "
            f"engine {__version__}"
        )


#: Sections permitted per conformance level (ADR-0016): a pack may not use
#: sections above its declared level, so a "small" pack cannot silently grow
#: unreviewed surface.
_TUNED_SECTIONS = ("approvals", "platforms", "artifacts", "rollback")


def _check_conformance(doc: IntentProfileDoc, violations: list[str]) -> None:
    level = doc.meta.conformance
    if level == "full":
        return
    uses_files = any(getattr(doc.files, f) for f in FilesSection.model_fields)
    if level == "baseline":
        for section in _TUNED_SECTIONS:
            if getattr(doc, section):
                violations.append(
                    f"conformance 'baseline' does not allow the {section!r} section"
                )
        if uses_files:
            violations.append(
                "conformance 'baseline' does not allow the 'files' section"
            )
        if doc.sot is not None:
            violations.append("conformance 'baseline' does not allow the 'sot' section")
        return
    # tuned: sot may only change default_base_branch
    if doc.sot is not None:
        reference = SotBinding(default_base_branch=doc.sot.default_base_branch)
        if doc.sot != reference:
            violations.append(
                "conformance 'tuned' allows sot.default_base_branch only; "
                "declare conformance: full for schema bindings"
            )


def _check_from_scratch_mandatory(doc: IntentProfileDoc, violations: list[str]) -> None:
    if doc.blast_radius is None:
        violations.append("extends: null requires an explicit blast_radius section")
    if doc.abort_criteria is None:
        violations.append("extends: null requires explicit abort_criteria")
    if doc.artifacts is None:
        violations.append("extends: null requires an explicit artifacts section")
    if doc.files.canary_strategies is None:
        violations.append("extends: null requires files.canary_strategies")


def _merge(base: IntentProfileDoc, child: IntentProfileDoc) -> IntentProfileDoc:
    """Two-layer section merge, small and total (ADR-0016):

    - scalar/mapping sections: wholesale replacement when present
    - platforms: per-key merge, child key replaces the whole entry
    - approvals.floors: union only — a child adds approvers, never removes
    - change classes: never inherited (baseline ships none, CI-pinned)
    """
    platforms = dict(base.platforms)
    platforms.update(child.platforms)
    base_floors = (base.approvals or ApprovalsSection()).floors
    child_floors = (child.approvals or ApprovalsSection()).floors
    return child.model_copy(
        deep=True,
        update={
            "sot": child.sot or base.sot,
            "blast_radius": child.blast_radius or base.blast_radius,
            "artifacts": child.artifacts or base.artifacts,
            "rollback": child.rollback or base.rollback,
            "abort_criteria": (
                child.abort_criteria
                if child.abort_criteria is not None
                else base.abort_criteria
            ),
            "platforms": platforms,
            "approvals": ApprovalsSection(
                floors=ApprovalFloors(
                    low=sorted(set(base_floors.low) | set(child_floors.low)),
                    moderate=sorted(
                        set(base_floors.moderate) | set(child_floors.moderate)
                    ),
                    high=sorted(set(base_floors.high) | set(child_floors.high)),
                )
            ),
        },
    )


def _canary_models(
    directory: Path, filename: str | None, violations: list[str]
) -> list[CanaryStrategyModel]:
    if not filename:
        return []
    loaded = _load_model_file(
        directory / filename, CanaryStrategiesFile, violations, "canary_strategies"
    )
    return list(loaded.strategies) if loaded else []


def _delivery_platforms(
    directory: Path, filename: str | None, violations: list[str]
) -> dict[str, list[str]]:
    if not filename:
        return {}
    loaded = _load_model_file(
        directory / filename, DeliveryPreferencesFile, violations, "delivery_preferences"
    )
    if loaded is None:
        return {}
    for platform, order in loaded.platforms.items():
        for protocol in order:
            if protocol not in PROTOCOLS:
                violations.append(
                    f"delivery_preferences: unknown protocol {protocol!r} for "
                    f"platform {platform!r} (engine vocabulary: {sorted(PROTOCOLS)})"
                )
    return {platform: list(order) for platform, order in loaded.platforms.items()}


def _load_model_file(
    path: Path, model: type[BaseModel], violations: list[str], label: str
):
    if not path.exists():
        violations.append(f"{label}: declared file {path.name!r} does not exist")
        return None
    try:
        return model.model_validate(_read_yaml(path))
    except (ValidationError, yaml.YAMLError) as exc:
        violations.append(f"{label} ({path.name}): {exc}")
        return None


def _merge_strategies(
    base: list[CanaryStrategyModel], child: list[CanaryStrategyModel]
) -> list[CanaryStrategyModel]:
    """Merge by name: same name = full replacement (a half-merged strategy is
    a safety hazard); new names append; ``enabled: false`` removes."""
    merged = list(base)
    index = {m.name: i for i, m in enumerate(merged)}
    for entry in child:
        if entry.name in index:
            merged[index[entry.name]] = entry
        else:
            index[entry.name] = len(merged)
            merged.append(entry)
    return merged


# --------------------------------------------------------------------------
# Cross-reference gates + materialization
# --------------------------------------------------------------------------


def _resolve(
    doc: IntentProfileDoc,
    *,
    source_dir: Path,
    strategy_models: list[CanaryStrategyModel],
    delivery_platforms: dict[str, list[str]],
    classes_file: ChangeClassesFile | None,
    strict: bool,
    source: Literal["builtin", "pack"],
) -> ResolvedProfile:
    violations: list[str] = []
    _validate_strategies(strategy_models, violations)
    floors = (doc.approvals or ApprovalsSection()).floors
    _validate_coverage_and_f9(strategy_models, floors, violations)
    if classes_file is not None:
        _validate_change_classes(classes_file, strategy_models, violations)
    for platform, binding in doc.platforms.items():
        if strict and (binding.driver is None or binding.rollback is None):
            violations.append(
                f"platforms.{platform}: strict packs must bind both driver and "
                f"rollback explicitly (reviewed pins, never guesses)"
            )
        if binding.rollback is not None and binding.rollback not in ROLLBACK_STRATEGIES:
            violations.append(
                f"platforms.{platform}: unknown rollback {binding.rollback!r} "
                f"(engine vocabulary: {sorted(ROLLBACK_STRATEGIES)})"
            )
    if violations:
        raise ProfileError(str(source_dir), violations)

    thresholds_model = (doc.blast_radius or BlastRadiusSection()).thresholds
    thresholds = Thresholds(
        low_max_devices=thresholds_model.low_max_devices,
        high_min_devices=thresholds_model.high_min_devices,
        high_min_regions=thresholds_model.high_min_regions,
    )
    strategies = [
        CanaryStrategy(
            name=m.name,
            applies_to=[BlastRadiusClass(c) for c in m.applies_to_blast_radius],
            stages=[
                CanaryStage(select=s.select, soak_minutes=s.soak_minutes, gate=s.gate)
                for s in m.stages
            ],
            requires_approvals=list(m.requires_approvals),
        )
        for m in strategy_models
        if m.enabled
    ]
    definition_formats = {
        name: binding.content_format
        for name, binding in (doc.artifacts or ArtifactsSection()).definitions.items()
    }
    abort_criteria = list(doc.abort_criteria or [])

    resolved_doc = {
        "profile_version": PROFILE_CONTRACT_VERSION,
        "meta": doc.meta.model_dump(),
        "sot": (doc.sot or SotBinding()).model_dump(),
        "blast_radius": {"thresholds": thresholds_model.model_dump()},
        "approvals": {"floors": floors.model_dump()},
        "platforms": {
            name: binding.model_dump() for name, binding in sorted(doc.platforms.items())
        },
        "artifacts": {
            "definitions": {
                name: {"content_format": fmt.value}
                for name, fmt in sorted(definition_formats.items())
            }
        },
        "rollback": (doc.rollback or RollbackDefaults()).model_dump(),
        "abort_criteria": abort_criteria,
        "canary_strategies": [m.model_dump() for m in strategy_models],
        "delivery_preferences": {
            "platforms": {k: v for k, v in sorted(delivery_platforms.items())}
        },
        "change_classes": (
            classes_file.model_dump(by_alias=True) if classes_file else None
        ),
    }

    return ResolvedProfile(
        ref=ProfileRef(
            tenant=doc.meta.tenant,
            name=doc.meta.name,
            version=doc.meta.version,
            checksum=profile_checksum(resolved_doc),
            source=source,
        ),
        strict=strict,
        sot=doc.sot or SotBinding(),
        thresholds=thresholds,
        floors=floors,
        strategies=strategies,
        delivery_preferences={"platforms": delivery_platforms},
        change_classes=_materialize_change_classes(classes_file),
        platforms=dict(doc.platforms),
        definition_formats=definition_formats,
        rollback_defaults=doc.rollback or RollbackDefaults(),
        abort_criteria=abort_criteria,
        resolved_doc=resolved_doc,
    )


def profile_checksum(resolved_doc: dict) -> str:
    """Identity from bytes, not claims: sha256 over the resolved profile as
    canonical JSON. Formatting-insensitive; the value Plans record and
    dispatch compares."""
    canonical = json.dumps(
        resolved_doc, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _validate_strategies(
    strategies: list[CanaryStrategyModel], violations: list[str]
) -> None:
    seen: set[str] = set()
    for strategy in strategies:
        if strategy.name in seen:
            violations.append(f"canary strategy {strategy.name!r} defined twice")
        seen.add(strategy.name)
        for blast in strategy.applies_to_blast_radius:
            if blast not in BLAST_CLASSES:
                violations.append(
                    f"strategy {strategy.name!r}: unknown blast class {blast!r}"
                )
        if strategy.enabled and not strategy.stages:
            violations.append(f"strategy {strategy.name!r} has no stages")
        for stage in strategy.stages:
            if stage.select not in SELECTORS:
                violations.append(
                    f"strategy {strategy.name!r}: unknown selector {stage.select!r} "
                    f"(engine vocabulary: {sorted(SELECTORS)})"
                )
            if stage.gate not in GATE_KINDS:
                violations.append(
                    f"strategy {strategy.name!r}: unknown gate {stage.gate!r} "
                    f"(engine vocabulary: {sorted(GATE_KINDS)})"
                )


def _validate_coverage_and_f9(
    strategies: list[CanaryStrategyModel], floors: ApprovalFloors, violations: list[str]
) -> None:
    enabled = [s for s in strategies if s.enabled]
    for blast in BlastRadiusClass:
        if not any(blast.value in s.applies_to_blast_radius for s in enabled):
            violations.append(
                f"no enabled canary strategy applies to blast radius {blast.value!r} "
                f"(coverage is a load-time requirement, not a plan-time crash)"
            )
    # F9: HIGH blast radius always has a named human somewhere. A strategy
    # reachable by classification (non-empty applies_to) that covers HIGH
    # must carry approvals from the strategy or the floor; class-only
    # strategies (applies_to_blast_radius: []) are exempt — they are
    # reachable solely via a reviewed, customer-authored change class.
    for strategy in enabled:
        if BlastRadiusClass.HIGH.value not in strategy.applies_to_blast_radius:
            continue
        if not set(strategy.requires_approvals) | set(floors.high):
            violations.append(
                f"strategy {strategy.name!r} applies to high blast radius with no "
                f"approvals (F9): add requires_approvals, set approvals.floors.high, "
                f"or make it class-only with applies_to_blast_radius: []"
            )


def _validate_change_classes(
    classes_file: ChangeClassesFile,
    strategies: list[CanaryStrategyModel],
    violations: list[str],
) -> None:
    strategy_names = {s.name for s in strategies if s.enabled}
    for cls in classes_file.classes:
        if cls.max_blast_radius not in BLAST_CLASSES:
            violations.append(
                f"change class {cls.name!r}: unknown max_blast_radius "
                f"{cls.max_blast_radius!r}"
            )
        if cls.canary_strategy and cls.canary_strategy not in strategy_names:
            violations.append(
                f"change class {cls.name!r}: canary_strategy "
                f"{cls.canary_strategy!r} names no enabled strategy"
            )
        if cls.match.ietf_xml is not None:
            violations.append(
                f"change class {cls.name!r}: ietf-xml matcher is unsupported by "
                f"engine {__version__} (fail-closed; ADR-0016 deferral)"
            )
        cli_allow = cls.match.cli_text.changed_lines_allow if cls.match.cli_text else []
        for pattern in cli_allow:
            try:
                re.compile(pattern)
            except re.error as exc:
                violations.append(
                    f"change class {cls.name!r}: broken regex {pattern!r}: {exc}"
                )


def _materialize_change_classes(
    classes_file: ChangeClassesFile | None,
) -> ChangeClassPolicy:
    if classes_file is None:
        return ChangeClassPolicy()
    classes = [
        ChangeClass(
            name=cls.name,
            enabled=cls.enabled,
            description=cls.description,
            artifact_definitions=list(cls.applies_to.artifact_definitions),
            cli_text_allow=list(
                cls.match.cli_text.changed_lines_allow if cls.match.cli_text else []
            ),
            model_paths_allow=list(
                cls.match.openconfig_json.paths_allow
                if cls.match.openconfig_json
                else []
            ),
            max_blast_radius=BlastRadiusClass(cls.max_blast_radius),
            canary_strategy=cls.canary_strategy,
            max_plans_per_hour=(
                cls.rate_limit.max_plans_per_hour if cls.rate_limit else None
            ),
        )
        for cls in classes_file.classes
    ]
    return ChangeClassPolicy(version=str(classes_file.version), classes=classes)


# --------------------------------------------------------------------------
# Legacy mode: a policies dir without profile.yaml
# --------------------------------------------------------------------------


def _load_legacy_dir(directory: Path) -> ResolvedProfile:
    """Today's lenient per-file semantics, preserved verbatim — with every
    fallback recorded as an assumption so provenance is never blank. Removal
    of this mode is a future major (ADR-0016)."""
    assumptions: list[str] = []
    strategies = load_canary_strategies(directory)
    if not _file_has_entries(directory / "canary_strategies.yaml", "strategies"):
        assumptions.append("canary_strategies: builtin defaults in effect")
    delivery = load_delivery_preferences(directory)
    if not (directory / "delivery_preferences.yaml").exists():
        assumptions.append("delivery_preferences: builtin defaults in effect")
    change_classes = load_change_classes(directory)
    if not change_classes.classes:
        assumptions.append("change_classes: none loaded (no pre-approval possible)")

    baseline = _load_builtin_baseline()
    return ResolvedProfile(
        ref=ProfileRef(
            tenant="_legacy",
            name="legacy-dir",
            version="0",
            checksum=_legacy_dir_checksum(directory),
            source="legacy-policies-dir",
        ),
        strict=False,
        sot=baseline.sot,
        thresholds=baseline.thresholds,
        floors=ApprovalFloors(),
        strategies=strategies,
        delivery_preferences=delivery,
        change_classes=change_classes,
        platforms=baseline.platforms,
        definition_formats=baseline.definition_formats,
        rollback_defaults=baseline.rollback_defaults,
        abort_criteria=baseline.abort_criteria,
        load_assumptions=assumptions,
        resolved_doc={},
    )


def _file_has_entries(path: Path, key: str) -> bool:
    if not path.exists():
        return False
    try:
        doc = yaml.safe_load(path.read_text()) or {}
    except yaml.YAMLError:
        return False
    return bool(doc.get(key))


def _legacy_dir_checksum(directory: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(directory.rglob("*")):
        if path.is_file():
            digest.update(str(path.relative_to(directory)).encode())
            digest.update(b"\0")
            digest.update(path.read_bytes())
    return "sha256:" + digest.hexdigest()
