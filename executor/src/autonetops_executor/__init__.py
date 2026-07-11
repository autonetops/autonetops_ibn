"""AutoNetOps IBN execution layer.

The only component that touches the network (ADR-0010). Drivers implement a
fixed verb contract and declare capabilities (ADR-0011); the orchestrator and
ibnctl consume this package only through its public API (ADR-0009) — no
Prefect imports exist or may be added here.
"""

from .driver import BaseDriver, available_drivers, capability_report, get_driver_class, register
from .models import (
    ArtifactPayload,
    Atomicity,
    CapabilityMatrix,
    DiffResult,
    Evidence,
    FactsResult,
    PendingChange,
    Protocol,
    Snapshot,
    Transactionality,
)

# Importing the drivers package registers the built-in drivers.
from . import drivers as _drivers  # noqa: F401  (registration side effect)

__version__ = "0.1.0"

__all__ = [
    "ArtifactPayload",
    "Atomicity",
    "BaseDriver",
    "CapabilityMatrix",
    "DiffResult",
    "Evidence",
    "FactsResult",
    "PendingChange",
    "Protocol",
    "Snapshot",
    "Transactionality",
    "available_drivers",
    "capability_report",
    "get_driver_class",
    "register",
]
