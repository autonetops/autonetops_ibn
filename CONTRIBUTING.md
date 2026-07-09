# Contributing

## Ground rules

1. **Respect the boundaries.** Each top-level directory has a README stating
   its contract and non-responsibilities. If your change needs to cross a
   boundary, the contract changes first (docs + ADR), then the code.
2. **No quick fixes in random directories.** If something doesn't have a home,
   that's a design discussion, not an excuse.
3. **Decisions get ADRs.** Anything non-obvious or hard to reverse →
   `docs/adr/`.
4. **Policies are data.** Change windows, canary strategies, rate limits and
   remediation classes are YAML under review — never hardcoded.
5. **Production-affecting ≠ touches prod files.** A transform/template change
   in `infrahub/` re-renders configs for existing intent. Golden tests exist
   to make that visible; a golden diff must be explicitly acknowledged.

## Workflow

- Branch from `main`, open a PR. CI gates are defined in `.github/workflows/`.
- CODEOWNERS maps directories to domain owners; blast-radius-sensitive paths
  require the corresponding owners' approval.
- Intent/SoT data changes do **not** happen in this repo — they happen in
  Infrahub via branches + proposed changes (see ADR-0001).

## Language / tooling decisions

Implementation language(s), package layout and lint/test tooling for
planner/deployer/validator are pending the design discussion — see the ADR
backlog in `docs/adr/README.md`. Until then, avoid adding build scaffolding.
