variable "org_slug" {
  description = "Short organization identifier used in globally-unique names"
  type        = string
}

variable "seed_project_id" {
  description = "Existing project that hosts the state bucket and CI identity"
  type        = string
}

variable "region" {
  description = "Default region for bootstrap resources"
  type        = string
  default     = "southamerica-east1"
}
