"""Pydantic models for the Plan contract (contracts/plan/v1).

These models are the canonical definition; the JSON Schema under
contracts/plan/v1/plan.schema.json is GENERATED from them via
`autonetops-planner export-schema` and checked for drift in CI (ADR-0007).

Target model (ADR-0011): the unit of execution is a CONTROL POINT — a direct
NOS device, an API endpoint, or a controller managing many devices. Blast
radius is always computed over affected *devices*, however the change is
pushed.
"""

from __future__ import annotations

import hashlib
import json
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

PLAN_CONTRACT_VERSION = "1"


class BlastRadiusClass(str, Enum):
    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"


class ControlPointKind(str, Enum):
    DIRECT = "direct"  # NOS device we own the transaction on
    API = "api"  # structured API per device / cloud tenant
    CONTROLLER = "controller"  # one endpoint managing N devices


class ContentFormat(str, Enum):
    """What the artifact's bytes ARE - this, not taste, drives protocol
    selection (ADR-0012): model-based payloads prefer NETCONF/gNMI, CLI
    text can only ride a CLI-shaped transport."""

    CLI_TEXT = "cli-text"  # platform-native CLI lines
    OPENCONFIG_JSON = "openconfig-json"  # OC JSON document (gNMI Set / NETCONF)
    IETF_XML = "ietf-xml"  # YANG XML document (NETCONF edit-config)


MODEL_BASED_FORMATS = {ContentFormat.OPENCONFIG_JSON, ContentFormat.IETF_XML}


class TargetArtifact(BaseModel):
    """One rendered artifact for one control point, as exposed by Infrahub."""

    target: str
    kind: ControlPointKind = ControlPointKind.DIRECT
    definition: str
    checksum: str
    storage_id: str | None = None
    platform: str | None = None
    role: str | None = None
    region: str | None = None
    content_format: ContentFormat = ContentFormat.CLI_TEXT
    affected_devices: list[str] = Field(
        default_factory=list,
        description="Devices this artifact ultimately touches; empty means [target].",
    )

    @property
    def effective_devices(self) -> list[str]:
        return self.affected_devices or [self.target]


class ChangeItem(BaseModel):
    """The unit of diffing: one (control point, artifact definition) pair."""

    target: str
    kind: ControlPointKind = ControlPointKind.DIRECT
    definition: str
    checksum_before: str | None = None
    checksum_after: str | None = None
    storage_id_after: str | None = None
    platform: str | None = None
    role: str | None = None
    region: str | None = None
    content_format: ContentFormat = ContentFormat.CLI_TEXT
    affected_devices: list[str] = Field(default_factory=list)

    @property
    def change_kind(self) -> Literal["added", "removed", "changed"]:
        if self.checksum_before is None:
            return "added"
        if self.checksum_after is None:
            return "removed"
        return "changed"

    @property
    def effective_devices(self) -> list[str]:
        return self.affected_devices or [self.target]


class ChangeSet(BaseModel):
    """All artifact-level differences between two branches."""

    base_branch: str
    candidate_branch: str
    items: list[ChangeItem] = Field(default_factory=list)

    @property
    def deployable(self) -> list[ChangeItem]:
        """Added/changed items; removals need a human decision (decommission)."""
        return [i for i in self.items if i.change_kind != "removed"]

    @property
    def removed(self) -> list[ChangeItem]:
        return [i for i in self.items if i.change_kind == "removed"]


class StepTarget(BaseModel):
    control_point: str
    kind: ControlPointKind = ControlPointKind.DIRECT
    affected_devices: list[str] = Field(default_factory=list)


class RollbackSpec(BaseModel):
    """Strategy names are driver-declared (ADR-0011). Well-known values:
    commit_confirmed, commit_confirm, checkpoint, snapshot_revert,
    controller_revision, manual."""

    strategy: str
    confirm_timeout_minutes: int = 10


class Step(BaseModel):
    """One control-point-level operation for the executor."""

    target: StepTarget
    driver: str | None = None  # executor driver hint; None = resolve by platform
    protocol: str | None = None  # delivery protocol per ADR-0012; None = driver's choice
    platform: str | None = None
    artifact_definition: str
    content_format: ContentFormat = ContentFormat.CLI_TEXT
    checksum_before: str | None = None
    checksum_after: str
    storage_id: str | None = None
    rollback: RollbackSpec
    abort_on_failure: bool = True


class Gate(BaseModel):
    """Validation checkpoint between stages. Expectations are evaluated per
    DEVICE regardless of how the change was pushed (ADR-0011)."""

    kind: Literal["validator.expectations_pass", "manual"] = "validator.expectations_pass"
    soak_minutes: int = 0


class Stage(BaseModel):
    name: str
    steps: list[Step]
    gate: Gate = Field(default_factory=Gate)


class BlastRadius(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    classification: BlastRadiusClass = Field(alias="class")
    device_count: int
    devices: list[str]
    control_points: list[str] = Field(default_factory=list)
    roles: list[str] = Field(default_factory=list)
    regions: list[str] = Field(default_factory=list)


class PreApproval(BaseModel):
    """The whole diff falls inside a reviewed pre-approved change class
    (ADR-0014). Waives the per-plan human approval step ONLY; windows and
    stage gates apply unchanged. Re-verified at dispatch from the frozen
    content — the recorded claim can only ever be tightened, never trusted."""

    model_config = ConfigDict(populate_by_name=True)

    class_name: str = Field(alias="class")
    policy_version: str


class PolicyEvaluation(BaseModel):
    canary_strategy: str
    change_window: str = "not_evaluated"
    rate_limits: str = "not_evaluated"
    pre_approved: PreApproval | None = None


class PlanSource(BaseModel):
    base_branch: str
    candidate_branch: str
    proposed_change_id: str | None = None


class Plan(BaseModel):
    """The declarative rollout document. Nothing executes without one.

    Immutable once approved (merged): any change to the rollout is a new Plan
    that supersedes this one (ADR-0003).
    """

    contract_version: Literal["1"] = PLAN_CONTRACT_VERSION
    id: str
    created_at: str | None = None
    source: PlanSource
    blast_radius: BlastRadius
    policy_evaluation: PolicyEvaluation
    stages: list[Stage]
    removed_targets: list[str] = Field(
        default_factory=list,
        description="Control points whose artifacts disappeared; requires an "
        "explicit decommission decision, never auto-executed.",
    )
    abort_criteria: list[str] = Field(default_factory=list)

    @staticmethod
    def deterministic_id(source: PlanSource, stages: list[Stage]) -> str:
        """Content-addressed plan ID: same diff + same policy -> same ID."""
        payload = json.dumps(
            {
                "source": source.model_dump(),
                "stages": [s.model_dump(mode="json") for s in stages],
            },
            sort_keys=True,
        )
        return "plan-" + hashlib.sha256(payload.encode()).hexdigest()[:16]
