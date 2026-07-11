# 0011 — Southbound target model: control points and driver capabilities

- Status: accepted
- Date: 2026-07-11
- Refines: ADR-0008 (library choices stand; the abstraction above them is defined here)

## Context

The network is not just NOS boxes we SSH into. Three southbound classes must
coexist in one architecture:

1. **Direct NOS** — we own the transaction per device (Junos commit-confirmed,
   XR commit, EOS checkpoint) over gNMI/NETCONF/SSH.
2. **API vendors** — the platform exposes a structured API per device or per
   cloud tenant (eAPI, RESTCONF, Mist/Meraki-style cloud APIs); transactions
   are whatever the API gives us, often nothing.
3. **Controller-based** — one endpoint (Apstra, CloudVision, NSO, ACI,
   Panorama…) manages N devices. The push target is the controller; the
   *blast radius* is the managed devices; rollback is the controller's
   revision/snapshot model; the controller may apply changes domain-atomically.

A device-centric Plan ("step = one device") cannot express class 3, and
retrofitting it after drivers exist would be a contract break across every
layer. This is the moment to fix the model.

## Decision 1 — The unit of execution is a control point, not a device

SoT (Infrahub) models every managed endpoint as a **control point**:

```
control_point:
  name: apstra-fabric-gig          # or pe1-gru for a direct device
  kind: direct | api | controller
  managed_devices: [...]           # == [self] for direct/api-per-device
```

Consequences through the stack:

- **Artifacts** are rendered per control point: device config (direct),
  API payload (api), controller intent document (controller). Same artifact
  contract — definition, checksum, storage id — regardless of kind.
- **Plan steps** target a control point and carry `affected_devices`.
- **Blast radius** is computed over the union of affected devices — a
  one-step controller change to 40 leaves is a 40-device change and hits the
  approval bar accordingly.
- **Expectations/validation** remain per *device* (the truth lives in the
  network), regardless of how the change was pushed. This is what catches a
  controller that claims success but didn't converge.

## Decision 2 — Executor verbs + driver capability matrix

The executor exposes a small, fixed verb set; **drivers** implement it per
platform, composing shared **transports** (gnmi/netconf/ssh/http):

```
verbs:    get_facts | snapshot | dry_run -> Diff | apply -> PendingChange
          | confirm | rollback        (each returns structured Evidence)

capabilities (declared by each driver, mirrored in SoT capabilities schema):
  transactional:      none | per_change | per_session
  supports_dry_run:   bool          # diff without touching running state
  supports_confirm:   bool          # auto-revert unless confirmed
  supports_snapshot:  bool
  atomicity:          per_device | domain     # controllers are usually domain
```

**The planner consumes capabilities to choose strategies** — this is the key
coupling that keeps one architecture over heterogeneous southbounds:

| Capability profile | Planner strategy |
|---|---|
| `supports_confirm` (Junos-class) | commit-confirmed with timer as rollback |
| dry-run but no confirm (EOS-class) | pre-snapshot → apply → validate → revert-on-fail |
| no dry-run, no transaction (bare API) | mandatory simulation gate before merge + snapshot-revert |
| `atomicity: domain` (controller) | step cannot be split by device — see canary note |

**Canary through a controller** requires slicing the *intent scope* (render a
controller artifact covering a subset of its devices), not picking devices at
deploy time. Until intent-scope slicing exists in the compiler, controller
steps are single-shot and their full `affected_devices` inflates blast radius
— which forces the high-blast-radius approval path. Safe by default, honest
about the limitation.

## Decision 3 — Initial drivers and evolution path

Phase 1 (prove the verb set across all three transports, free lab images):

| Driver | Kind | Transport | Why |
|---|---|---|---|
| `nokia_srlinux` | direct | gNMI | gNMI-native, free in containerlab — CI workhorse |
| `juniper_junos` | direct | NETCONF | commit-confirmed = the transactional gold standard |
| `arista_eos` | direct | eAPI/gNMI | exercises the api-style path + checkpoints |

Phase 2: first cloud/API-vendor driver — chosen by what actually enters SoT.
Phase 3: first controller driver — the contract is ready for it from day one;
selection driven by the estate (Apstra/CloudVision/NSO/…).

A driver is "done" only with: capability declaration, evidence for every verb,
integration tests against containerlab (or a recorded API fixture for
cloud/controller drivers), and a golden expectation set in simulations/.

## Consequences

- Plan contract v1 (still pre-release, no consumers) is amended: `Step.target`
  = {control_point, kind, affected_devices}; `driver` replaces transport;
  rollback strategy becomes a driver-declared string. Schema regenerated.
- Infrahub schema work: `control_point` kind + capability attributes join the
  SoT schema backlog (`infrahub/schemas/`).
- ADR-0008's library picks live *inside* drivers; a controller driver is just
  a driver whose transport is `http`.
