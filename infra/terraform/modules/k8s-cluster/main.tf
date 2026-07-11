# GKE Autopilot: node management is not our product; the IBN platform is.
# Swap for a standard cluster only when a concrete requirement forces it
# (e.g. privileged DaemonSets for collectors that Autopilot won't run).

terraform {
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
  }
}

resource "google_container_cluster" "platform" {
  project  = var.project_id
  name     = var.cluster_name
  location = var.region

  enable_autopilot = true
  network          = var.network_id
  subnetwork       = var.subnet_id

  release_channel {
    channel = var.environment == "prod" ? "STABLE" : "REGULAR"
  }

  # Control plane reachable only from the platform VPC + declared ranges.
  private_cluster_config {
    enable_private_nodes = true
  }

  deletion_protection = var.environment == "prod"
}
