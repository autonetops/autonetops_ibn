variable "org_slug" {
  type = string
}

variable "billing_account" {
  type = string
}

variable "folder_id" {
  type    = string
  default = null
}

variable "region" {
  type    = string
  default = "southamerica-east1"
}

variable "infrahub_chart_version" {
  type = string
}

variable "prefect_chart_version" {
  type = string
}

variable "kube_prometheus_stack_version" {
  type = string
}
