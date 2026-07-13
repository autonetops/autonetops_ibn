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

## Runbook: fully private setup (private repo + private registry)

The sequence below was validated end-to-end on 2026-07-14 against a local
styrmin vcluster and is written to be reusable for any private project with a
private image. Substitute `<app>` (driver/chart/deployment name), `<org>`
(GitHub org), and `<ns>` (styrmin's own namespace, usually `styrmin`).

**Prerequisites**: a GitHub PAT with `repo` read (for the driver clone) and
`read:packages`/`write:packages` (for GHCR); `kubectl` pointed at the styrmin
cluster; the styrmin admin credentials.

1. **Publish image and chart** (both may stay private):

   ```shell
   docker build -t ghcr.io/<org>/<app>:<version> .
   docker push ghcr.io/<org>/<app>:<version>
   helm registry login ghcr.io -u <user> --password-stdin   # paste the PAT
   helm package <chart-dir>
   helm push <app>-<version>.tgz oci://ghcr.io/<org>/charts
   ```

2. **Give the styrmin server the git token** — `load-version` clones on the
   server, there are no client-side credential flags. In the bundled chart the
   token lives in the `styrmin-secrets` Secret under the `driver-token` key
   (it exists but is *empty* by default — this yields the misleading
   "credentials" failure on load):

   ```shell
   kubectl -n <ns> patch secret styrmin-secrets \
     -p '{"stringData":{"driver-token":"<github-PAT>"}}'
   kubectl -n <ns> rollout restart deploy styrmin-server
   ```

3. **Load the driver** (`driver.styrmin.yml` must be at the repo root; each
   load pins the branch-tip commit as an immutable driver version — reload
   after every push you want picked up). Non-interactive auth is env-var
   based:

   ```shell
   export STYRMIN_SERVER_ADDRESS=http://styrmin.local.styrmin.io:8080
   export STYRMIN_USERNAME=admin STYRMIN_PASSWORD=<admin-password>
   uv run styrminctl drivers load-version https://github.com/<org>/<app> main
   ```

4. **Pre-create the chart-pull credential** in styrmin's namespace (used in
   step 6):

   ```shell
   kubectl -n <ns> create secret docker-registry ghcr-auth \
     --docker-server=ghcr.io --docker-username=<user> --docker-password=<PAT>
   ```

5. **Create the deployment** via a manifest so parameters and env vars go in
   one shot (`styrminctl deployments apply -f deploy.yaml`):

   ```yaml
   apiVersion: styrmin/v1
   kind: Deployment
   metadata:
     name: <app>
   spec:
     driver: <app>
     version: "<version>"
     environment: <environment-name>
     config:
       envVars:
         - name: INFRAHUB_API_TOKEN
           value: "<token>"
     parameters:
       infrahub_address: "https://<your-infrahub>"
       sot_repo_url: "https://github.com/<org>/<sot-repo>"
       sot_repo_ref: "main"
       image_pull_secret: "ghcr-pull"
   ```

6. **Patch the Flux HelmRepository with the chart credential.** Styrmin
   templates the `HelmRepository` *without* `secretRef` (no private-OCI
   support upstream — `services/helm/templates/repository_spec.j2`), so the
   chart pull fails with `401 Unauthorized` until you patch it. The patch
   also triggers an immediate retry:

   ```shell
   kubectl -n <ns> get helmrepositories        # find the styrmin-<uuid> name
   kubectl -n <ns> patch helmrepository styrmin-<uuid> --type=merge \
     -p '{"spec":{"secretRef":{"name":"ghcr-auth"}}}'
   ```

   ⚠️ The patch lives on an operator-owned object: a future deployment
   update may recreate the HelmRepository without it. Re-check on upgrade.

7. **Create the image-pull secret in the deployment's namespace.** Styrmin
   creates one namespace per deployment, named `styrmin-<deployment-uuid>`
   (it appears seconds after step 5; an early `ImagePullBackOff` self-heals
   once the secret exists):

   ```shell
   kubectl get ns | grep styrmin-        # find the deployment namespace
   kubectl -n styrmin-<deployment-uuid> create secret docker-registry ghcr-pull \
     --docker-server=ghcr.io --docker-username=<user> --docker-password=<PAT>
   ```

8. **Verify the chain** — each link, in order:

   ```shell
   kubectl -n <ns> get helmcharts              # READY True, "pulled ... chart"
   kubectl -n styrmin-<deployment-uuid> get helmrelease,pods
   kubectl -n styrmin-<deployment-uuid> logs -l app.kubernetes.io/name=<app> --tail=20
   ```

   Note: the HelmRelease may keep showing a *stale* chart-pull error for a
   minute after step 6 — trust the HelmChart's own status, not the
   HelmRelease message.

To update the running deployment later (new env var, parameter, version),
edit the manifest and re-run `styrminctl deployments apply -f deploy.yaml` —
config changes roll the pod automatically.

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
