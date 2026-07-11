# 0009 — Deployer split: two packages now, executor service later if needed

- Status: accepted
- Date: 2026-07-11

## Context

ADR-0005 separated orchestration (Prefect flows) from execution (library) as
*directories*. The follow-up question: should they be separated harder —
distinct packages, or even a standalone executor service?

There are three separation levels:

1. **Modules in one package** — cheap, but nothing stops a flow importing
   adapter internals; the boundary is convention.
2. **Two Python packages** — `autonetops-executor` (pure library:
   adapters + rollback + evidence models) and `autonetops-deployer-flows`
   (Prefect flows) that depends on the executor **only through its public
   API**. The boundary becomes a dependency edge: enforceable, versionable,
   independently releasable and testable.
3. **Executor as a service** (device gateway, gRPC/REST) — flows call over
   the network; the gateway owns device credentials, connection pooling, and
   global per-device session limits.

## Decision

**Level 2 now.** Two packages inside `deployer/`:

```
deployer/
  executor/    # package: autonetops-executor  (no Prefect imports — enforced by lint/CI)
  flows/       # package: autonetops-deployer-flows  (depends on autonetops-executor)
```

**Level 3 is deferred, with explicit promotion triggers** (any one suffices):

- Credential isolation: flows must run where device credentials must not
  exist (multi-tenant product, customer-run workers).
- A non-Python caller needs device operations.
- Global coordination: per-device session brokering / rate limiting across
  *multiple* concurrent plans, which a library cannot enforce process-wide.
- Compliance demands a single audited chokepoint for all device writes.

Because flows already consume only the executor's public API, promotion to a
service is mechanical: the API grows a transport (gRPC), flows swap an import
for a client. Nothing else moves.

## Consequences

- `ibnctl` break-glass and adapter integration tests depend on
  `autonetops-executor` alone — no Prefect anywhere near them.
- CI adds an import-boundary check (no `prefect` in executor's dependency
  tree).
- The executor's public API must be designed as if remote from day one:
  serializable inputs/outputs (pydantic), no leaking of live connection
  objects across the boundary.
