variable "project_id" {
  description = "Globally-unique project ID, e.g. acme-ibn-lab"
  type        = string
}

variable "display_name" {
  type = string
}

variable "environment" {
  description = "lab | staging | prod"
  type        = string

  validation {
    condition     = contains(["lab", "staging", "prod"], var.environment)
    error_message = "environment must be lab, staging or prod."
  }
}

variable "tenant" {
  description = "Tenant slug for productized per-customer projects; 'shared' otherwise"
  type        = string
  default     = "shared"
}

variable "folder_id" {
  description = "Parent folder (numeric ID); null to create under the org root"
  type        = string
  default     = null
}

variable "billing_account" {
  type = string
}

variable "monthly_budget_usd" {
  description = "0 disables the budget guardrail"
  type        = number
  default     = 0
}

variable "enabled_apis" {
  type = list(string)
  default = [
    "compute.googleapis.com",
    "container.googleapis.com",
    "secretmanager.googleapis.com",
    "artifactregistry.googleapis.com",
    "monitoring.googleapis.com",
    "logging.googleapis.com",
  ]
}
