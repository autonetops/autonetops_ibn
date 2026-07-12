"""Validator models: expectations in, verdicts out.

The input contract is the ContractExpectations artifact the SoT compiles
(apiVersion expectations.networking.autonetops/v1). The validator never
talks to a device: callers collect facts through the executor's verb
contract and hand them over - expectations are evaluated per DEVICE
regardless of how a change was pushed (ADR-0011).
"""

from __future__ import annotations

from typing import Any

import yaml
from pydantic import BaseModel, Field


class SessionExpectation(BaseModel):
    """One BGP session that must be established if the intent holds."""

    contract: str
    device: str
    neighbor_ip: str
    neighbor_device: str | None = None
    must_state: str = "established"


class ExpectationSet(BaseModel):
    """Everything a set of ContractExpectations artifacts demands."""

    sessions: list[SessionExpectation] = Field(default_factory=list)

    @classmethod
    def from_artifacts(cls, documents: list[str]) -> "ExpectationSet":
        """Parse rendered contract-expectations YAML documents."""
        sessions: list[SessionExpectation] = []
        for text in documents:
            doc = yaml.safe_load(text) or {}
            contract = (doc.get("metadata") or {}).get("name") or "unknown"
            bgp = ((doc.get("spec") or {}).get("bgp") or {})
            for session in bgp.get("sessions") or []:
                sessions.append(SessionExpectation(
                    contract=contract,
                    device=session["device"],
                    neighbor_ip=session["neighborIp"],
                    neighbor_device=session.get("neighborDevice"),
                    must_state=(session.get("mustBe") or {}).get(
                        "sessionState", "established"),
                ))
        return cls(sessions=sessions)

    def for_devices(
        self, devices: set[str], include_neighbors: bool = False
    ) -> "ExpectationSet":
        """Expectations touching these devices. With include_neighbors, a
        session OBSERVED elsewhere but terminating on one of them counts
        too - changing a CE is proven on the PE that faces it."""
        return ExpectationSet(sessions=[
            s for s in self.sessions
            if s.device in devices
            or (include_neighbors and s.neighbor_device in devices)
        ])


class CheckResult(BaseModel):
    """One expectation, one verdict. ``unverifiable`` is its own status:
    a session nobody could observe must never count as passing.
    ``pre_existing`` marks a failure that predates the change being gated -
    reported drift, not a rollout regression."""

    contract: str
    device: str
    neighbor_ip: str
    expected: str
    actual: str | None = None
    status: str  # pass | fail | pre_existing | unverifiable


class GateResult(BaseModel):
    checks: list[CheckResult] = Field(default_factory=list)
    detail: dict[str, Any] = Field(default_factory=dict)

    @property
    def passed(self) -> bool:
        """No failures. Unverifiable checks do not fail the gate, but they
        are reported loudly - silence is the one thing evidence can't be."""
        return all(c.status != "fail" for c in self.checks)

    @property
    def summary(self) -> str:
        counts: dict[str, int] = {}
        for check in self.checks:
            counts[check.status] = counts.get(check.status, 0) + 1
        parts = [f"{v} {k}" for k, v in sorted(counts.items())]
        return ", ".join(parts) if parts else "no checks"
