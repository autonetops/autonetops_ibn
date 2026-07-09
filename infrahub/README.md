# infrahub/

Everything in this directory is **synced into Infrahub** via the root
`.infrahub.yml`. It is the *source* of the schema, compiler and renderer —
it executes inside Infrahub, but it is reviewed, tested and versioned here.

Intent and SoT **data** do not live here; they live in Infrahub itself
(see ADR-0001).

```
infrahub/
  schemas/       # Infrahub schema files (data model for intent + SoT), versioned
  queries/       # GraphQL queries feeding transforms and artifact definitions
  transforms/    # Python transforms = the COMPILER (intent + SoT → normalized data)
  templates/     # Jinja2 templates = the RENDERER (normalized data → vendor config)
    junos/
    iosxr/
    eos/
  generators/    # Infrahub generators (derive objects from intent, e.g. expand a
                 # routing contract into per-device session nodes)
  checks/        # Policy-as-code merge gates that run inside proposed changes
  tests/         # Unit + golden tests for transforms/templates
    golden/      # "this intent must render exactly this artifact" fixtures
```

## Design rules

1. **Transforms stay vendor-neutral.** Vendor knowledge belongs in
   `templates/<vendor>/` only. Adding a platform must never touch intent or
   transform logic.
2. **Every config artifact has a sibling expectation artifact.** "We can
   configure it" without "we can prove it works" is not done.
3. **Golden tests are mandatory** for every transform/template pair. A diff in
   golden output is a production-affecting change and must be acknowledged
   explicitly in review.
4. **Checks are safety, not lint.** IPAM bounds, invariant removal, redundancy
   floors, capability declarations — organizational safety encoded as code.
