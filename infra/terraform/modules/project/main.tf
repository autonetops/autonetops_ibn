# Project factory: every environment (and later, every tenant) is born from
# this module — same APIs, same IAM baseline, same budget guardrails.
# AWS equivalent: account factory; Azure: subscription/resource-group factory.

terraform {
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
  }
}

resource "google_project" "this" {
  name            = var.display_name
  project_id      = var.project_id
  folder_id       = var.folder_id
  billing_account = var.billing_account
  deletion_policy = var.environment == "prod" ? "PREVENT" : "DELETE"

  labels = {
    platform    = "autonetops-ibn"
    environment = var.environment
    tenant      = var.tenant
  }
}

resource "google_project_service" "enabled" {
  for_each = toset(var.enabled_apis)

  project            = google_project.this.project_id
  service            = each.value
  disable_on_destroy = false
}

resource "google_billing_budget" "guardrail" {
  count = var.monthly_budget_usd > 0 ? 1 : 0

  billing_account = var.billing_account
  display_name    = "${var.project_id}-budget"

  budget_filter {
    projects = ["projects/${google_project.this.number}"]
  }

  amount {
    specified_amount {
      currency_code = "USD"
      units         = tostring(var.monthly_budget_usd)
    }
  }

  threshold_rules {
    threshold_percent = 0.8
  }
  threshold_rules {
    threshold_percent = 1.0
  }
}
