# playbooks/

What happens when a verification fails or the validator classifies dangerous
drift — organized by remediation class, strictest path first:

- `safe_fixes/` — deterministic, reversible, pre-approved actions. The only
  auto-proposable class, and even then: a safe fix **proposes a Plan**
  (through the planner, with blast radius and approval rules) — it never
  pushes directly. Canonical example: re-deploy the authoritative artifact
  over out-of-band drift.
- `quarantines/` — contain without touching: mark the control point
  non-compliant in Infrahub, freeze further plans targeting it, capture
  evidence bundles, open a ticket. Used when the fix is unclear or the drift
  is dangerous.
- `escalations/` — human-required: paging policy, who owns which domain
  (mirrors CODEOWNERS), and the context bundle a human needs to act in five
  minutes (what failed, evidence, blast radius, last plans touching the
  target).

A playbook declares: triggering classes, preconditions, actions, rollback of
the remediation itself, and its own verification (a remediation that can't be
verified is an incident generator).
