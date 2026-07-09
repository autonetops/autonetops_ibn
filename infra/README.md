# infra/

Deployment of the **platform itself** — Infrahub, planner, deployer, telemetry
stack, validator. Networks are configured by this platform; this directory
configures the platform.

```
infra/
  compose/           # local/lab stack: Infrahub + platform services + containerlab
  helm/              # one chart (or subchart) per platform component
  terraform/         # clusters, IAM, storage, secrets backends
  kustomize/         # environment overlays for k8s manifests
```

## Intended promotion path (to be confirmed — ADR backlog)

1. **Lab**: docker compose (Infrahub + services) + containerlab on one host.
2. **Staging/prod**: Kubernetes via helm + kustomize overlays; Infrahub
   treated as tier-0 (backup/restore runbook required before go-live).

## Notes

- Device credentials and Infrahub tokens are injected via the secrets backend
  (design pending); nothing secret is ever committed here.
- Telemetry storage sizing and retention are part of this layer's design.
