# The IBN platform itself, as helm releases on an existing cluster.
# This module is cloud-agnostic: it only needs helm/kubernetes providers,
# which the calling environment configures against its cluster.
#
# Chart versions are variables ON PURPOSE: environments pin them in tfvars,
# so "upgrade Infrahub in staging" is a one-line reviewed diff, and prod
# lags staging by construction.

terraform {
  required_providers {
    helm = {
      source  = "hashicorp/helm"
      version = "~> 2.13"
    }
    kubernetes = {
      source  = "hashicorp/kubernetes"
      version = "~> 2.30"
    }
  }
}

resource "kubernetes_namespace" "platform" {
  for_each = toset(["infrahub", "prefect", "telemetry"])

  metadata {
    name = each.value
    labels = {
      "app.kubernetes.io/part-of" = "autonetops-ibn"
    }
  }
}

# Tier-0: the desired-state brain (ADR-0001).
resource "helm_release" "infrahub" {
  name       = "infrahub"
  namespace  = kubernetes_namespace.platform["infrahub"].metadata[0].name
  repository = "https://opsmill.github.io/infrahub-helm"
  chart      = "infrahub"
  version    = var.infrahub_chart_version

  values = [file("${path.module}/values/infrahub.yaml")]
}

# Orchestrator (ADR-0005). Workers deploy separately, per work-pool.
resource "helm_release" "prefect_server" {
  name       = "prefect-server"
  namespace  = kubernetes_namespace.platform["prefect"].metadata[0].name
  repository = "https://prefecthq.github.io/prefect-helm"
  chart      = "prefect-server"
  version    = var.prefect_chart_version

  values = [file("${path.module}/values/prefect-server.yaml")]
}

# Observed-state storage + dashboards; gnmic collectors join this namespace
# (ADR-0006) once collector manifests land in telemetry/collectors/gnmi/.
resource "helm_release" "monitoring" {
  name       = "monitoring"
  namespace  = kubernetes_namespace.platform["telemetry"].metadata[0].name
  repository = "https://prometheus-community.github.io/helm-charts"
  chart      = "kube-prometheus-stack"
  version    = var.kube_prometheus_stack_version

  values = [file("${path.module}/values/monitoring.yaml")]
}
