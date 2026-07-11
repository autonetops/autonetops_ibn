"""Data models for the executor verb contract (ADR-0011).

Everything crossing the executor boundary is serializable (pydantic): the API
is designed as if remote from day one, so promotion to a device-gateway
service (ADR-0009) is mechanical.
"""

from __future__ import annotations

import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class Protocol(str, Enum):
    GNMI = "gnmi"
    NETCONF = "netconf"
    EAPI = "eapi"
    JSON_RPC = "json_rpc"
    HTTP_API = "http_api"
    CLI = "cli"


class Transactionality(str, Enum):
    NONE = "none"
    PER_CHANGE = "per_change"  # each apply is atomic on the target
    PER_SESSION = "per_session"  # candidate datastore + explicit commit


class Atomicity(str, Enum):
    PER_DEVICE = "per_device"
    DOMAIN = "domain"  # controllers: one apply converges the whole domain


class CapabilityMatrix(BaseModel):
    """Declared by every driver; consumed by the planner to choose delivery
    and rollback strategies (ADR-0011/0012)."""

    transactional: Transactionality
    supports_dry_run: bool
    supports_confirm: bool
    supports_snapshot: bool
    atomicity: Atomicity
    protocols: list[Protocol] = Field(
        description="Supported protocols in this driver's preferred order for config delivery."
    )


class ArtifactPayload(BaseModel):
    """A rendered artifact as handed to a driver: content + identity."""

    definition: str
    checksum: str
    content: str


class Evidence(BaseModel):
    """Every verb returns evidence. No evidence, no operation."""

    operation: str
    target: str
    driver: str
    protocol: Protocol
    started_at: str
    finished_at: str
    success: bool
    detail: dict[str, Any] = Field(default_factory=dict)


class FactsResult(BaseModel):
    evidence: Evidence
    facts: dict[str, Any] = Field(default_factory=dict)


class DiffResult(BaseModel):
    evidence: Evidence
    changed: bool
    diff: str = ""


class Snapshot(BaseModel):
    evidence: Evidence
    snapshot_id: str
    checksum: str


class PendingChange(BaseModel):
    """Result of apply(): a change that may still need confirm(), and that
    rollback() can target while the driver's rollback window is open."""

    evidence: Evidence
    change_id: str
    rollback_strategy: str
    confirm_deadline_seconds: int | None = None  # None = no confirm required


def utc_now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="milliseconds")
