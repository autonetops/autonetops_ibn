# infra/terraform

Terraform for the **platform's own infrastructure**: the projects, networks,
clusters and base services that Infrahub, Prefect, the telemetry stack and the
validator run on. (The *network devices* are never touched from here — that is
the deployer's job, driven by Plans.)

## Layout

```
terraform/
  bootstrap/            # run ONCE per org: state bucket + CI service account.
                        # The only stack with local state (then migrated).
  modules/              # reusable building blocks — versioned, no env knowledge
    project/            # project factory: project, APIs, IAM baseline, budgets
    network/            # VPC + subnets + baseline firewall
    k8s-cluster/        # GKE Autopilot cluster
    ibn-platform/       # helm releases: Infrahub, Prefect, observability
  environments/         # one directory per environment — composition only
    lab/
    staging/
    prod/
```

**The rule that keeps this sane:** `modules/` contain *how* to build something;
`environments/` contain only *which* modules with *which* values. If you're
writing a `resource` block inside `environments/`, it belongs in a module.

Cloud mapping: the example uses GCP (**project** = isolation unit). On AWS the
`project` module becomes an *account factory* (Organizations); on Azure, a
*subscription/resource-group factory*. Everything else is unchanged.

## Environment isolation model

Each environment is:

1. **Its own project** (blast radius: quota, IAM, billing, deletion are
   per-env by construction — same philosophy as the IBN layers).
2. **Its own state file** (`env/<name>` prefix in the state bucket): a bad
   `terraform apply` in lab cannot corrupt prod state.
3. **Its own tfvars**: promotion staging → prod is a reviewed diff of values,
   never a code fork (the overlay principle again).

## Getting started

```bash
# 0. One-time, with org-admin credentials
cd bootstrap && terraform init && terraform apply
#    -> creates the state bucket + terraform CI service account

# 1. Bring up the lab environment
cd ../environments/lab
terraform init -backend-config=backend.hcl
terraform plan -var-file=terraform.tfvars
terraform apply
```

> Status: scaffolding — not yet `terraform validate`d against a real org.
> First applies will shake out provider/versions details; pin versions then.

## How this scales (the path, in order)

**Stage 1 — now (1 team, ≤3 envs).** What's in this tree: three environment
dirs, modules referenced by relative path, CI runs fmt/validate/plan on PR
and apply on merge to main (OIDC to the cloud — no long-lived keys in CI).

**Stage 2 — split state by stack (~when applies get slow or scary).**
Inside each environment, split into layered stacks with separate state:
`10-foundation` (project/network) → `20-cluster` → `30-platform` (helm).
Lower layers change rarely; `terraform apply` on the platform layer can no
longer touch the VPC. Wire outputs across stacks with
`terraform_remote_state` or explicit data sources.

**Stage 3 — version the modules (~when >1 consumer per module).** Move
`modules/` refs to tagged git sources
(`source = "git::…//infra/terraform/modules/project?ref=v0.3.0"`), adopt
semver, and a changelog. Environments upgrade deliberately, not implicitly.

**Stage 4 — factories via `for_each` (~when envs/tenants multiply).**
`environments/` stops being copy-paste: a single `tenants.yaml` /
`envs.yaml` map drives `for_each` over the project module (project-per-tenant
for a productized offering). This is the point where per-customer isolated
stacks (dedicated Infrahub + platform per tenant) become one map entry each.

**Stage 5 — orchestration (~>5 envs or >2 teams).** Adopt a TACOS
(Atlantis / Spacelift / env0) or Terragrunt/Terramate for dependency-aware
plans, drift detection schedules, and per-stack RBAC. Do not adopt these
earlier — they solve coordination problems you don't have yet.

**Non-negotiables at every stage:** policy checks in CI (tflint +
checkov/OPA), plan output posted to the PR, no `terraform apply` from
laptops after Stage 1, drift detection (scheduled `plan -detailed-exitcode`)
from Stage 2.
