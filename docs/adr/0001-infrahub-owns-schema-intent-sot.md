# 0001 — Infrahub owns schema, intent, SoT, compiler and renderer

- Status: accepted
- Date: 2026-07-09

## Context

An IBN platform needs a home for schemas, intent, source of truth, and the
compile/render pipeline. The classic reference layout keeps all of these as
files in the monorepo (`schemas/`, `intent/`, `sot/`, `compiler/`,
`renderers/`). We already operate Infrahub, which natively provides:

- A versioned, schema-driven graph database for intent + SoT.
- Branches and proposed changes (review workflow on *data*, not just files).
- Repository sync: schemas, GraphQL queries, Python transforms, Jinja2
  templates, generators and checks loaded from Git.
- Artifact generation with storage and checksums.

## Decision

Infrahub is the system of record for schema, intent, and SoT. The compiler
(transforms) and renderer (templates) are Infrahub artifacts-pipeline code.
Their *source* still lives in this repo under `infrahub/` (synced via
`.infrahub.yml`), so it remains reviewable, testable, and versioned in Git —
but it executes inside Infrahub.

Consequently this repo does **not** contain `intent/` or `sot/` data
directories. Intent is data in Infrahub; environment differences are Infrahub
branches/overlays, not file forks.

The layers Infrahub does not provide — planner, deployer, telemetry,
validator, simulations — are first-class components of this repo and consume
Infrahub only through its API and artifacts.

## Consequences

- ✅ One review workflow (proposed changes) covers intent *and* the pipeline
  code that renders it.
- ✅ No file-based intent/SoT drift; snapshots for reproducibility come from
  Infrahub's own versioning + artifact checksums.
- ⚠️ Infrahub availability becomes critical-path for the whole loop; infra
  design must treat it as tier-0.
- ⚠️ Golden/regression tests for transforms and templates must be runnable in
  CI *outside* a live Infrahub (fixture-driven), or against an ephemeral
  Infrahub instance — to be decided when the first transform lands.
