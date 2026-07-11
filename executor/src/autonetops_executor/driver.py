"""The driver contract: fixed verb set + capability declaration + registry.

A driver is "done" only with: capability declaration, evidence for every verb,
and integration tests (containerlab or recorded API fixtures). See ADR-0011.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, ClassVar

from .exceptions import UnknownDriver, UnsupportedCapability
from .models import (
    ArtifactPayload,
    CapabilityMatrix,
    DiffResult,
    Evidence,
    FactsResult,
    PendingChange,
    Protocol,
    Snapshot,
    utc_now_iso,
)


class BaseDriver(ABC):
    """One instance = one control point. One verb call = one operation;
    concurrency and ordering belong to the Plan + orchestrator."""

    name: ClassVar[str]
    capabilities: ClassVar[CapabilityMatrix]

    def __init__(self, target: str, connection: dict[str, Any] | None = None):
        self.target = target
        self.connection = connection or {}

    # -- verb contract -------------------------------------------------------

    @abstractmethod
    def get_facts(self) -> FactsResult: ...

    @abstractmethod
    def snapshot(self) -> Snapshot: ...

    @abstractmethod
    def dry_run(self, artifact: ArtifactPayload) -> DiffResult: ...

    @abstractmethod
    def apply(self, artifact: ArtifactPayload) -> PendingChange: ...

    @abstractmethod
    def confirm(self, change_id: str) -> Evidence: ...

    @abstractmethod
    def rollback(self, reference: str) -> Evidence:
        """Roll back a pending/committed change (change_id) or restore a
        snapshot (snapshot_id), per the driver's declared strategy."""
        ...

    # -- helpers for implementations -----------------------------------------

    def _require(self, capability: str) -> None:
        if not getattr(self.capabilities, capability):
            raise UnsupportedCapability(
                f"driver {self.name!r} does not declare {capability}"
            )

    def _evidence(
        self,
        operation: str,
        started_at: str,
        success: bool,
        protocol: Protocol | None = None,
        **detail: Any,
    ) -> Evidence:
        return Evidence(
            operation=operation,
            target=self.target,
            driver=self.name,
            protocol=protocol or self.capabilities.protocols[0],
            started_at=started_at,
            finished_at=utc_now_iso(),
            success=success,
            detail=detail,
        )


# -- registry -----------------------------------------------------------------

_REGISTRY: dict[str, type[BaseDriver]] = {}


def register(cls: type[BaseDriver]) -> type[BaseDriver]:
    """Class decorator: @register on every driver."""
    _REGISTRY[cls.name] = cls
    return cls


def get_driver_class(name: str) -> type[BaseDriver]:
    try:
        return _REGISTRY[name]
    except KeyError as exc:
        raise UnknownDriver(f"no driver registered as {name!r}") from exc


def available_drivers() -> list[str]:
    return sorted(_REGISTRY)


def capability_report() -> dict[str, CapabilityMatrix]:
    """The publishable registry: what the planner (and eventually SoT
    capability records in Infrahub) consume to pick strategies."""
    return {name: cls.capabilities for name, cls in sorted(_REGISTRY.items())}
