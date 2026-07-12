"""ibnctl — the break-glass Plan runner (ADR-0003/0009).

Walks an approved Plan stage by stage, calling the executor verb contract
per step: snapshot -> dry_run (when the driver supports it) -> apply ->
rollback on failure. Every verb result is appended to an evidence JSONL
file; no evidence, no operation.

The production path is the Prefect orchestrator (orchestrator/flows/deploy);
ibnctl is the human-driven equivalent - same Plan, same executor, same
evidence - for labs and emergencies.
"""

from .cli import main

__all__ = ["main"]
