"""Pydantic models for the Plan contract (contracts/plan/v1).

These models are the canonical definition; the JSON Schema under
contracts/plan/v1/plan.schema.json is GENERATED from them via
`autonetops-planner export-schema` and checked for drift in CI (ADR-0007).
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


class DeviceArtifact(BaseModel):
    """One rendered artifact for one device, as exposed by Infrahub."""

    device: str
    definition: str
    checksum: str
    storage_id: str | None = None
    platform: str | None = None
    role: str | None = None
    region: str | None = None


class ChangeItem(BaseModel):
    """The unit of diffing: one (device, artifact definition) pair."""

    device: str
    definition: str
    checksum_before: str | None = None
    checksum_after: str | None = None
    storage_id_after: str | None = None
    platform: str | None = None
    role: str | None = None
    region: str | None = None

    @property
    def kind(self) -> Literal["added", "removed", "changed"]:
        if self.checksum_before is None:
            return "added"
        if self.checksum_after is None:
            return "removed"
        return "changed"


class ChangeSet(BaseModel):
    """All artifact-level differences between two branches."""

    base_branch: str
    candidate_branch: str
    items: list[ChangeItem] = Field(default_factory=list)

    @property
    def deployable(self) -> list[ChangeItem]:
        """Added/changed items; removals need a human decision (decommission)."""
        return [i for i in self.items if i.kind != "removed"]

    @property
    def removed(self) -> list[ChangeItem]:
        return [i for i in self.items if i.kind == "removed"]

    @property
    def devices(self) -> list[str]:
        return sorted({i.device for i in self.items})


class RollbackSpec(BaseModel):
    strategy: Literal["commit_confirmed", "commit_confirm", "checkpoint", "manual"]
    confirm_timeout_minutes: int = 10


class Step(BaseModel):
    """One device-level operation for the deployer's executor."""

    device: str
    transport: Literal["gnmi", "netconf", "ssh", "vendor_api"] = "gnmi"
    platform: str | None = None
    artifact_definition: str
    checksum_before: str | None = None
    checksum_after: str
    storage_id: str | None = None
    rollback: RollbackSpec
    abort_on_failure: bool = True


class Gate(BaseModel):
    """Validation checkpoint between stages."""

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
    roles: list[str] = Field(default_factory=list)
    regions: list[str] = Field(default_factory=list)


class PolicyEvaluation(BaseModel):
    canary_strategy: str
    change_window: str = "not_evaluated"
    rate_limits: str = "not_evaluated"


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
    removed_devices: list[str] = Field(
        default_factory=list,
        description="Devices whose artifacts disappeared; requires an explicit "
        "decommission decision, never auto-executed.",
    )
    abort_criteria: list[str] = Field(default_factory=list)

    @staticmethod
    def deterministic_id(source: PlanSource, stages: list[Stage]) -> str:
        """Content-addressed plan ID: same diff + same policy -> same ID."""
        payload = json.dumps(
            {
                "source": source.model_dump(),
                "stages": [s.model_dump() for s in stages],
            },
            sort_keys=True,
        )
        return "plan-" + hashlib.sha256(payload.encode()).hexdigest()[:16]
