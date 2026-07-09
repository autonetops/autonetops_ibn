# 0007 — Python as the platform implementation language

- Status: accepted
- Date: 2026-07-09

## Context

Planner, deployer (executor + flows), validator, and tools need a language.
Infrahub transforms are already Python; Prefect (ADR-0005) is Python-native;
the network-automation ecosystem (infrahub-sdk, pygnmi, ncclient, scrapli)
is Python-first.

## Decision

**Python ≥ 3.11** for all platform components.

Conventions (evolve via CONTRIBUTING, not per-package drift):

- One package per component, `src/` layout: `planner/src/autonetops_planner/`,
  `deployer/src/autonetops_deployer/`, `validator/src/autonetops_validator/`.
- **pydantic v2** models are the canonical form of every cross-layer contract;
  JSON Schemas under `contracts/` are *generated* from them, committed, and
  CI-checked for drift.
- pytest for tests; ruff for lint/format.

## Consequences

- Single toolchain across Infrahub transforms and platform code — the same
  engineers can work both sides of the artifact boundary.
- Contract-first discipline is enforced mechanically (schema export check).
