# Bootstrap: the one stack allowed to start with local state.
# Creates the remote-state bucket and the CI identity, then its own state is
# migrated into the bucket (`terraform init -migrate-state`).

terraform {
  required_version = ">= 1.7"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
  }
}

provider "google" {
  project = var.seed_project_id
  region  = var.region
}

resource "google_storage_bucket" "tfstate" {
  name                        = "${var.org_slug}-ibn-tfstate"
  location                    = var.region
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"

  versioning {
    enabled = true
  }
}

# CI identity: GitHub Actions authenticates via Workload Identity Federation
# (OIDC) — no exported keys, ever.
resource "google_service_account" "terraform_ci" {
  account_id   = "terraform-ci"
  display_name = "Terraform CI (IBN platform)"
}

resource "google_storage_bucket_iam_member" "ci_state_access" {
  bucket = google_storage_bucket.tfstate.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.terraform_ci.email}"
}
