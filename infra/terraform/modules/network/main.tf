# Platform VPC. Deliberately minimal: one VPC, one subnet per declared
# region, deny-by-default posture (GCP implied rules + explicit IAP SSH).
# Grows into Shared VPC / hub-spoke at scale — see infra/terraform/README.md.

terraform {
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
  }
}

resource "google_compute_network" "platform" {
  project                 = var.project_id
  name                    = var.network_name
  auto_create_subnetworks = false
}

resource "google_compute_subnetwork" "regional" {
  for_each = var.subnets

  project                  = var.project_id
  name                     = "${var.network_name}-${each.key}"
  region                   = each.key
  network                  = google_compute_network.platform.id
  ip_cidr_range            = each.value
  private_ip_google_access = true
}

resource "google_compute_firewall" "allow_iap_ssh" {
  project = var.project_id
  name    = "${var.network_name}-allow-iap-ssh"
  network = google_compute_network.platform.name

  allow {
    protocol = "tcp"
    ports    = ["22"]
  }

  # Google IAP range — operator SSH goes through IAP, never the open internet.
  source_ranges = ["35.235.240.0/20"]
}
