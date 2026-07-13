# Deploying the IBN platform through Styrmin

[Styrmin](https://github.com/opsmill/styrmin) is OpsMill's deployment
orchestration platform for Kubernetes applications. It deploys, upgrades and
backs up applications through **Application Drivers** — versioned deployment
specifications loaded from git repositories. Styrmin already ships a driver
for Infrahub, so a Styrmin cluster can run the full stack this platform needs:
Infrahub (the desired-state brain) plus this repo's orchestrator (the closed
loop around it).

This repository is loadable as a Styrmin driver. Do not confuse the two uses
of the word *driver*: Styrmin's **ApplicationDriver** (how Styrmin deploys
this platform, defined at the repo root) is unrelated to the executor's
southbound **NOS/API drivers** (`executor/`, ADR-0010/0011).

## The pieces

| Artifact | Where | Purpose |
|---|---|---|
| `driver.styrmin.yml` | repo root | Styrmin driver spec: component (orchestrator), parameters, env vars, container overrides. Must be at the repo root for git-loaded drivers. |
| `values.j2.yml` | repo root | Jinja2 template Styrmin renders into Helm values (image tag, Infrahub address, SoT repo, storage class). |
| `infra/helm/autonetops-ibn/` | this repo | Helm chart deploying the orchestrator reconcile service (`ibn-orchestrate watch`). |
| `Dockerfile` | repo root | Container image with all five workspace packages installed; entrypoint `ibn-orchestrate`, default command `watch --interval 15`. |
| `pyproject.toml` + `uv.lock` | repo root | uv workspace tying the five packages together so the image build resolves sibling dependencies locally. |

What gets deployed is deliberately minimal today: **one component**, the
orchestrator running the `watch` reconcile loop — the platform's only
long-running service per `docs/architecture/runtime-topology.md`. Planner,
executor and validator are libraries inside the same image. As Prefect flows
land in `orchestrator/flows/`, they become additional components or Styrmin
driver actions.

## One-time publishing

Styrmin pulls the chart from an OCI/HTTP location and the image from a
registry; neither is read from the git checkout. Publish both (adjust
registry/owner to taste, then update `driver.styrmin.yml` and
`values.j2.yml` to match):

```shell
# Image
docker build -t ghcr.io/autonetops/autonetops-ibn:0.1.0 .
docker push ghcr.io/autonetops/autonetops-ibn:0.1.0

# Chart
helm package infra/helm/autonetops-ibn        # -> autonetops-ibn-0.1.0.tgz
helm push autonetops-ibn-0.1.0.tgz oci://ghcr.io/autonetops/charts
```

The image tag doubles as the *application version* in Styrmin: the driver's
`supported_versions` range (`>=0.1,<1.0`) must cover it, and `values.j2.yml`
sets `image.tag: {{ app.version }}`.

## Private repository and registry

This repo and its GHCR packages are private, which affects all three pull
paths:

- **Driver load (git)**: `styrminctl drivers load-version` clones on the
  *server* side; there are no client-side credential flags. The Styrmin
  server must hold a GitHub token with read access to this repo in
  `STYRMIN_DRIVER_TOKEN` — in the bundled Styrmin Helm chart it is read from
  a Kubernetes Secret in the `styrmin` namespace, created before
  `helm upgrade --install`. Until that's configured, use the local
  alternative: mount/copy the three driver files into the server container
  and run `styrminctl drivers load-local-version <in-container-path>`.
- **Chart pull (OCI)**: the Styrmin server resolves
  `spec.helm.main.location` itself. Either make the
  `ghcr.io/autonetops/charts/autonetops-ibn` package public, or configure the
  server's Helm registry credentials accordingly.
- **Image pull (Kubernetes)**: the kubelet needs credentials for
  `ghcr.io/autonetops/autonetops-ibn`. Either make the package public, or
  create a docker-registry Secret in the deployment's namespace and pass its
  name through the `image_pull_secret` driver parameter (chart value
  `imagePullSecrets`).

The no-credentials path is to make both GHCR packages public
(GitHub → Package settings → Change visibility); the git repo itself can
stay private once `STYRMIN_DRIVER_TOKEN` is set.

## Loading the driver and deploying

```shell
# Load this repo as a driver (driver.styrmin.yml is read from the repo
# root; requires STYRMIN_DRIVER_TOKEN on the server — see above)
styrminctl drivers load-version https://github.com/autonetops/autonetops_ibn main

# Create a deployment of application version 0.1.0
styrminctl deployments create autonetops-ibn 0.1.0 <environment-id>
```

Deployment-time knobs:

- **Parameters** (shown in the Styrmin UI): `infrahub_address` (defaults to
  `http://styrmin-infrahub:8000`, the address of a Styrmin-deployed Infrahub in
  the same namespace), `sot_repo_url` / `sot_repo_ref` (the Infrahub-synced SoT
  repository; when set, an init container clones it to `IBN_SOT_REPO` before
  the orchestrator starts).
- **Env vars** (deployment-level, reach the container via `extraEnv`):
  `INFRAHUB_API_TOKEN` (required for the watch loop to talk to Infrahub),
  `IBN_POLICIES_DIR` (optional override of the planner policy set baked into
  the image at `/app/planner/policies`).
- **Container overrides**: the orchestrator container's `command`/`args` can be
  overridden per deployment, e.g. to change the poll interval
  (`args: ["watch", "--interval", "60"]`).

## Using the chart without Styrmin

The chart is a normal Helm chart and works standalone:

```shell
helm install ibn infra/helm/autonetops-ibn \
  --set image.tag=0.1.0 \
  --set infrahub.address=http://infrahub:8000 \
  --set infrahub.existingTokenSecret.name=infrahub-token \
  --set sotRepo.gitUrl=https://github.com/autonetops/autonetops_infrahub \
  --set persistence.enabled=true
```

## Known limitations

- The plans directory (`/data/plans`) is a PVC, not a git remote: the
  plans-as-PRs review flow (ADR-0003) still happens in git/CI; the deployed
  watch loop only consumes approved plan bundles it finds in its plans dir.
  Wiring the container to a plans git remote is future work.
- No Styrmin `backup` block yet — plan bundles are reproducible from the SoT
  repo plus git history, so nothing irreplaceable lives in the PVC.
- No driver `actions` yet. Upgrades are plain Helm upgrades; if a future
  version needs sequencing (e.g. drain the watch loop before swapping images),
  add an `actions.py` with Prefect flows and declare them in
  `driver.styrmin.yml`.
- Private SoT repositories are not yet supported by the clone init container
  (no credential wiring).
