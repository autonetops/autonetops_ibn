# Lab environment — the fully-worked example. Staging/prod are the same
# composition with different tfvars (never a code fork).

terraform {
  required_version = ">= 1.7"

  backend "gcs" {
    # bucket via -backend-config=backend.hcl (created by ../../bootstrap)
    prefix = "env/lab"
  }

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
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

provider "google" {
  region = var.region
}

module "project" {
  source = "../../modules/project"

  project_id         = "${var.org_slug}-ibn-lab"
  display_name       = "IBN Platform — Lab"
  environment        = "lab"
  billing_account    = var.billing_account
  folder_id          = var.folder_id
  monthly_budget_usd = 300
}

module "network" {
  source = "../../modules/network"

  project_id = module.project.project_id
  subnets = {
    (var.region) = "10.64.0.0/20"
  }
}

module "cluster" {
  source = "../../modules/k8s-cluster"

  project_id  = module.project.project_id
  environment = "lab"
  region      = var.region
  network_id  = module.network.network_id
  subnet_id   = module.network.subnet_ids[var.region]
}

# Providers for in-cluster resources. At Stage 2 (state-per-stack) this moves
# to a 30-platform stack reading cluster outputs via remote state.
data "google_client_config" "current" {}

provider "kubernetes" {
  host                   = "https://${module.cluster.cluster_endpoint}"
  token                  = data.google_client_config.current.access_token
  cluster_ca_certificate = null # populated after first apply; see README
}

provider "helm" {
  kubernetes {
    host  = "https://${module.cluster.cluster_endpoint}"
    token = data.google_client_config.current.access_token
  }
}

module "platform" {
  source = "../../modules/ibn-platform"

  infrahub_chart_version        = var.infrahub_chart_version
  prefect_chart_version         = var.prefect_chart_version
  kube_prometheus_stack_version = var.kube_prometheus_stack_version
}
