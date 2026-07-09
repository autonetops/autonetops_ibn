# Runbooks

Operational procedures. A runbook exists **before** the component ships to
production, not after the first incident.

Planned set (stubs are created as components land):

- `deployer.md` — operating the deployer: pausing rollouts, resuming, manual
  rollback per vendor, credential rotation.
- `validator.md` — interpreting drift classes, clearing quarantines, tuning
  noisy rules.
- `emergency-changes.md` — the sanctioned break-glass path and the backport
  obligation (see docs/architecture/data-flows.md, Flow 3).
- `schema-migrations.md` — how to evolve Infrahub schemas safely.
- `infrahub-recovery.md` — Infrahub is tier-0 for this platform; backup and
  restore procedures.
